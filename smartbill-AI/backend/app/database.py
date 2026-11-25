from collections.abc import Generator
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "smartbill.db"
configured_database_path = os.environ.get("SMARTBILL_DATABASE_PATH", "").strip()
DATABASE_PATH = (
    Path(configured_database_path).expanduser().resolve()
    if configured_database_path
    else DEFAULT_DATABASE_PATH
)
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)
DEFAULT_ENGINE = engine


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(
    dbapi_connection: Any, _connection_record: Any
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def verify_database_schema(target_engine: Engine = engine) -> None:
    from app import models

    if target_engine is engine and not DATABASE_PATH.is_file():
        raise RuntimeError(
            "The configured production database file does not exist. "
            "Provision or restore the persistent database before starting SmartBill."
        )

    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = set(models.Base.metadata.tables) - existing_tables
    missing_columns: dict[str, set[str]] = {}
    for table_name, table in models.Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing = {column.name for column in table.columns} - existing_columns
        if missing:
            missing_columns[table_name] = missing

    if missing_tables or missing_columns:
        raise RuntimeError(
            "The production database schema is incomplete. Back up the database "
            "and apply a reviewed migration before starting SmartBill."
        )


def initialize_database(target_engine: Engine = engine) -> None:
    from app import models

    models.Base.metadata.create_all(bind=target_engine)

    column_additions = {
        "products": {
            "barcode": "VARCHAR(128)",
            "minimum_stock_threshold": "NUMERIC(12, 3) NOT NULL DEFAULT 0",
            "unit_of_measure": "VARCHAR(30) NOT NULL DEFAULT 'piece'",
            "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        },
        "invoices": {
            "idempotency_key": "VARCHAR(36)",
            "request_hash": "VARCHAR(64)",
            "discount_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "taxable_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "non_taxable_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
        },
        "invoice_items": {
            "product_name": "VARCHAR(150) NOT NULL DEFAULT ''",
            "unit_of_measure": "VARCHAR(30) NOT NULL DEFAULT 'piece'",
            "discount_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "taxable_value": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "non_taxable_value": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
        },
        "payments": {
            "payment_status": "VARCHAR(20) NOT NULL DEFAULT 'recorded'",
        },
    }

    newly_added_columns: dict[str, set[str]] = {}
    with target_engine.begin() as connection:
        inspector = inspect(connection)
        for table_name, additions in column_additions.items():
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            for name, definition in additions.items():
                if name not in existing_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"
                    )
                    newly_added_columns.setdefault(table_name, set()).add(name)

        item_additions = newly_added_columns.get("invoice_items", set())
        if item_additions:
            updates: list[str] = []
            if "product_name" in item_additions:
                updates.append(
                    "product_name = COALESCE("
                    "(SELECT name FROM products "
                    "WHERE products.id = invoice_items.product_id), product_name)"
                )
            if "unit_of_measure" in item_additions:
                updates.append(
                    "unit_of_measure = COALESCE("
                    "(SELECT unit_of_measure FROM products "
                    "WHERE products.id = invoice_items.product_id), unit_of_measure)"
                )
            if "taxable_value" in item_additions:
                updates.append(
                    "taxable_value = CASE WHEN gst_applicable "
                    "THEN line_subtotal - discount_amount ELSE 0 END"
                )
            if "non_taxable_value" in item_additions:
                updates.append(
                    "non_taxable_value = CASE WHEN gst_applicable "
                    "THEN 0 ELSE line_subtotal - discount_amount END"
                )
            connection.exec_driver_sql(
                f"UPDATE invoice_items SET {', '.join(updates)}"
            )

        invoice_additions = newly_added_columns.get("invoices", set())
        invoice_updates: list[str] = []
        if "taxable_amount" in invoice_additions:
            invoice_updates.append(
                "taxable_amount = COALESCE("
                "(SELECT SUM(taxable_value) FROM invoice_items "
                "WHERE invoice_items.invoice_id = invoices.id), 0)"
            )
        if "non_taxable_amount" in invoice_additions:
            invoice_updates.append(
                "non_taxable_amount = COALESCE("
                "(SELECT SUM(non_taxable_value) FROM invoice_items "
                "WHERE invoice_items.invoice_id = invoices.id), 0)"
            )
        if invoice_updates:
            connection.exec_driver_sql(
                f"UPDATE invoices SET {', '.join(invoice_updates)}"
            )

        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_barcode "
            "ON products (barcode)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_invoices_idempotency_key "
            "ON invoices (idempotency_key)"
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
