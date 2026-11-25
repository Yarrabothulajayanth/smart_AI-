import json
import os
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import main
from app.auth import require_owner
from app.database import DATABASE_PATH, get_db
from app.models import (
    Category,
    Customer,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
)
from app.routers.reports import BUSINESS_TIMEZONE
from app.services.ai_provider import AIProviderError, AISettings
from app.services.assistant import get_ai_provider, get_rag_store
from app.services.rag import RAGStore
from tests.test_products import ASGIClient


class FakeAIProvider:
    def __init__(self) -> None:
        self.fail_chat = False
        self.document_answer = (
            "The policy allows returns within seven days [returns.md, chunk 1]."
        )

    async def chat(self, messages: list[dict[str, str]]) -> str:
        if self.fail_chat:
            raise AIProviderError("The test provider is unavailable.")
        system_message = messages[0]["content"]
        if system_message.startswith("Classify"):
            return json.dumps(self._plan(messages[1]["content"]))
        return self.document_answer

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    float("refund" in lowered or "return" in lowered),
                    float("seven" in lowered or "7 days" in lowered),
                    float("rice" in lowered),
                ]
            )
        return vectors

    @staticmethod
    def _plan(question: str) -> dict[str, object]:
        lowered = question.lower()
        common: dict[str, object] = {
            "intent": "general",
            "query": None,
            "period": None,
            "start_date": None,
            "end_date": None,
            "compare_start_date": None,
            "compare_end_date": None,
        }
        today = datetime.now(BUSINESS_TIMEZONE).date()
        if "compare" in lowered:
            common.update(
                {
                    "intent": "sales_comparison",
                    "start_date": today.isoformat(),
                    "end_date": today.isoformat(),
                    "compare_start_date": (today - timedelta(days=1)).isoformat(),
                    "compare_end_date": (today - timedelta(days=1)).isoformat(),
                }
            )
        elif "top selling" in lowered or "best selling" in lowered:
            common.update({"intent": "best_sellers", "period": "monthly"})
        elif "total invoices" in lowered or "invoice count" in lowered:
            common.update({"intent": "business_totals"})
        elif "sales" in lowered or "అమ్మకాలు" in question:
            common.update({"intent": "sales_summary", "period": "daily"})
        elif "rice" in lowered and ("product" in lowered or "price" in lowered):
            common.update({"intent": "product_search", "query": "Rice"})
        elif "invoice" in lowered or "sb-test" in lowered:
            query = "1" if "invoice id" in lowered else "SB-TEST"
            common.update({"intent": "invoice_search", "query": query})
        elif "customer" in lowered or "maya" in lowered:
            common.update({"intent": "customer_search", "query": "Maya"})
        elif "refund" in lowered or "return" in lowered:
            common.update({"intent": "document_question"})
        return common


class AssistantApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = TemporaryDirectory(prefix="smartbill-assistant-tests-")
        self.database_path = Path(self.temp_dir.name) / "assistant-test.sqlite"
        self.engine = create_engine(
            f"sqlite:///{self.database_path.as_posix()}",
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
        self.provider = FakeAIProvider()
        self.rag_store = RAGStore(Path(self.temp_dir.name) / "rag-test.sqlite")

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_get_db
        main.app.dependency_overrides[require_owner] = lambda: "test-owner"
        main.app.dependency_overrides[get_ai_provider] = lambda: self.provider
        main.app.dependency_overrides[get_rag_store] = lambda: self.rag_store
        self.lifespan = main.app.router.lifespan_context(main.app)
        await self.lifespan.__aenter__()
        self.client = ASGIClient(main.app)
        self._create_sample_records()

    def _create_sample_records(self) -> None:
        with self.session_factory() as db:
            category = Category(name="AI test grocery")
            customer = Customer(
                name="Maya Test",
                email="maya@example.test",
                phone="555-0101",
                address="1 Test Road",
            )
            product = Product(
                name="Rice",
                barcode="AI-RICE-1",
                category=category,
                purchase_price=Decimal("30.00"),
                selling_price=Decimal("50.00"),
                gst_applicable=True,
                gst_rate=Decimal("5.00"),
                unit_of_measure="kg",
                is_active=True,
            )
            invoice = Invoice(
                invoice_number="SB-TEST-001",
                customer=customer,
                subtotal=Decimal("100.00"),
                discount_amount=Decimal("10.00"),
                taxable_amount=Decimal("90.00"),
                non_taxable_amount=Decimal("0.00"),
                tax_total=Decimal("4.50"),
                total_amount=Decimal("94.50"),
                items=[
                    InvoiceItem(
                        product=product,
                        product_name="Rice",
                        unit_of_measure="kg",
                        quantity=Decimal("2.000"),
                        unit_price=Decimal("50.00"),
                        gst_applicable=True,
                        gst_rate=Decimal("5.00"),
                        line_subtotal=Decimal("100.00"),
                        discount_amount=Decimal("10.00"),
                        taxable_value=Decimal("90.00"),
                        non_taxable_value=Decimal("0.00"),
                        tax_amount=Decimal("4.50"),
                        line_total=Decimal("94.50"),
                    )
                ],
                payments=[
                    Payment(
                        amount=Decimal("94.50"),
                        payment_method="cash",
                        payment_status="paid",
                    )
                ],
            )
            db.add(invoice)
            db.commit()
            self.invoice_id = invoice.id
            self.customer_id = customer.id
            self.product_id = product.id

    async def asyncTearDown(self) -> None:
        try:
            await self.lifespan.__aexit__(None, None, None)
        finally:
            main.engine = self.previous_engine
            main.app.dependency_overrides.clear()
            main.app.dependency_overrides.update(self.previous_overrides)
            self.engine.dispose()
            self.temp_dir.cleanup()

    async def ask(self, question: str) -> tuple[int, dict[str, object]]:
        status_code, response = await self.client.request(
            "POST", "/assistant/chat", {"question": question}
        )
        assert isinstance(response, dict)
        return status_code, response

    async def test_sales_answer_uses_actual_invoice_records(self) -> None:
        status_code, response = await self.ask("What were today's sales?")
        self.assertEqual(status_code, 200, response)
        self.assertEqual(response["intent"], "sales_summary")
        self.assertIn("₹90.00", str(response["answer"]))
        self.assertIn("₹4.50", str(response["answer"]))
        self.assertIn("1", str(response["answer"]))
        with self.session_factory() as db:
            self.assertEqual(db.scalar(select(Invoice.id)), self.invoice_id)

    async def test_telugu_sales_question_returns_telugu_and_actual_totals(self) -> None:
        status_code, response = await self.ask("ఈ రోజు అమ్మకాలు ఎంత?")
        self.assertEqual(status_code, 200, response)
        self.assertEqual(response["language"], "te")
        self.assertIn("₹90.00", str(response["answer"]))
        self.assertIn("₹94.50", str(response["answer"]))

    async def test_product_invoice_and_customer_agents_read_real_records(self) -> None:
        product_status, product_response = await self.ask("Find product Rice price")
        invoice_status, invoice_response = await self.ask("Find invoice SB-TEST-001")
        customer_status, customer_response = await self.ask("Find customer Maya")
        self.assertEqual(product_status, 200)
        self.assertIn("₹50.00", str(product_response["answer"]))
        self.assertEqual(invoice_status, 200)
        self.assertIn("SB-TEST-001", str(invoice_response["answer"]))
        self.assertIn("₹94.50", str(invoice_response["answer"]))
        self.assertEqual(customer_status, 200)
        self.assertIn("555-0101", str(customer_response["answer"]))
        with self.session_factory() as db:
            self.assertIsNotNone(db.get(Product, self.product_id))
            self.assertIsNotNone(db.get(Customer, self.customer_id))
            self.assertIsNotNone(db.get(Invoice, self.invoice_id))

    async def test_invoice_assistant_can_find_invoice_by_database_id(self) -> None:
        status_code, response = await self.ask("Find invoice ID 1")
        self.assertEqual(status_code, 200, response)
        self.assertIn("SB-TEST-001", str(response["answer"]))

    async def test_sales_comparison_uses_validated_date_ranges(self) -> None:
        status_code, response = await self.ask("Compare sales for today and yesterday")
        self.assertEqual(status_code, 200, response)
        self.assertEqual(response["intent"], "sales_comparison")
        self.assertIn("₹90.00", str(response["answer"]))

    async def test_best_sellers_come_from_saved_invoice_items(self) -> None:
        status_code, response = await self.ask(
            "Show this month's best selling products"
        )
        self.assertEqual(status_code, 200, response)
        self.assertEqual(response["intent"], "best_sellers")
        self.assertIn("Rice", str(response["answer"]))
        self.assertIn("2", str(response["answer"]))

    async def test_all_time_invoice_and_customer_counts_are_actual(self) -> None:
        status_code, response = await self.ask("How many total invoices?")
        self.assertEqual(status_code, 200, response)
        self.assertEqual(response["intent"], "business_totals")
        self.assertIn("Total invoices: 1", str(response["answer"]))
        self.assertIn("total customers: 1", str(response["answer"]))

    async def test_document_ingestion_retrieval_and_grounded_answer(self) -> None:
        status_code, document = await self.client.request(
            "POST",
            "/assistant/documents",
            {
                "filename": "returns.md",
                "content": "Refunds are accepted within seven days of purchase.",
            },
        )
        self.assertEqual(status_code, 201, document)
        chat_status, response = await self.ask("What is the refund policy?")
        self.assertEqual(chat_status, 200, response)
        self.assertIn("seven days", str(response["answer"]))
        self.assertTrue(response["sources"])
        self.assertEqual(response["sources"][0]["label"], "returns.md")
        list_status, documents = await self.client.request(
            "GET", "/assistant/documents"
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(len(documents), 1)

    async def test_document_answer_falls_back_when_it_invents_a_number(self) -> None:
        _, document = await self.client.request(
            "POST",
            "/assistant/documents",
            {
                "filename": "returns.md",
                "content": "Refunds are accepted within seven days of purchase.",
            },
        )
        self.assertIsNotNone(document)
        self.provider.document_answer = "The policy gives ₹500 back to every customer."
        status_code, response = await self.ask("What is the refund policy?")
        self.assertEqual(status_code, 200, response)
        self.assertNotIn("₹500", str(response["answer"]))
        self.assertIn("Refunds are accepted within seven days", str(response["answer"]))

    async def test_document_rejects_unsupported_and_unsafe_names(self) -> None:
        status_code, _ = await self.client.request(
            "POST",
            "/assistant/documents",
            {"filename": "../private.pdf", "content": "not allowed"},
        )
        self.assertEqual(status_code, 422)

    async def test_model_cannot_select_an_unapproved_operation(self) -> None:
        status_code, response = await self.ask("Delete invoice SB-TEST-001")
        self.assertEqual(status_code, 200)
        self.assertEqual(response["intent"], "rejected_operation")
        self.assertIn("cannot", str(response["answer"]))
        with self.session_factory() as db:
            self.assertEqual(
                db.scalar(select(Invoice.id).where(Invoice.id == self.invoice_id)),
                self.invoice_id,
            )

    async def test_provider_failure_does_not_break_billing_api(self) -> None:
        self.provider.fail_chat = True
        status_code, response = await self.client.request(
            "POST", "/assistant/chat", {"question": "What were today's sales?"}
        )
        self.assertEqual(status_code, 502)
        self.assertIn("unavailable", str(response["detail"]))
        health_status, health = await self.client.request("GET", "/health")
        invoices_status, invoices = await self.client.request("GET", "/invoices/")
        self.assertEqual(health_status, 200)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(invoices_status, 200)
        self.assertEqual(len(invoices), 1)

    def test_assistant_endpoints_are_in_swagger_schema(self) -> None:
        schema = main.app.openapi()
        self.assertIn("/assistant/chat", schema["paths"])
        self.assertIn("/assistant/documents", schema["paths"])
        self.assertIn("/assistant/status", schema["paths"])
        self.assertIn("/auth/login", schema["paths"])

    def test_rag_store_cannot_use_the_billing_database_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "separate"):
            RAGStore(DATABASE_PATH)

    async def test_invalid_provider_configuration_is_reported_as_unavailable(self) -> None:
        fake_provider = main.app.dependency_overrides.pop(get_ai_provider)
        try:
            with patch.dict(os.environ, {"SMARTBILL_AI_TIMEOUT_SECONDS": "invalid"}):
                status_code, response = await self.client.request(
                    "GET", "/assistant/status"
                )
        finally:
            main.app.dependency_overrides[get_ai_provider] = fake_provider
        self.assertEqual(status_code, 503)
        self.assertIn("must be a number", str(response["detail"]))


class AISettingsTest(unittest.TestCase):
    def test_external_provider_is_optional_until_configured(self) -> None:
        settings = AISettings(
            base_url="",
            api_key="",
            chat_model="",
            embedding_model="",
            timeout_seconds=25,
        )
        self.assertFalse(settings.chat_configured)
        self.assertFalse(settings.embeddings_configured)

    def test_chat_and_embedding_models_are_reported_separately(self) -> None:
        settings = AISettings(
            base_url="https://provider.example/v1",
            api_key="secret",
            chat_model="chat-model",
            embedding_model="",
            timeout_seconds=25,
        )
        self.assertTrue(settings.chat_configured)
        self.assertFalse(settings.embeddings_configured)
