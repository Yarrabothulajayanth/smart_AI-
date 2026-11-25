import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.database import initialize_database
from app.models import Invoice, InvoiceItem, Payment, Product


class ProductDatabaseMigrationTest(unittest.TestCase):
    def test_adds_product_fields_without_losing_existing_rows(self) -> None:
        with TemporaryDirectory(prefix="smartbill-migration-test-") as temp_dir:
            database_path = Path(temp_dir) / "legacy.sqlite"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE categories (
                            id INTEGER PRIMARY KEY,
                            name VARCHAR(100) NOT NULL UNIQUE,
                            description TEXT,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE products (
                            id INTEGER PRIMARY KEY,
                            name VARCHAR(150) NOT NULL,
                            sku VARCHAR(64) UNIQUE,
                            description TEXT,
                            category_id INTEGER,
                            purchase_price NUMERIC(12, 2) NOT NULL,
                            selling_price NUMERIC(12, 2) NOT NULL,
                            gst_applicable BOOLEAN NOT NULL,
                            gst_rate NUMERIC(5, 2) NOT NULL,
                            stock_quantity NUMERIC(12, 3) NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            FOREIGN KEY(category_id) REFERENCES categories(id)
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO categories
                            (id, name, created_at, updated_at)
                        VALUES (1, 'Grocery', '2025-01-01', '2025-01-01')
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO products (
                            id, name, sku, category_id, purchase_price,
                            selling_price, gst_applicable, gst_rate,
                            stock_quantity, created_at, updated_at
                        ) VALUES (
                            1, 'Rice', 'RICE-1', 1, 10.00, 15.00, 0, 0,
                            3.000, '2025-01-01', '2025-01-01'
                        )
                        """
                    )

                initialize_database(engine)

                columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("products")
                }
                self.assertTrue(
                    {
                        "barcode",
                        "minimum_stock_threshold",
                        "unit_of_measure",
                        "is_active",
                    }.issubset(columns)
                )
                barcode_index = next(
                    index
                    for index in inspect(engine).get_indexes("products")
                    if index["name"] == "ix_products_barcode"
                )
                self.assertTrue(barcode_index["unique"])

                with Session(engine) as session:
                    product = session.get(Product, 1)
                    self.assertIsNotNone(product)
                    assert product is not None
                    self.assertEqual(product.name, "Rice")
                    self.assertEqual(product.purchase_price, Decimal("10.00"))
                    self.assertEqual(product.stock_quantity, Decimal("3.000"))
                    self.assertIsNone(product.barcode)
                    self.assertEqual(
                        product.minimum_stock_threshold, Decimal("0.000")
                    )
                    self.assertEqual(product.unit_of_measure, "piece")
                    self.assertTrue(product.is_active)
            finally:
                engine.dispose()

    def test_adds_billing_fields_and_preserves_legacy_invoice_data(self) -> None:
        with TemporaryDirectory(prefix="smartbill-billing-migration-test-") as temp_dir:
            database_path = Path(temp_dir) / "legacy.sqlite"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE categories (
                            id INTEGER PRIMARY KEY,
                            name VARCHAR(100) NOT NULL UNIQUE,
                            description TEXT,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE products (
                            id INTEGER PRIMARY KEY,
                            name VARCHAR(150) NOT NULL,
                            sku VARCHAR(64) UNIQUE,
                            description TEXT,
                            category_id INTEGER,
                            purchase_price NUMERIC(12, 2) NOT NULL,
                            selling_price NUMERIC(12, 2) NOT NULL,
                            gst_applicable BOOLEAN NOT NULL,
                            gst_rate NUMERIC(5, 2) NOT NULL,
                            stock_quantity NUMERIC(12, 3) NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            FOREIGN KEY(category_id) REFERENCES categories(id)
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE customers (
                            id INTEGER PRIMARY KEY,
                            name VARCHAR(150) NOT NULL,
                            email VARCHAR(254),
                            phone VARCHAR(32),
                            address TEXT,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE invoices (
                            id INTEGER PRIMARY KEY,
                            invoice_number VARCHAR(50) NOT NULL UNIQUE,
                            customer_id INTEGER,
                            subtotal NUMERIC(12, 2) NOT NULL,
                            tax_total NUMERIC(12, 2) NOT NULL,
                            total_amount NUMERIC(12, 2) NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            FOREIGN KEY(customer_id) REFERENCES customers(id)
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE invoice_items (
                            id INTEGER PRIMARY KEY,
                            invoice_id INTEGER NOT NULL,
                            product_id INTEGER NOT NULL,
                            quantity NUMERIC(12, 3) NOT NULL,
                            unit_price NUMERIC(12, 2) NOT NULL,
                            gst_applicable BOOLEAN NOT NULL,
                            gst_rate NUMERIC(5, 2) NOT NULL,
                            line_subtotal NUMERIC(12, 2) NOT NULL,
                            tax_amount NUMERIC(12, 2) NOT NULL,
                            line_total NUMERIC(12, 2) NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            FOREIGN KEY(invoice_id) REFERENCES invoices(id),
                            FOREIGN KEY(product_id) REFERENCES products(id)
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE payments (
                            id INTEGER PRIMARY KEY,
                            invoice_id INTEGER NOT NULL,
                            amount NUMERIC(12, 2) NOT NULL,
                            payment_method VARCHAR(30) NOT NULL,
                            reference VARCHAR(100),
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            FOREIGN KEY(invoice_id) REFERENCES invoices(id)
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO categories
                            (id, name, created_at, updated_at)
                        VALUES (1, 'Grocery', '2025-01-01', '2025-01-01')
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO products (
                            id, name, sku, category_id, purchase_price,
                            selling_price, gst_applicable, gst_rate,
                            stock_quantity, created_at, updated_at
                        ) VALUES (
                            1, 'Rice', 'RICE-1', 1, 10.00, 15.00, 1, 5.00,
                            3.000, '2025-01-01', '2025-01-01'
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO invoices (
                            id, invoice_number, customer_id, subtotal,
                            tax_total, total_amount, created_at, updated_at
                        ) VALUES (
                            1, 'SB-LEGACY-1', NULL, 30.00, 1.50, 31.50,
                            '2025-01-01', '2025-01-01'
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO invoice_items (
                            id, invoice_id, product_id, quantity, unit_price,
                            gst_applicable, gst_rate, line_subtotal, tax_amount,
                            line_total, created_at, updated_at
                        ) VALUES (
                            1, 1, 1, 2.000, 15.00, 1, 5.00, 30.00, 1.50,
                            31.50, '2025-01-01', '2025-01-01'
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO payments (
                            id, invoice_id, amount, payment_method, reference,
                            created_at, updated_at
                        ) VALUES (
                            1, 1, 31.50, 'cash', NULL,
                            '2025-01-01', '2025-01-01'
                        )
                        """
                    )

                initialize_database(engine)

                invoice_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("invoices")
                }
                item_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("invoice_items")
                }
                payment_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("payments")
                }
                self.assertTrue(
                    {
                        "idempotency_key",
                        "request_hash",
                        "discount_amount",
                        "taxable_amount",
                        "non_taxable_amount",
                    }.issubset(invoice_columns)
                )
                self.assertTrue(
                    {
                        "product_name",
                        "unit_of_measure",
                        "discount_amount",
                        "taxable_value",
                        "non_taxable_value",
                    }.issubset(item_columns)
                )
                self.assertIn("payment_status", payment_columns)

                with Session(engine) as session:
                    invoice = session.get(Invoice, 1)
                    item = session.get(InvoiceItem, 1)
                    payment = session.get(Payment, 1)
                    product = session.get(Product, 1)
                    assert invoice is not None
                    assert item is not None
                    assert payment is not None
                    assert product is not None
                    self.assertEqual(invoice.invoice_number, "SB-LEGACY-1")
                    self.assertEqual(invoice.total_amount, Decimal("31.50"))
                    self.assertEqual(invoice.taxable_amount, Decimal("30.00"))
                    self.assertEqual(invoice.non_taxable_amount, Decimal("0.00"))
                    self.assertEqual(item.product_name, "Rice")
                    self.assertEqual(item.unit_of_measure, "piece")
                    self.assertEqual(item.taxable_value, Decimal("30.00"))
                    self.assertEqual(payment.amount, Decimal("31.50"))
                    self.assertEqual(payment.payment_status, "recorded")
                    self.assertEqual(product.stock_quantity, Decimal("3.000"))

                    product.name = "Renamed Rice"
                    session.commit()

                initialize_database(engine)

                with Session(engine) as session:
                    item = session.get(InvoiceItem, 1)
                    self.assertIsNotNone(item)
                    assert item is not None
                    self.assertEqual(item.product_name, "Rice")
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
