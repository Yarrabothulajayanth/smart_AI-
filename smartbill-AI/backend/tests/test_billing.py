import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.auth import require_owner
from app.database import get_db
from app.models import (
    InventoryMovement,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
)
from tests.test_products import ASGIClient


class BillingApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = TemporaryDirectory(prefix="smartbill-billing-tests-")
        database_path = Path(self.temp_dir.name) / "billing-test.sqlite"
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
            "POST", "/categories/", {"name": "Billing Grocery"}
        )
        self.assertEqual(category_status, 201)
        assert isinstance(category, dict)
        self.category_id = int(category["id"])
        self.barcode_number = 0

    async def asyncTearDown(self) -> None:
        try:
            await self.lifespan.__aexit__(None, None, None)
        finally:
            main.engine = self.previous_engine
            main.app.dependency_overrides.clear()
            main.app.dependency_overrides.update(self.previous_overrides)
            self.engine.dispose()
            self.temp_dir.cleanup()

    async def create_product(
        self,
        *,
        name: str = "Rice",
        selling_price: str = "10.00",
        gst_applicable: bool = True,
        gst_rate: str = "5.00",
        unit_of_measure: str = "piece",
    ) -> dict[str, object]:
        self.barcode_number += 1
        payload: dict[str, object] = {
            "name": name,
            "barcode": f"BILL-{self.barcode_number}",
            "category_id": self.category_id,
            "purchase_price": "5.00",
            "selling_price": selling_price,
            "gst_applicable": gst_applicable,
            "gst_rate": gst_rate if gst_applicable else "0.00",
            "unit_of_measure": unit_of_measure,
        }
        status_code, product = await self.client.request(
            "POST", "/products/", payload
        )
        self.assertEqual(status_code, 201, product)
        assert isinstance(product, dict)
        return product

    async def post_invoice(
        self,
        items: list[dict[str, str | int]],
        payment_amount: str,
        *,
        payment_method: str = "cash",
        discount_amount: str = "0.00",
        customer_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, object]:
        payload: dict[str, object] = {
            "items": items,
            "payment_method": payment_method,
            "payment_amount": payment_amount,
            "discount_amount": discount_amount,
        }
        if customer_id is not None:
            payload["customer_id"] = customer_id
        return await self.client.request(
            "POST",
            "/invoices/",
            payload,
            headers={"Idempotency-Key": idempotency_key or str(uuid4())},
        )

    def counts(self) -> tuple[int, int, int, int]:
        with Session(self.engine) as db:
            return (
                len(db.scalars(select(Invoice)).all()),
                len(db.scalars(select(InvoiceItem)).all()),
                len(db.scalars(select(Payment)).all()),
                len(db.scalars(select(InventoryMovement)).all()),
            )

    async def test_successful_single_product_sale_creates_invoice_and_payment(self) -> None:
        product = await self.create_product()
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "2.000"}],
            "21.00",
        )

        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(invoice["subtotal"], "20.00")
        self.assertEqual(invoice["tax_total"], "1.00")
        self.assertEqual(invoice["total_amount"], "21.00")
        self.assertEqual(invoice["items"][0]["product_name"], "Rice")
        self.assertEqual(invoice["payments"][0]["payment_status"], "paid")
        with Session(self.engine) as db:
            stored_product = db.get(Product, product["id"])
            self.assertIsNotNone(stored_product)
            assert stored_product is not None
            self.assertEqual(stored_product.stock_quantity, Decimal("0.000"))
            self.assertEqual(len(db.scalars(select(InventoryMovement)).all()), 0)

    async def test_successful_multiple_product_sale(self) -> None:
        first = await self.create_product(name="Rice")
        second = await self.create_product(
            name="Beans",
            selling_price="3.00",
            gst_applicable=False,
        )
        status_code, invoice = await self.post_invoice(
            [
                {"product_id": int(first["id"]), "quantity": "2.000"},
                {"product_id": int(second["id"]), "quantity": "2.000"},
            ],
            "27.00",
        )

        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(len(invoice["items"]), 2)
        self.assertEqual(invoice["subtotal"], "26.00")
        self.assertEqual(invoice["total_amount"], "27.00")
        with Session(self.engine) as db:
            self.assertEqual(db.get(Product, first["id"]).stock_quantity, Decimal("0.000"))
            self.assertEqual(db.get(Product, second["id"]).stock_quantity, Decimal("0.000"))
            self.assertEqual(len(db.scalars(select(InventoryMovement)).all()), 0)

    async def test_duplicate_product_lines_are_combined(self) -> None:
        product = await self.create_product(gst_applicable=False)
        status_code, invoice = await self.post_invoice(
            [
                {"product_id": int(product["id"]), "quantity": "1.000"},
                {"product_id": int(product["id"]), "quantity": "1.000"},
            ],
            "20.00",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(len(invoice["items"]), 1)
        self.assertEqual(invoice["items"][0]["quantity"], "2.000")
        with Session(self.engine) as db:
            stored_product = db.get(Product, product["id"])
            self.assertIsNotNone(stored_product)
            assert stored_product is not None
            self.assertEqual(stored_product.stock_quantity, Decimal("0.000"))

    async def test_gst_is_calculated_from_product_rate(self) -> None:
        product = await self.create_product(selling_price="12.00", gst_rate="18.00")
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "14.16",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(invoice["items"][0]["gst_rate"], "18.00")
        self.assertEqual(invoice["items"][0]["tax_amount"], "2.16")
        self.assertEqual(invoice["total_amount"], "14.16")

    async def test_gst_uses_half_up_rounding_to_two_decimals(self) -> None:
        product = await self.create_product(
            selling_price="0.05", gst_rate="10.00"
        )
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "0.06",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(invoice["items"][0]["tax_amount"], "0.01")
        self.assertEqual(invoice["total_amount"], "0.06")

    async def test_non_gst_product_has_no_tax(self) -> None:
        product = await self.create_product(
            selling_price="12.00", gst_applicable=False
        )
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "12.00",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(invoice["items"][0]["tax_amount"], "0.00")
        self.assertEqual(invoice["items"][0]["non_taxable_value"], "12.00")
        self.assertEqual(invoice["tax_total"], "0.00")

    async def test_mixed_gst_and_non_gst_items_with_discount(self) -> None:
        taxable = await self.create_product(
            name="Taxable rice", selling_price="10.00"
        )
        non_taxable = await self.create_product(
            name="Fresh produce",
            selling_price="3.00",
            gst_applicable=False,
        )
        status_code, invoice = await self.post_invoice(
            [
                {"product_id": int(taxable["id"]), "quantity": "2.000"},
                {"product_id": int(non_taxable["id"]), "quantity": "1.000"},
            ],
            "21.60",
            discount_amount="2.30",
        )

        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertEqual(invoice["subtotal"], "23.00")
        self.assertEqual(invoice["discount_amount"], "2.30")
        self.assertEqual(invoice["taxable_amount"], "18.00")
        self.assertEqual(invoice["non_taxable_amount"], "2.70")
        self.assertEqual(invoice["tax_total"], "0.90")
        self.assertEqual(invoice["total_amount"], "21.60")
        self.assertEqual(
            [item["discount_amount"] for item in invoice["items"]],
            ["2.00", "0.30"],
        )

    async def test_cash_and_upi_are_recorded_as_paid(self) -> None:
        product = await self.create_product(
            selling_price="12.50", gst_applicable=False
        )
        for method in ("cash", "upi"):
            with self.subTest(method=method):
                status_code, invoice = await self.post_invoice(
                    [{"product_id": int(product["id"]), "quantity": "1.000"}],
                    "12.50",
                    payment_method=method,
                )
                self.assertEqual(status_code, 201)
                assert isinstance(invoice, dict)
                self.assertEqual(invoice["payments"][0]["payment_method"], method)
                self.assertEqual(invoice["payments"][0]["amount"], "12.50")
                self.assertEqual(invoice["payments"][0]["payment_status"], "paid")

    async def test_invoice_numbers_are_unique(self) -> None:
        product = await self.create_product(gst_applicable=False)
        invoice_numbers: list[str] = []
        for _ in range(2):
            status_code, invoice = await self.post_invoice(
                [{"product_id": int(product["id"]), "quantity": "1.000"}],
                "10.00",
            )
            self.assertEqual(status_code, 201)
            assert isinstance(invoice, dict)
            invoice_numbers.append(str(invoice["invoice_number"]))
        self.assertNotEqual(invoice_numbers[0], invoice_numbers[1])
        self.assertEqual(len(set(invoice_numbers)), 2)

    async def test_idempotent_retry_does_not_duplicate_invoice(self) -> None:
        product = await self.create_product()
        key = str(uuid4())
        payload_items = [{"product_id": int(product["id"]), "quantity": "1.000"}]
        first_status, first_invoice = await self.post_invoice(
            payload_items, "10.50", idempotency_key=key
        )
        retry_status, retry_invoice = await self.post_invoice(
            payload_items, "10.50", idempotency_key=key
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(retry_status, 200)
        assert isinstance(first_invoice, dict)
        assert isinstance(retry_invoice, dict)
        self.assertEqual(first_invoice["id"], retry_invoice["id"])
        self.assertEqual(self.counts(), (1, 1, 1, 0))
        with Session(self.engine) as db:
            stored_product = db.get(Product, product["id"])
            self.assertIsNotNone(stored_product)
            assert stored_product is not None
            self.assertEqual(stored_product.stock_quantity, Decimal("0.000"))

    async def test_idempotency_key_cannot_be_reused_for_another_request(self) -> None:
        first = await self.create_product(name="Rice", gst_applicable=False)
        second = await self.create_product(name="Beans", gst_applicable=False)
        key = str(uuid4())
        first_status, _ = await self.post_invoice(
            [{"product_id": int(first["id"]), "quantity": "1.000"}],
            "10.00",
            idempotency_key=key,
        )
        second_status, error = await self.post_invoice(
            [{"product_id": int(second["id"]), "quantity": "1.000"}],
            "10.00",
            idempotency_key=key,
        )
        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 409)
        self.assertIn("different request", error["detail"])
        self.assertEqual(self.counts(), (1, 1, 1, 0))

    async def test_billing_ignores_legacy_stock_and_does_not_create_movements(self) -> None:
        product = await self.create_product()
        status_code, error = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "100.000"}],
            "1050.00",
        )
        self.assertEqual(status_code, 201, error)
        self.assertEqual(self.counts(), (1, 1, 1, 0))
        with Session(self.engine) as db:
            stored_product = db.get(Product, product["id"])
            self.assertIsNotNone(stored_product)
            assert stored_product is not None
            self.assertEqual(stored_product.stock_quantity, Decimal("0.000"))

    async def test_negative_quantity_is_rejected(self) -> None:
        product = await self.create_product()
        status_code, error = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "-1.000"}],
            "0.00",
        )
        self.assertEqual(status_code, 422)
        self.assertIsNotNone(error)
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    async def test_unknown_product_is_rejected(self) -> None:
        status_code, error = await self.post_invoice(
            [{"product_id": 999999, "quantity": "1.000"}],
            "10.50",
        )
        self.assertEqual(status_code, 404)
        self.assertIn("product 999999", error["detail"])
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    async def test_payment_must_equal_invoice_total(self) -> None:
        product = await self.create_product(gst_applicable=False)
        status_code, error = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "9.99",
        )
        self.assertEqual(status_code, 422)
        self.assertIn("exactly match", error["detail"])
        self.assertEqual(self.counts(), (0, 0, 0, 0))

    async def test_customer_is_optional_for_walk_in_billing(self) -> None:
        product = await self.create_product(gst_applicable=False)
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "10.00",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)
        self.assertIsNone(invoice["customer_id"])

    async def test_database_failure_rolls_back_invoice_and_payment(self) -> None:
        product = await self.create_product()
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TRIGGER reject_test_payment
                BEFORE INSERT ON payments
                BEGIN
                    SELECT RAISE(ABORT, 'forced test failure');
                END
                """
            )

        with self.assertLogs("app.routers.invoices", level="ERROR") as logs:
            status_code, error = await self.post_invoice(
                [{"product_id": int(product["id"]), "quantity": "1.000"}],
                "10.50",
            )
        self.assertEqual(status_code, 500)
        self.assertIn("transaction was rolled back", logs.output[0])
        self.assertIn("rolled back", error["detail"])
        self.assertEqual(self.counts(), (0, 0, 0, 0))
        with Session(self.engine) as db:
            stored_product = db.get(Product, product["id"])
            self.assertIsNotNone(stored_product)
            assert stored_product is not None
            self.assertEqual(stored_product.stock_quantity, Decimal("0.000"))

    async def test_invoice_can_be_retrieved_by_id_and_number_and_listed(self) -> None:
        product = await self.create_product(gst_applicable=False)
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "10.00",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)

        by_id_status, by_id = await self.client.request(
            "GET", f"/invoices/{invoice['id']}"
        )
        by_number_status, by_number = await self.client.request(
            "GET", f"/invoices/number/{invoice['invoice_number']}"
        )
        list_status, listed = await self.client.request("GET", "/invoices/")
        search_status, searched = await self.client.request(
            "GET", f"/invoices/?search={invoice['invoice_number'][-6:]}"
        )
        self.assertEqual(by_id_status, 200)
        self.assertEqual(by_number_status, 200)
        self.assertEqual(list_status, 200)
        self.assertEqual(search_status, 200)
        self.assertEqual(by_id["invoice_number"], invoice["invoice_number"])
        self.assertEqual(by_number["id"], invoice["id"])
        self.assertEqual(len(listed), 1)
        self.assertEqual([item["id"] for item in searched], [invoice["id"]])

    async def test_invoice_pdf_is_downloadable_a4_pdf(self) -> None:
        product = await self.create_product(gst_applicable=False)
        status_code, invoice = await self.post_invoice(
            [{"product_id": int(product["id"]), "quantity": "1.000"}],
            "10.00",
        )
        self.assertEqual(status_code, 201)
        assert isinstance(invoice, dict)

        pdf_status, body, headers = await self.client.request_raw(
            "GET", f"/invoices/{invoice['id']}/pdf"
        )
        self.assertEqual(pdf_status, 200)
        self.assertEqual(headers["content-type"], "application/pdf")
        self.assertIn("attachment;", headers["content-disposition"])
        self.assertTrue(body.startswith(b"%PDF-"))

    async def test_billing_routes_are_documented_in_openapi(self) -> None:
        paths = main.app.openapi()["paths"]
        expected_methods = {
            "/invoices/": {"get", "post"},
            "/invoices/{invoice_id}": {"get"},
            "/invoices/number/{invoice_number}": {"get"},
            "/invoices/{invoice_id}/pdf": {"get"},
        }
        for path, methods in expected_methods.items():
            self.assertTrue(methods.issubset(paths[path].keys()), path)
        post_parameters = paths["/invoices/"]["post"]["parameters"]
        self.assertTrue(
            any(parameter["name"] == "idempotency-key" for parameter in post_parameters)
        )
        docs_status, docs_body, docs_headers = await self.client.request_raw(
            "GET", "/docs"
        )
        openapi_status, openapi_body, openapi_headers = await self.client.request_raw(
            "GET", "/openapi.json"
        )
        self.assertEqual(docs_status, 200)
        self.assertTrue(docs_headers["content-type"].startswith("text/html"))
        self.assertEqual(openapi_status, 200)
        self.assertIn(b"/invoices/", openapi_body)
        self.assertIn("application/json", openapi_headers["content-type"])


if __name__ == "__main__":
    unittest.main()
