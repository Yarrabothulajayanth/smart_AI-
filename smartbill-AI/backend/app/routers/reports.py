from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models import Customer, Invoice, InvoiceItem
from app.schemas import (
    BestSellingProductRead,
    DashboardRead,
    InvoiceRead,
    SalesOverviewPoint,
    SalesReportRead,
)

router = APIRouter(prefix="/reports", tags=["Sales reports"])
BUSINESS_TIMEZONE_NAME = os.environ.get(
    "SMARTBILL_TIMEZONE", "Asia/Kolkata"
).strip()
try:
    BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)
except ZoneInfoNotFoundError as error:
    if BUSINESS_TIMEZONE_NAME == "Asia/Kolkata":
        BUSINESS_TIMEZONE = timezone(
            timedelta(hours=5, minutes=30), name="Asia/Kolkata"
        )
    else:
        raise RuntimeError(
            "SMARTBILL_TIMEZONE must be a valid IANA timezone name available "
            "to the operating system."
        ) from error
PROFIT_NOTE = (
    "Profit is not available because historical invoice items do not store "
    "purchase-price snapshots. Revenue is shown separately and excludes GST."
)
ZERO = Decimal("0.00")


def _utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(start, time.min, tzinfo=BUSINESS_TIMEZONE)
    end_local = datetime.combine(
        end + timedelta(days=1), time.min, tzinfo=BUSINESS_TIMEZONE
    )
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def _sales_totals(
    db: Session, start: datetime, end: datetime
) -> tuple[Decimal, Decimal, Decimal, int]:
    result = db.execute(
        select(
            func.coalesce(
                func.sum(Invoice.subtotal - Invoice.discount_amount), 0
            ),
            func.coalesce(func.sum(Invoice.total_amount), 0),
            func.coalesce(func.sum(Invoice.tax_total), 0),
            func.count(Invoice.id),
        ).where(Invoice.created_at >= start, Invoice.created_at < end)
    ).one()
    return (
        Decimal(result[0] or 0),
        Decimal(result[1] or 0),
        Decimal(result[2] or 0),
        int(result[3]),
    )


def _report_period(
    period: str,
    requested_start: date | None,
    requested_end: date | None,
    today: date,
) -> tuple[date, date]:
    if period == "custom":
        if requested_start is None or requested_end is None:
            raise HTTPException(
                status_code=422,
                detail="Both start_date and end_date are required for a custom report.",
            )
        if requested_start > requested_end:
            raise HTTPException(
                status_code=422,
                detail="start_date must be on or before end_date.",
            )
        return requested_start, requested_end

    if requested_start is not None or requested_end is not None:
        raise HTTPException(
            status_code=422,
            detail="Use period=custom when providing date boundaries.",
        )
    if period == "daily":
        return today, today
    if period == "weekly":
        return today - timedelta(days=today.weekday()), today
    month_start = today.replace(day=1)
    return month_start, today


def _profit_fields() -> dict[str, Decimal | None | str]:
    return {"profit": None, "profit_note": PROFIT_NOTE}


@router.get(
    "/dashboard",
    response_model=DashboardRead,
    summary="Get dashboard metrics",
    description=(
        "Return actual sales, invoice, customer, recent transaction, and "
        "seven-day revenue data. Revenue excludes GST; profit is unavailable "
        "without historical cost snapshots."
    ),
)
def dashboard(db: Session = Depends(get_db)) -> DashboardRead:
    now = datetime.now(BUSINESS_TIMEZONE)
    today = now.date()
    today_start, tomorrow_start = _utc_bounds(today, today)
    month_start = today.replace(day=1)
    month_start_utc, _ = _utc_bounds(month_start, today)
    today_revenue, _, _, today_count = _sales_totals(
        db, today_start, tomorrow_start
    )
    monthly_revenue, _, _, _ = _sales_totals(
        db, month_start_utc, tomorrow_start
    )
    total_invoices = int(db.scalar(select(func.count(Invoice.id))) or 0)
    total_customers = int(db.scalar(select(func.count(Customer.id))) or 0)

    recent_statement = (
        select(Invoice)
        .options(
            joinedload(Invoice.customer),
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
        )
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .limit(8)
    )
    recent_invoices = list(db.scalars(recent_statement).all())

    chart_start = today - timedelta(days=6)
    chart_start_utc, _ = _utc_bounds(chart_start, today)
    chart_rows = db.execute(
        select(
            Invoice.created_at,
            Invoice.subtotal - Invoice.discount_amount,
        ).where(Invoice.created_at >= chart_start_utc, Invoice.created_at < tomorrow_start)
    ).all()
    chart_values: dict[date, Decimal] = {}
    chart_counts: dict[date, int] = {}
    for created_at, revenue in chart_rows:
        timestamp = created_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        day = timestamp.astimezone(BUSINESS_TIMEZONE).date()
        chart_values[day] = chart_values.get(day, ZERO) + Decimal(revenue or 0)
        chart_counts[day] = chart_counts.get(day, 0) + 1

    overview = [
        SalesOverviewPoint(
            date=chart_start + timedelta(days=offset),
            revenue=chart_values.get(chart_start + timedelta(days=offset), ZERO),
            invoice_count=chart_counts.get(chart_start + timedelta(days=offset), 0),
        )
        for offset in range(7)
    ]
    return DashboardRead(
        today_revenue=today_revenue,
        today_invoice_count=today_count,
        monthly_revenue=monthly_revenue,
        total_invoices=total_invoices,
        total_customers=total_customers,
        recent_invoices=recent_invoices,
        sales_overview=overview,
        **_profit_fields(),
    )


@router.get(
    "/sales",
    response_model=SalesReportRead,
    summary="Get a sales report",
    description=(
        "Report daily, week-to-date, month-to-date, or custom-range revenue, "
        "collections, GST, invoices, and best-selling products."
    ),
)
def sales_report(
    period: Literal["daily", "weekly", "monthly", "custom"] = Query(
        default="monthly"
    ),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SalesReportRead:
    today = datetime.now(BUSINESS_TIMEZONE).date()
    start_day, end_day = _report_period(
        period, start_date, end_date, today
    )
    start_utc, end_utc = _utc_bounds(start_day, end_day)
    revenue, gross_collected, gst_collected, invoice_count = _sales_totals(
        db, start_utc, end_utc
    )
    average_invoice_value = (
        (gross_collected / invoice_count).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if invoice_count
        else ZERO
    )
    product_rows = db.execute(
        select(
            InvoiceItem.product_id,
            InvoiceItem.product_name,
            func.sum(InvoiceItem.quantity),
            func.sum(InvoiceItem.taxable_value + InvoiceItem.non_taxable_value),
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.created_at >= start_utc, Invoice.created_at < end_utc)
        .group_by(InvoiceItem.product_id, InvoiceItem.product_name)
        .order_by(func.sum(InvoiceItem.quantity).desc(), InvoiceItem.product_name)
        .limit(5)
    ).all()
    best_selling_products = [
        BestSellingProductRead(
            product_id=row[0],
            product_name=row[1],
            quantity_sold=Decimal(row[2] or 0),
            revenue=Decimal(row[3] or 0),
        )
        for row in product_rows
    ]
    return SalesReportRead(
        period=period,
        start_date=start_day,
        end_date=end_day,
        revenue=revenue,
        gross_collected=gross_collected,
        gst_collected=gst_collected,
        invoice_count=invoice_count,
        average_invoice_value=average_invoice_value,
        best_selling_products=best_selling_products,
        **_profit_fields(),
    )
