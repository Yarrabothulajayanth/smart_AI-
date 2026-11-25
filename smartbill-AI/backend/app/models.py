from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("purchase_price >= 0", name="ck_products_purchase_price"),
        CheckConstraint("selling_price >= 0", name="ck_products_selling_price"),
        CheckConstraint("stock_quantity >= 0", name="ck_products_stock_quantity"),
        CheckConstraint(
            "minimum_stock_threshold >= 0",
            name="ck_products_minimum_stock_threshold",
        ),
        CheckConstraint(
            "gst_rate >= 0 AND gst_rate <= 100", name="ck_products_gst_rate"
        ),
        CheckConstraint(
            "gst_applicable = 1 OR gst_rate = 0",
            name="ck_products_non_gst_rate",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    sku: Mapped[str | None] = mapped_column(String(64), unique=True)
    barcode: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    selling_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    gst_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )
    stock_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=Decimal("0.000")
    )
    minimum_stock_threshold: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, default=Decimal("0.000")
    )
    unit_of_measure: Mapped[str] = mapped_column(
        String(30), nullable=False, default="piece"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[Category | None] = relationship(back_populates="products")
    invoice_items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="product"
    )
    inventory_movements: Mapped[list["InventoryMovement"]] = relationship(
        back_populates="product"
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_invoices_subtotal"),
        CheckConstraint(
            "discount_amount >= 0 AND discount_amount <= subtotal",
            name="ck_invoices_discount_amount",
        ),
        CheckConstraint(
            "taxable_amount >= 0", name="ck_invoices_taxable_amount"
        ),
        CheckConstraint(
            "non_taxable_amount >= 0",
            name="ck_invoices_non_taxable_amount",
        ),
        CheckConstraint("tax_total >= 0", name="ck_invoices_tax_total"),
        CheckConstraint("total_amount >= 0", name="ck_invoices_total_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(36), unique=True, index=True
    )
    request_hash: Mapped[str | None] = mapped_column(String(64))
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    taxable_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    non_taxable_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    customer: Mapped[Customer | None] = relationship(back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )
    inventory_movements: Mapped[list["InventoryMovement"]] = relationship(
        back_populates="invoice"
    )

    @property
    def customer_name(self) -> str | None:
        return self.customer.name if self.customer is not None else None


class InvoiceItem(TimestampMixin, Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_invoice_items_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_items_unit_price"),
        CheckConstraint(
            "gst_rate >= 0 AND gst_rate <= 100",
            name="ck_invoice_items_gst_rate",
        ),
        CheckConstraint("line_subtotal >= 0", name="ck_invoice_items_subtotal"),
        CheckConstraint("tax_amount >= 0", name="ck_invoice_items_tax_amount"),
        CheckConstraint("line_total >= 0", name="ck_invoice_items_line_total"),
        CheckConstraint(
            "discount_amount >= 0 AND discount_amount <= line_subtotal",
            name="ck_invoice_items_discount_amount",
        ),
        CheckConstraint(
            "taxable_value >= 0", name="ck_invoice_items_taxable_value"
        ),
        CheckConstraint(
            "non_taxable_value >= 0",
            name="ck_invoice_items_non_taxable_value",
        ),
        CheckConstraint(
            "gst_applicable = 1 OR gst_rate = 0",
            name="ck_invoice_items_non_gst_rate",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gst_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gst_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )
    line_subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    taxable_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    non_taxable_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )

    invoice: Mapped[Invoice] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="invoice_items")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payments_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="paid"
    )
    reference: Mapped[str | None] = mapped_column(String(100))

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class InventoryMovement(TimestampMixin, Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_movements_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="inventory_movements")
    invoice: Mapped[Invoice | None] = relationship(
        back_populates="inventory_movements"
    )
