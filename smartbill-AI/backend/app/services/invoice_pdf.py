from decimal import Decimal
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Invoice


def _currency(value: Decimal) -> str:
    return f"INR {value:,.2f}"


def generate_invoice_pdf(invoice: Invoice) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Invoice {invoice.invoice_number}",
    )
    styles = getSampleStyleSheet()
    right_style = styles["Normal"]
    right_style.alignment = TA_RIGHT
    story: list[Any] = [
        Paragraph("SmartBill AI", styles["Title"]),
        Paragraph(f"Invoice {escape(invoice.invoice_number)}", styles["Heading2"]),
        Paragraph(
            f"Date: {invoice.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"],
        ),
        Paragraph(
            "Customer: "
            + escape(invoice.customer.name if invoice.customer else "Walk-in customer"),
            styles["Normal"],
        ),
        Spacer(1, 8 * mm),
    ]

    item_rows: list[list[Any]] = [
        [
            "Product",
            "Quantity / unit",
            "Unit price",
            "Discount",
            "Taxable value",
            "GST",
            "Line total",
        ]
    ]
    for item in invoice.items:
        quantity = f"{item.quantity.normalize():f} {escape(item.unit_of_measure)}"
        gst_text = (
            f"{item.gst_rate:.2f}% / {_currency(item.tax_amount)}"
            if item.gst_applicable
            else "Not applicable"
        )
        item_rows.append(
            [
                Paragraph(escape(item.product_name), styles["BodyText"]),
                quantity,
                _currency(item.unit_price),
                _currency(item.discount_amount),
                _currency(item.taxable_value),
                gst_text,
                _currency(item.line_total),
            ]
        )

    item_table = Table(
        item_rows,
        colWidths=[30 * mm, 24 * mm, 20 * mm, 20 * mm, 24 * mm, 31 * mm, 25 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    item_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183B56")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("LEADING", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D4DCE2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F3F6F8")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([item_table, Spacer(1, 7 * mm)])

    totals_rows = [
        ["Subtotal", _currency(invoice.subtotal)],
        ["Discount", f"- {_currency(invoice.discount_amount)}"],
        ["Taxable value", _currency(invoice.taxable_amount)],
        ["Non-taxable value", _currency(invoice.non_taxable_amount)],
        ["GST", _currency(invoice.tax_total)],
        ["Amount payable", _currency(invoice.total_amount)],
    ]
    totals_table = Table(totals_rows, colWidths=[50 * mm, 45 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#183B56")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8F0F5")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([totals_table, Spacer(1, 6 * mm)])

    payment = invoice.payments[0] if invoice.payments else None
    if payment is not None:
        story.append(
            Paragraph(
                f"Payment: {escape(payment.payment_method.upper())} "
                f"({escape(payment.payment_status)}) - {_currency(payment.amount)}",
                styles["Normal"],
            )
        )
    story.append(
        Paragraph(
            "Selling prices are GST-exclusive. GST is added only for products "
            "marked as GST-applicable.",
            styles["Italic"],
        )
    )
    document.build(story)
    return buffer.getvalue()
