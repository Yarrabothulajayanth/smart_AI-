import unittest
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    Category,
    Customer,
    InventoryMovement,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
)


class ModelRelationshipsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_invoice_product_customer_and_payment_relationships(self) -> None:
        category = Category(name="Grocery")
        product = Product(
            name="Rice",
            sku="RICE-001",
            category=category,
            purchase_price=Decimal("12.50"),
            selling_price=Decimal("15.00"),
            gst_applicable=True,
            gst_rate=Decimal("5.00"),
            stock_quantity=Decimal("20.000"),
        )
        customer = Customer(name="Asha Patel")
        item = InvoiceItem(
            product=product,
            product_name="Rice",
            unit_of_measure="kg",
            quantity=Decimal("2.000"),
            unit_price=Decimal("15.00"),
            gst_applicable=True,
            gst_rate=Decimal("5.00"),
            line_subtotal=Decimal("30.00"),
            tax_amount=Decimal("1.50"),
            line_total=Decimal("31.50"),
        )
        payment = Payment(amount=Decimal("31.50"), payment_method="cash")
        movement = InventoryMovement(
            product=product,
            movement_type="sale",
            quantity=Decimal("2.000"),
        )
        invoice = Invoice(
            invoice_number="SB-0001",
            customer=customer,
            subtotal=Decimal("30.00"),
            tax_total=Decimal("1.50"),
            total_amount=Decimal("31.50"),
            items=[item],
            payments=[payment],
            inventory_movements=[movement],
        )

        self.session.add(invoice)
        self.session.commit()

        stored_invoice = self.session.scalar(
            select(Invoice).where(Invoice.invoice_number == "SB-0001")
        )
        self.assertIsNotNone(stored_invoice)
        assert stored_invoice is not None
        self.assertEqual(stored_invoice.customer.name, "Asha Patel")
        self.assertEqual(stored_invoice.items[0].product.name, "Rice")
        self.assertEqual(stored_invoice.payments[0].amount, Decimal("31.50"))
        self.assertEqual(stored_invoice.inventory_movements[0].product, product)
        self.assertEqual(product.category.name, "Grocery")
        self.assertEqual(stored_invoice.total_amount, Decimal("31.50"))
        self.assertIsInstance(stored_invoice.total_amount, Decimal)
        self.assertIsNotNone(stored_invoice.created_at)

    def test_invoice_numbers_are_unique(self) -> None:
        self.session.add_all(
            [
                Invoice(invoice_number="SB-0001"),
                Invoice(invoice_number="SB-0001"),
            ]
        )

        with self.assertRaises(IntegrityError):
            self.session.commit()


if __name__ == "__main__":
    unittest.main()
