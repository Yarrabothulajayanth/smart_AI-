import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import main
from app.auth import require_owner
from app.database import get_db
from app.routers.reports import BUSINESS_TIMEZONE
from tests.test_products import ASGIClient


class CustomerAndReportsApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = TemporaryDirectory(prefix="smartbill-customer-report-tests-")
        database_path = Path(self.temp_dir.name) / "customer-report-test.sqlite"
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

        status_code, category = await self.client.request(
            "POST", "/categories/", {"name": "Customer Report Grocery"}
        )
        self.assertEqual(status_code, 201)
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

    async def create_customer(self) -> dict[str, object]:
        status_code, customer = await self.client.request(
            "POST",
            "/customers/",
            {
                "name": "Maya Singh",
                "email": "maya@example.test",
                "phone": "555-0100",
                "address": "12 Market Road",
            },
        )
        self.assertEqual(status_code, 201, customer)
        assert isinstance(customer, dict)
        return customer

    async def create_product(self) -> dict[str, object]:
        self.barcode_number += 1
        status_code, product = await self.client.request(
            "POST",
            "/products/",
            {
                "name": "Wholegrain Rice",
                "barcode": f"REPORT-{self.barcode_number}",
                "category_id": self.category_id,
                "purchase_price": "5.00",
                "selling_price": "10.00",
                "gst_applicable": True,
                "gst_rate": "5.00",
                "unit_of_measure": "kg",
            },
        )
        self.assertEqual(status_code, 201, product)
        assert isinstance(product, dict)
        self.assertNotIn("stock_quantity", product)
        return product

    async def create_invoice(
        self, product_id: int, customer_id: int | None = None
    ) -> dict[str, object]:
        request_payload: dict[str, object] = {
            "items": [{"product_id": product_id, "quantity": "1.000"}],
            "discount_amount": "0.00",
        }
        quote_status, quote = await self.client.request(
            "POST", "/invoices/quote", request_payload
        )
        self.assertEqual(quote_status, 200, quote)
        assert isinstance(quote, dict)
        invoice_payload = {
            **request_payload,
            "payment_method": "cash",
            "payment_amount": quote["total_amount"],
        }
        if customer_id is not None:
            invoice_payload["customer_id"] = customer_id
        status_code, invoice = await self.client.request(
            "POST",
            "/invoices/",
            invoice_payload,
            headers={"Idempotency-Key": str(uuid4())},
        )
        self.assertEqual(status_code, 201, invoice)
        assert isinstance(invoice, dict)
        return invoice

    async def test_customer_create_search_update_detail_and_invoice_history(self) -> None:
        customer = await self.create_customer()
        product = await self.create_product()
        invoice = await self.create_invoice(
            int(product["id"]), int(customer["id"])
        )

        search_status, customers = await self.client.request(
            "GET", "/customers/?search=maya"
        )
        get_status, stored = await self.client.request(
            "GET", f"/customers/{customer['id']}"
        )
        update_status, updated = await self.client.request(
            "PUT",
            f"/customers/{customer['id']}",
            {
                "name": "Maya Shah",
                "email": "maya.shah@example.test",
                "phone": "555-0101",
                "address": "18 Market Road",
            },
        )
        invoices_status, invoices = await self.client.request(
            "GET", f"/customers/{customer['id']}/invoices"
        )

        self.assertEqual(search_status, 200)
        self.assertEqual(len(customers), 1)
        self.assertEqual(get_status, 200)
        self.assertEqual(stored["name"], "Maya Singh")
        self.assertEqual(update_status, 200)
        self.assertEqual(updated["name"], "Maya Shah")
        self.assertEqual(invoices_status, 200)
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["id"], invoice["id"])
        self.assertEqual(invoices[0]["customer_name"], "Maya Shah")

    async def test_quote_returns_backend_calculation_without_writes(self) -> None:
        product = await self.create_product()
        status_code, quote = await self.client.request(
            "POST",
            "/invoices/quote",
            {
                "items": [{"product_id": int(product["id"]), "quantity": "2.000"}],
                "discount_amount": "1.00",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(quote["subtotal"], "20.00")
        self.assertEqual(quote["discount_amount"], "1.00")
        self.assertEqual(quote["taxable_amount"], "19.00")
        self.assertEqual(quote["tax_total"], "0.95")
        self.assertEqual(quote["total_amount"], "19.95")
        self.assertEqual(quote["items"][0]["unit_of_measure"], "kg")
        invoices_status, invoices = await self.client.request("GET", "/invoices/")
        self.assertEqual(invoices_status, 200)
        self.assertEqual(invoices, [])

    async def test_dashboard_uses_actual_invoice_and_customer_data(self) -> None:
        customer = await self.create_customer()
        product = await self.create_product()
        first_invoice = await self.create_invoice(
            int(product["id"]), int(customer["id"])
        )
        second_invoice = await self.create_invoice(int(product["id"]))

        status_code, dashboard = await self.client.request(
            "GET", "/reports/dashboard"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(dashboard["today_revenue"], "20.00")
        self.assertEqual(dashboard["today_invoice_count"], 2)
        self.assertEqual(dashboard["monthly_revenue"], "20.00")
        self.assertEqual(dashboard["total_invoices"], 2)
        self.assertEqual(dashboard["total_customers"], 1)
        self.assertEqual(len(dashboard["recent_invoices"]), 2)
        self.assertEqual(
            {row["id"] for row in dashboard["recent_invoices"]},
            {first_invoice["id"], second_invoice["id"]},
        )
        self.assertEqual(len(dashboard["sales_overview"]), 7)
        self.assertIsNone(dashboard["profit"])
        self.assertIn("purchase-price snapshots", dashboard["profit_note"])

    async def test_daily_weekly_monthly_and_custom_sales_reports(self) -> None:
        product = await self.create_product()
        await self.create_invoice(int(product["id"]))
        today = datetime.now(BUSINESS_TIMEZONE).date().isoformat()
        report_urls = [
            "/reports/sales?period=daily",
            "/reports/sales?period=weekly",
            "/reports/sales?period=monthly",
            "/reports/sales?"
            + urlencode(
                {"period": "custom", "start_date": today, "end_date": today}
            ),
        ]
        for url in report_urls:
            with self.subTest(url=url):
                status_code, report = await self.client.request("GET", url)
                self.assertEqual(status_code, 200)
                self.assertEqual(report["revenue"], "10.00")
                self.assertEqual(report["gross_collected"], "10.50")
                self.assertEqual(report["gst_collected"], "0.50")
                self.assertEqual(report["invoice_count"], 1)
                self.assertEqual(report["best_selling_products"][0]["quantity_sold"], "1.000")
                self.assertIsNone(report["profit"])

    async def test_custom_report_requires_valid_date_range(self) -> None:
        missing_status, _ = await self.client.request(
            "GET", "/reports/sales?period=custom"
        )
        invalid_status, error = await self.client.request(
            "GET",
            "/reports/sales?"
            + urlencode(
                {
                    "period": "custom",
                    "start_date": "2026-11-25",
                    "end_date": "2026-11-24",
                }
            ),
        )
        self.assertEqual(missing_status, 422)
        self.assertEqual(invalid_status, 422)
        self.assertIn("on or before", error["detail"])

    async def test_frontend_origin_is_allowed_by_cors(self) -> None:
        status_code, _, headers = await self.client.request_raw(
            "OPTIONS",
            "/reports/dashboard",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(
            headers["access-control-allow-origin"], "http://localhost:5173"
        )

    async def test_customer_and_report_routes_are_documented(self) -> None:
        paths = main.app.openapi()["paths"]
        expected = {
            "/customers/": {"get", "post"},
            "/customers/{customer_id}": {"get", "put"},
            "/customers/{customer_id}/invoices": {"get"},
            "/invoices/quote": {"post"},
            "/reports/dashboard": {"get"},
            "/reports/sales": {"get"},
        }
        for path, methods in expected.items():
            self.assertTrue(methods.issubset(paths[path].keys()), path)


if __name__ == "__main__":
    unittest.main()
