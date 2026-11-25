import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Body,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models import Customer, Invoice
from app.schemas import (
    InvoiceCreate,
    InvoiceQuoteRead,
    InvoiceQuoteRequest,
    InvoiceRead,
)
from app.services.billing import (
    BillingError,
    CustomerNotFoundError,
    DiscountExceedsSubtotalError,
    IdempotencyConflictError,
    PaymentAmountMismatchError,
    ProductNotFoundError,
    QuantityOutOfRangeError,
    create_invoice,
    quote_invoice,
)
from app.services.invoice_pdf import generate_invoice_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/invoices", tags=["Billing"])


def _invoice_options():
    return (
        selectinload(Invoice.items),
        selectinload(Invoice.payments),
        joinedload(Invoice.customer),
    )


@router.post(
    "/quote",
    response_model=InvoiceQuoteRead,
    summary="Preview invoice totals",
    description=(
        "Calculate product-specific GST, proportional bill discount, and "
        "payable total without creating an invoice or changing product data."
    ),
    responses={
        404: {"description": "An active product was not found."},
        422: {"description": "The discount or quantities are invalid."},
    },
)
def post_invoice_quote(
    payload: InvoiceQuoteRequest,
    db: Session = Depends(get_db),
) -> InvoiceQuoteRead:
    try:
        return quote_invoice(db, payload)
    except ProductNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (DiscountExceedsSubtotalError, QuantityOutOfRangeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/",
    response_model=InvoiceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create and pay an invoice",
    description=(
        "Create a fully paid invoice atomically. Billing does not track, "
        "check, or deduct stock. Product prices are GST-exclusive. The required "
        "fixed bill discount is allocated proportionally across line "
        "subtotals before product-specific GST is calculated. Monetary "
        "amounts are rounded to two decimals using half-up rounding. The "
        "required Idempotency-Key header makes retries safe."
    ),
    responses={
        200: {"description": "A previously created invoice was returned for a retry."},
        404: {"description": "Customer or active product was not found."},
        409: {"description": "Idempotency conflict."},
        422: {"description": "Invalid discount, quantity, or payment amount."},
        500: {"description": "Invoice failed; the database transaction was rolled back."},
    },
)
def post_invoice(
    payload: InvoiceCreate,
    response: Response,
    idempotency_key: UUID = Header(
        description="Unique key to safely retry this checkout request."
    ),
    db: Session = Depends(get_db),
) -> Invoice:
    try:
        invoice, created = create_invoice(db, payload, str(idempotency_key))
    except ProductNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CustomerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except IdempotencyConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (
        DiscountExceedsSubtotalError,
        PaymentAmountMismatchError,
        QuantityOutOfRangeError,
    ) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BillingError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SQLAlchemyError as error:
        db.rollback()
        logger.error(
            "Invoice creation failed; the transaction was rolled back (%s).",
            type(error).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Invoice could not be completed; all changes were rolled back.",
        ) from error

    if not created:
        response.status_code = status.HTTP_200_OK
    return invoice


@router.get(
    "/",
    response_model=list[InvoiceRead],
    summary="List invoices",
    description=(
        "Return recent invoices, including line items and payments. "
        "Optionally search by invoice number or customer name."
    ),
)
def list_invoices(
    search: str | None = Query(default=None, max_length=150),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Invoice]:
    statement = select(Invoice).options(*_invoice_options())
    search_term = search.strip() if search else ""
    if search_term:
        pattern = f"%{search_term}%"
        statement = statement.outerjoin(Invoice.customer).where(
            Invoice.invoice_number.ilike(pattern)
            | Customer.name.ilike(pattern)
        )
    statement = statement.order_by(
        Invoice.created_at.desc(), Invoice.id.desc()
    ).limit(limit).offset(offset)
    return list(db.scalars(statement).all())


@router.get(
    "/number/{invoice_number}",
    response_model=InvoiceRead,
    summary="Get invoice by number",
    description="Retrieve an invoice using its unique invoice number.",
    responses={404: {"description": "Invoice not found."}},
)
def get_invoice_by_number(
    invoice_number: str = Path(min_length=1, max_length=50),
    db: Session = Depends(get_db),
) -> Invoice:
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.invoice_number == invoice_number)
        .options(*_invoice_options())
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice


@router.get(
    "/{invoice_id}/pdf",
    summary="Download invoice PDF",
    description="Generate a printer-friendly A4 PDF for the selected invoice.",
    responses={
        404: {"description": "Invoice not found."},
        200: {"content": {"application/pdf": {}}},
    },
)
def download_invoice_pdf(
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> Response:
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(*_invoice_options())
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")

    pdf_content = generate_invoice_pdf(invoice)
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="invoice-{invoice.invoice_number}.pdf"'
            )
        },
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceRead,
    summary="Get invoice by ID",
    description="Retrieve an invoice by its database ID.",
    responses={404: {"description": "Invoice not found."}},
)
def get_invoice(
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> Invoice:
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(*_invoice_options())
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice
