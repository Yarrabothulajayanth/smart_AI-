import json
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Message, Scope

from app import main
from app.auth import require_owner
from app.database import get_db
from app.models import InventoryMovement, Product


class ASGIClient:
    def __init__(self, application: ASGIApp) -> None:
        self.application = application

    async def request(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        status, response_content, _ = await self.request_raw(
            method, url, payload, headers
        )
        response_data = (
            json.loads(response_content) if response_content else None
        )
        return status, response_data

    async def request_raw(
        self,
        method: str,
        url: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        parsed_url = urlsplit(url)
        body = json.dumps(payload).encode() if payload is not None else b""
        request_sent = False
        response_start: dict[str, Any] = {}
        response_body: list[bytes] = []
        response_headers: dict[str, str] = {}

        async def receive() -> Message:
            nonlocal request_sent
            if request_sent:
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_start["status"] = message["status"]
                response_headers.update(
                    {
                        key.decode("latin-1").lower(): value.decode("latin-1")
                        for key, value in message.get("headers", [])
                    }
                )
            elif message["type"] == "http.response.body":
                content = message.get("body", b"")
                if isinstance(content, bytes):
                    response_body.append(content)

        scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": parsed_url.path,
            "raw_path": parsed_url.path.encode(),
            "query_string": parsed_url.query.encode(),
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            + [
                (key.lower().encode(), value.encode())
                for key, value in (headers or {}).items()
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "app": self.application,
            "state": {},
        }
        await self.application(scope, receive, send)

        response_content = b"".join(response_body)
        response_status = response_start.get("status")
        if not isinstance(response_status, int):
            raise RuntimeError("ASGI response did not contain a status code.")
        return response_status, response_content, response_headers


class ProductApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = TemporaryDirectory(prefix="smartbill-product-tests-")
        database_path = Path(self.temp_dir.name) / "test.sqlite"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(
            dbapi_connection: object, _connection_record: object
        ) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.previous_engine = main.engine
        self.previous_overrides = main.app.dependency_overrides.copy()
        main.engine = self.engine

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_get_db
        main.app.dependency_overrides[require_owner] = lambda: "test-owner"
        self.lifespan = main.app.router.lifespan_context(main.app)
        await self.lifespan.__aenter__()
        self.client = ASGIClient(main.app)

        category_status, category = await self.client.request(
            "POST", "/categories/", {"name": "Grocery"}
        )
        self.assertEqual(category_status, 201)
        assert isinstance(category, dict)
        self.category_id = int(category["id"])

    async def asyncTearDown(self) -> None:
        try:
            await self.lifespan.__aexit__(None, None, None)
        finally:
            main.engine = self.previous_engine
            main.app.dependency_overrides.clear()
            main.app.dependency_overrides.update(self.previous_overrides)
            self.engine.dispose()
            self.temp_dir.cleanup()

    def product_payload(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": "Organic Rice",
            "barcode": "BAR-100",
            "category_id": self.category_id,
            "description": "Long-grain rice",
            "purchase_price": "10.25",
            "selling_price": "15.00",
            "gst_applicable": True,
            "gst_rate": "5.00",
            "unit_of_measure": "kg",
        }
        payload.update(overrides)
        return payload

    async def create_product(
        self, **overrides: object
    ) -> tuple[int, dict[str, object]]:
        status_code, response = await self.client.request(
            "POST", "/products/", self.product_payload(**overrides)
        )
        assert isinstance(response, dict)
        return status_code, response

    async def test_create_and_retrieve_product(self) -> None:
        status_code, product = await self.create_product()
        self.assertEqual(status_code, 201)
        self.assertEqual(product["name"], "Organic Rice")
        self.assertEqual(product["barcode"], "BAR-100")
        self.assertEqual(product["is_active"], True)
        self.assertNotIn("stock_quantity", product)
        self.assertNotIn("minimum_stock_threshold", product)

        list_status, products = await self.client.request("GET", "/products/")
        self.assertEqual(list_status, 200)
        self.assertEqual(len(products), 1)

        get_status, stored = await self.client.request(
            "GET", f"/products/{product['id']}"
        )
        self.assertEqual(get_status, 200)
        self.assertEqual(stored["purchase_price"], "10.25")

    async def test_update_product_updates_only_catalog_fields(self) -> None:
        _, product = await self.create_product()
        updates = self.product_payload(
            name="Premium Rice",
            purchase_price="11.00",
            selling_price="17.50",
        )

        status_code, updated = await self.client.request(
            "PUT", f"/products/{product['id']}", updates
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(updated["name"], "Premium Rice")
        self.assertEqual(updated["purchase_price"], "11.00")
        self.assertNotIn("stock_quantity", updated)

    async def test_deactivate_product_keeps_inventory_references(self) -> None:
        _, product = await self.create_product()
        with Session(self.engine) as db:
            stored_product = db.get(Product, product["id"])
            assert stored_product is not None
            db.add(
                InventoryMovement(
                    product=stored_product,
                    movement_type="initial",
                    quantity=Decimal("8.500"),
                )
            )
            db.commit()

        status_code, deactivated = await self.client.request(
            "DELETE", f"/products/{product['id']}"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(deactivated["is_active"], False)

        with Session(self.engine) as db:
            self.assertIsNotNone(db.get(Product, product["id"]))
            self.assertEqual(
                len(db.scalars(select(InventoryMovement)).all()),
                1,
            )

        list_status, products = await self.client.request("GET", "/products/")
        self.assertEqual(list_status, 200)
        self.assertEqual(products, [])
        inactive_status, inactive_products = await self.client.request(
            "GET", "/products/?include_inactive=true"
        )
        self.assertEqual(inactive_status, 200)
        self.assertEqual(len(inactive_products), 1)

    async def test_search_products_by_name(self) -> None:
        await self.create_product()
        status_code, results = await self.client.request(
            "GET", "/products/search/organic"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(len(results), 1)

    async def test_search_products_by_barcode(self) -> None:
        _, product = await self.create_product()
        status_code, result = await self.client.request(
            "GET", f"/products/barcode/{product['barcode']}"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(result["id"], product["id"])

    async def test_create_list_update_and_delete_category(self) -> None:
        status_code, category = await self.client.request(
            "POST", "/categories/", {"name": "Beverages"}
        )
        self.assertEqual(status_code, 201)
        assert isinstance(category, dict)

        list_status, categories = await self.client.request("GET", "/categories/")
        self.assertEqual(list_status, 200)
        self.assertEqual(len(categories), 2)

        update_status, updated = await self.client.request(
            "PUT",
            f"/categories/{category['id']}",
            {"name": "Drinks", "description": "Cold and hot drinks"},
        )
        self.assertEqual(update_status, 200)
        self.assertEqual(updated["name"], "Drinks")

        delete_status, _ = await self.client.request(
            "DELETE", f"/categories/{category['id']}"
        )
        self.assertEqual(delete_status, 204)

    async def test_duplicate_category_name_is_rejected(self) -> None:
        status_code, response = await self.client.request(
            "POST", "/categories/", {"name": "Grocery"}
        )
        self.assertEqual(status_code, 409)
        self.assertIn("already exists", response["detail"])

    async def test_category_in_use_cannot_be_deleted(self) -> None:
        await self.create_product()
        status_code, response = await self.client.request(
            "DELETE", f"/categories/{self.category_id}"
        )
        self.assertEqual(status_code, 409)
        self.assertIn("products use it", response["detail"])

    async def test_duplicate_barcode_is_rejected(self) -> None:
        await self.create_product()
        status_code, response = await self.client.request(
            "POST",
            "/products/",
            self.product_payload(name="Another Rice"),
        )
        self.assertEqual(status_code, 409)
        self.assertIn("barcode", response["detail"])

    async def test_negative_price_is_rejected(self) -> None:
        status_code, response = await self.client.request(
            "POST", "/products/", self.product_payload(purchase_price="-0.01")
        )
        self.assertEqual(status_code, 422)
        self.assertIsNotNone(response)

    async def test_stock_fields_are_not_accepted_by_product_api(self) -> None:
        status_code, response = await self.client.request(
            "POST",
            "/products/",
            self.product_payload(stock_quantity="10.000"),
        )
        self.assertEqual(status_code, 422)
        self.assertIsNotNone(response)

    async def test_nonexistent_category_is_rejected(self) -> None:
        status_code, response = await self.client.request(
            "POST", "/products/", self.product_payload(category_id=999999)
        )
        self.assertEqual(status_code, 404)
        self.assertEqual(response["detail"], "Category not found.")

    async def test_blank_product_name_is_rejected(self) -> None:
        status_code, response = await self.client.request(
            "POST", "/products/", self.product_payload(name="   ")
        )
        self.assertEqual(status_code, 422)
        self.assertIsNotNone(response)

    async def test_product_and_category_routes_are_in_openapi(self) -> None:
        paths = main.app.openapi()["paths"]
        expected_methods = {
            "/products/": {"get", "post"},
            "/products/{product_id}": {"get", "put", "delete"},
            "/products/search/{name}": {"get"},
            "/products/barcode/{barcode}": {"get"},
            "/categories/": {"get", "post"},
            "/categories/{category_id}": {"put", "delete"},
        }
        for path, methods in expected_methods.items():
            self.assertTrue(methods.issubset(paths[path].keys()), path)
        product_schema = main.app.openapi()["components"]["schemas"]["ProductCreate"]
        self.assertNotIn("stock_quantity", product_schema["properties"])
        self.assertNotIn("minimum_stock_threshold", product_schema["properties"])


if __name__ == "__main__":
    unittest.main()
