import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Customer,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
)
from app.schemas import (
    InvoiceCreate,
    InvoiceItemCreate,
    InvoiceQuoteLineRead,
    InvoiceQuoteRead,
    InvoiceQuoteRequest,
)

CENT = Decimal("0.01")
MAX_INVOICE_QUANTITY = Decimal("999999999.999")


class BillingError(Exception):
    pass


class ProductNotFoundError(BillingError):
    def __init__(self, product_id: int) -> None:
        super().__init__(f"Active product {product_id} was not found.")


class CustomerNotFoundError(BillingError):
    def __init__(self) -> None:
        super().__init__("Customer was not found.")


class DiscountExceedsSubtotalError(BillingError):
    def __init__(self) -> None:
        super().__init__("Bill discount cannot exceed the item subtotal.")


class PaymentAmountMismatchError(BillingError):
    def __init__(self, expected: Decimal) -> None:
        super().__init__(
            f"Payment amount must exactly match the invoice total of {expected:.2f}."
        )


class IdempotencyConflictError(BillingError):
    def __init__(self) -> None:
        super().__init__(
            "This Idempotency-Key was already used for a different request."
        )


class QuantityOutOfRangeError(BillingError):
    def __init__(self) -> None:
        super().__init__("Combined product quantity exceeds the supported limit.")


@dataclass(frozen=True)
class CalculatedLine:
    product: Product
    quantity: Decimal
    subtotal: Decimal
    discount: Decimal
    taxable_value: Decimal
    non_taxable_value: Decimal
    tax_amount: Decimal
    line_total: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _combined_quantities(
    items: Sequence[InvoiceItemCreate],
) -> dict[int, Decimal]:
    quantities: dict[int, Decimal] = {}
    for item in items:
        combined = quantities.get(item.product_id, Decimal("0")) + item.quantity
        if combined > MAX_INVOICE_QUANTITY:
            raise QuantityOutOfRangeError()
        quantities[item.product_id] = combined
    return quantities


def _load_active_products(
    db: Session, product_ids: Sequence[int]
) -> list[Product]:
    products = list(
        db.scalars(
            select(Product)
            .where(
                Product.id.in_(product_ids),
                Product.is_active.is_(True),
            )
            .order_by(Product.id)
        ).all()
    )
    product_ids_found = {product.id for product in products}
    missing_product_id = next(
        (product_id for product_id in product_ids if product_id not in product_ids_found),
        None,
    )
    if missing_product_id is not None:
        raise ProductNotFoundError(missing_product_id)
    return products


def _request_hash(
    payload: InvoiceCreate, quantities: dict[int, Decimal]
) -> str:
    canonical_request = {
        "customer_id": payload.customer_id,
        "discount_amount": _decimal_text(payload.discount_amount),
        "items": [
            {
                "product_id": product_id,
                "quantity": _decimal_text(quantity),
            }
            for product_id, quantity in sorted(quantities.items())
        ],
        "payment_amount": _decimal_text(payload.payment_amount),
        "payment_method": payload.payment_method,
    }
    encoded = json.dumps(
        canonical_request, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _allocate_discount(
    discount: Decimal, subtotals: Sequence[Decimal]
) -> list[Decimal]:
    if not subtotals or discount == 0:
        return [Decimal("0.00") for _ in subtotals]

    total_cents = sum(int(subtotal * 100) for subtotal in subtotals)
    if total_cents == 0:
        return [Decimal("0.00") for _ in subtotals]

    discount_cents = int(discount * 100)
    raw_shares = [
        Decimal(discount_cents * int(subtotal * 100)) / Decimal(total_cents)
        for subtotal in subtotals
    ]
    allocated_cents = [
        int(share.to_integral_value(rounding=ROUND_DOWN))
        for share in raw_shares
    ]
    cents_left = discount_cents - sum(allocated_cents)
    remainder_order = sorted(
        range(len(subtotals)),
        key=lambda index: (
            raw_shares[index] - allocated_cents[index],
            -index,
        ),
        reverse=True,
    )
    for index in remainder_order[:cents_left]:
        allocated_cents[index] += 1
    return [
        (Decimal(cents) / 100).quantize(CENT) for cents in allocated_cents
    ]


def _calculate_lines(
    products: Sequence[Product],
    quantities: dict[int, Decimal],
    discount_amount: Decimal,
) -> tuple[list[CalculatedLine], Decimal, Decimal, Decimal, Decimal]:
    product_by_id = {product.id: product for product in products}
    ordered_product_ids = list(quantities)
    subtotals = [
        _money(quantities[product_id] * product_by_id[product_id].selling_price)
        for product_id in ordered_product_ids
    ]
    subtotal = _money(sum(subtotals, Decimal("0.00")))
    if discount_amount > subtotal:
        raise DiscountExceedsSubtotalError()

    discounts = _allocate_discount(discount_amount, subtotals)
    lines: list[CalculatedLine] = []
    taxable_total = Decimal("0.00")
    non_taxable_total = Decimal("0.00")
    tax_total = Decimal("0.00")

    for product_id, line_subtotal, line_discount in zip(
        ordered_product_ids, subtotals, discounts, strict=True
    ):
        product = product_by_id[product_id]
        net_value = line_subtotal - line_discount
        if product.gst_applicable:
            taxable_value = net_value
            non_taxable_value = Decimal("0.00")
            tax_amount = _money(
                taxable_value * product.gst_rate / Decimal("100")
            )
        else:
            taxable_value = Decimal("0.00")
            non_taxable_value = net_value
            tax_amount = Decimal("0.00")
        line_total = net_value + tax_amount
        lines.append(
            CalculatedLine(
                product=product,
                quantity=quantities[product_id],
                subtotal=line_subtotal,
                discount=line_discount,
                taxable_value=taxable_value,
                non_taxable_value=non_taxable_value,
                tax_amount=tax_amount,
                line_total=line_total,
            )
        )
        taxable_total += taxable_value
        non_taxable_total += non_taxable_value
        tax_total += tax_amount

    return (
        lines,
        subtotal,
        taxable_total,
        non_taxable_total,
        _money(tax_total),
    )


def quote_invoice(
    db: Session, payload: InvoiceQuoteRequest
) -> InvoiceQuoteRead:
    quantities = _combined_quantities(payload.items)
    products = _load_active_products(db, list(quantities))
    (
        calculated_lines,
        subtotal,
        taxable_total,
        non_taxable_total,
        tax_total,
    ) = _calculate_lines(products, quantities, payload.discount_amount)
    total_amount = _money(taxable_total + non_taxable_total + tax_total)
    return InvoiceQuoteRead(
        subtotal=subtotal,
        discount_amount=payload.discount_amount,
        taxable_amount=taxable_total,
        non_taxable_amount=non_taxable_total,
        tax_total=tax_total,
        total_amount=total_amount,
        items=[
            InvoiceQuoteLineRead(
                product_id=line.product.id,
                product_name=line.product.name,
                unit_of_measure=line.product.unit_of_measure,
                quantity=line.quantity,
                unit_price=line.product.selling_price,
                gst_applicable=line.product.gst_applicable,
                gst_rate=line.product.gst_rate,
                line_subtotal=line.subtotal,
                discount_amount=line.discount,
                taxable_value=line.taxable_value,
                non_taxable_value=line.non_taxable_value,
                tax_amount=line.tax_amount,
                line_total=line.line_total,
            )
            for line in calculated_lines
        ],
    )


def create_invoice(
    db: Session, payload: InvoiceCreate, idempotency_key: str
) -> tuple[Invoice, bool]:
    quantities = _combined_quantities(payload.items)
    request_hash = _request_hash(payload, quantities)

    with db.begin():
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        existing_invoice = db.scalar(
            select(Invoice)
            .where(Invoice.idempotency_key == idempotency_key)
            .options(
                selectinload(Invoice.items),
                selectinload(Invoice.payments),
            )
        )
        if existing_invoice is not None:
            if existing_invoice.request_hash != request_hash:
                raise IdempotencyConflictError()
            return existing_invoice, False

        if payload.customer_id is not None:
            customer = db.get(Customer, payload.customer_id)
            if customer is None:
                raise CustomerNotFoundError()

        products = _load_active_products(db, list(quantities))

        (
            calculated_lines,
            subtotal,
            taxable_total,
            non_taxable_total,
            tax_total,
        ) = _calculate_lines(products, quantities, payload.discount_amount)
        total_amount = _money(
            taxable_total + non_taxable_total + tax_total
        )
        if payload.payment_amount != total_amount:
            raise PaymentAmountMismatchError(total_amount)

        invoice = Invoice(
            invoice_number=f"SB-{uuid4().hex[:16].upper()}",
            customer_id=payload.customer_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            subtotal=subtotal,
            discount_amount=payload.discount_amount,
            taxable_amount=taxable_total,
            non_taxable_amount=non_taxable_total,
            tax_total=tax_total,
            total_amount=total_amount,
        )
        db.add(invoice)
        db.flush()

        for line in calculated_lines:
            invoice.items.append(
                InvoiceItem(
                    product_id=line.product.id,
                    product_name=line.product.name,
                    unit_of_measure=line.product.unit_of_measure,
                    quantity=line.quantity,
                    unit_price=line.product.selling_price,
                    gst_applicable=line.product.gst_applicable,
                    gst_rate=line.product.gst_rate,
                    line_subtotal=line.subtotal,
                    discount_amount=line.discount,
                    taxable_value=line.taxable_value,
                    non_taxable_value=line.non_taxable_value,
                    tax_amount=line.tax_amount,
                    line_total=line.line_total,
                )
            )
        invoice.payments.append(
            Payment(
                amount=total_amount,
                payment_method=payload.payment_method,
                payment_status="paid",
            )
        )
        db.flush()
        return invoice, True
