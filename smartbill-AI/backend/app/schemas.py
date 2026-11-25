from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CategoryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CategoryCreate(CategoryFields):
    pass


class CategoryUpdate(CategoryFields):
    pass


class CategoryRead(CategoryFields):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    created_at: datetime
    updated_at: datetime


class CustomerFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=2_000)

    @field_validator("name", mode="before")
    @classmethod
    def strip_customer_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", "phone", "address", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class CustomerCreate(CustomerFields):
    pass


class CustomerUpdate(CustomerFields):
    pass


class CustomerRead(CustomerFields):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    created_at: datetime
    updated_at: datetime


class CustomerInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    subtotal: Decimal
    discount_amount: Decimal
    tax_total: Decimal
    total_amount: Decimal
    created_at: datetime


class ProductFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    barcode: str | None = Field(default=None, max_length=128)
    category_id: int = Field(gt=0)
    description: str | None = Field(default=None, max_length=2_000)
    purchase_price: Decimal = Field(
        ge=0, max_digits=12, decimal_places=2
    )
    selling_price: Decimal = Field(
        ge=0, max_digits=12, decimal_places=2
    )
    gst_applicable: bool = False
    gst_rate: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )
    unit_of_measure: str = Field(default="piece", min_length=1, max_length=30)
    is_active: bool = True

    @field_validator("name", "unit_of_measure", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("barcode", mode="before")
    @classmethod
    def normalize_barcode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_non_gst_rate(self) -> "ProductFields":
        if not self.gst_applicable and self.gst_rate != Decimal("0.00"):
            raise ValueError("GST rate must be zero when GST is not applicable.")
        return self


class ProductCreate(ProductFields):
    pass


class ProductUpdate(ProductFields):
    pass


class ProductRead(ProductFields):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    category_id: int | None
    created_at: datetime
    updated_at: datetime


class InvoiceItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)


class InvoiceQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InvoiceItemCreate] = Field(min_length=1, max_length=100)
    discount_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "Fixed currency amount allocated proportionally across item "
            "subtotals before GST is calculated."
        ),
    )


class InvoiceCreate(InvoiceQuoteRequest):
    customer_id: int | None = Field(default=None, gt=0)
    payment_method: Literal["cash", "upi"] = Field(
        description="Full-payment method accepted at checkout."
    )
    payment_amount: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="Must exactly equal the calculated invoice total.",
    )

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_payment_method(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class InvoiceQuoteLineRead(BaseModel):
    product_id: int
    product_name: str
    unit_of_measure: str
    quantity: Decimal
    unit_price: Decimal
    gst_applicable: bool
    gst_rate: Decimal
    line_subtotal: Decimal
    discount_amount: Decimal
    taxable_value: Decimal
    non_taxable_value: Decimal
    tax_amount: Decimal
    line_total: Decimal


class InvoiceQuoteRead(BaseModel):
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    non_taxable_amount: Decimal
    tax_total: Decimal
    total_amount: Decimal
    items: list[InvoiceQuoteLineRead]


class InvoiceItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    unit_of_measure: str
    quantity: Decimal
    unit_price: Decimal
    gst_applicable: bool
    gst_rate: Decimal
    line_subtotal: Decimal
    discount_amount: Decimal
    taxable_value: Decimal
    non_taxable_value: Decimal
    tax_amount: Decimal
    line_total: Decimal


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    payment_method: str
    payment_status: str
    created_at: datetime


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    customer_id: int | None
    customer_name: str | None
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    non_taxable_amount: Decimal
    tax_total: Decimal
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[InvoiceItemRead]
    payments: list[PaymentRead]


class SalesOverviewPoint(BaseModel):
    date: date
    revenue: Decimal
    invoice_count: int


class DashboardRead(BaseModel):
    today_revenue: Decimal
    today_invoice_count: int
    monthly_revenue: Decimal
    total_invoices: int
    total_customers: int
    recent_invoices: list[InvoiceRead]
    sales_overview: list[SalesOverviewPoint]
    profit: Decimal | None
    profit_note: str


class BestSellingProductRead(BaseModel):
    product_id: int
    product_name: str
    quantity_sold: Decimal
    revenue: Decimal


class SalesReportRead(BaseModel):
    period: str
    start_date: date
    end_date: date
    revenue: Decimal
    gross_collected: Decimal
    gst_collected: Decimal
    invoice_count: int
    average_invoice_value: Decimal
    best_selling_products: list[BestSellingProductRead]
    profit: Decimal | None
    profit_note: str


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AssistantSource(BaseModel):
    label: str
    detail: str | None = None


class AssistantChatResponse(BaseModel):
    answer: str
    language: Literal["en", "te"]
    intent: str
    sources: list[AssistantSource]


class AssistantDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=1_000_000)


class AssistantDocumentRead(BaseModel):
    id: int
    filename: str
    created_at: str
    chunk_count: int


class AssistantStatusRead(BaseModel):
    chat_configured: bool
    embeddings_configured: bool
