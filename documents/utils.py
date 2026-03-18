import csv
from decimal import Decimal, ROUND_HALF_UP
import re

from django.db.models import Sum
from django.http import HttpResponse
from django.template.loader import render_to_string

from openpyxl import Workbook


def export_to_csv(qs):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="documentos.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Fecha",
        "Número documento",
        "Proveedor",
        "Base imponible",
        "IVA %",
        "Importe IVA",
        "Total",
    ])

    for doc in qs:
        writer.writerow([
            doc.issue_date,
            doc.document_number,
            doc.company.name,
            doc.base_amount,
            doc.tax_percentage,
            doc.tax_amount,
            doc.total_amount,
        ])

    total_base_amount = round(float(qs.aggregate(Sum('base_amount'))['base_amount__sum']), 2)
    total_tax_amount = round(float(qs.aggregate(Sum('tax_amount'))['tax_amount__sum']), 2)
    total_total_amount = round(float(qs.aggregate(Sum('total_amount'))['total_amount__sum']), 2)

    writer.writerow([
        "Totales",
        "",
        "",
        total_base_amount,
        "",
        total_tax_amount,
        total_total_amount
    ])
    return response


def export_to_excel(qs):
    wb = Workbook()
    ws = wb.active
    ws.title = "Documentos"

    headers = [
        "Fecha",
        "Número documento",
        "Proveedor",
        "Base imponible",
        "IVA %",
        "Importe IVA",
        "Total",
    ]

    ws.append(headers)

    for doc in qs:
        ws.append([
            doc.issue_date.strftime("%d/%m/%Y"),
            doc.document_number,
            doc.company.name,
            doc.base_amount,
            doc.tax_percentage,
            doc.tax_amount,
            doc.total_amount,
        ])

    total_base_amount = round(float(qs.aggregate(Sum('base_amount'))['base_amount__sum']), 2)
    total_tax_amount = round(float(qs.aggregate(Sum('tax_amount'))['tax_amount__sum']), 2)
    total_total_amount = round(float(qs.aggregate(Sum('total_amount'))['total_amount__sum']), 2)

    ws.append([
        "Totales",
        "",
        "",
        total_base_amount,
        "",
        total_tax_amount,
        total_total_amount
    ])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="documentos.xlsx"'

    wb.save(response)
    return response


def render_pdf_from_html(html, *, base_url=None):
    from weasyprint import HTML

    return HTML(string=html, base_url=base_url).write_pdf()


def export_invoice_pdf(invoice, *, base_url=None):
    html = render_to_string(
        "private/documents/invoice_pdf.html",
        {"invoice": invoice},
    )
    return render_pdf_from_html(html, base_url=base_url)


def export_invoices_to_pdf(qs, *, base_url=None):
    invoices = list(qs)
    html = render_to_string(
        "private/documents/document_export_pdf.html",
        {"invoices": invoices},
    )
    pdf_bytes = render_pdf_from_html(html, base_url=base_url)

    if not invoices:
        filename = "invoices.pdf"
    elif len(invoices) == 1:
        filename = f"invoice_{invoices[0].id}.pdf"
    else:
        filename = "invoices.pdf"

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def round_decimal(value, places=2):
    if value is None:
        return None
    quantizer = Decimal("1." + "0" * places)
    return to_decimal(value).quantize(quantizer, rounding=ROUND_HALF_UP)


def normalize_tax(base, tax_amount, tax_percentage, total):
    base = round_decimal(base, 2)
    tax_amount = round_decimal(tax_amount, 2)
    tax_percentage = round_decimal(tax_percentage, 2)
    total = round_decimal(total, 2)

    if base and tax_percentage and not tax_amount:
        tax_amount = round_decimal(base * tax_percentage / 100, 2)

    if base and tax_amount and not tax_percentage:
        tax_percentage = round_decimal(tax_amount / base * 100, 2)

    if base and tax_amount and not total:
        total = round_decimal(base + tax_amount, 2)

    return {
        "base": base,
        "tax_amount": tax_amount,
        "tax_percentage": tax_percentage,
        "total": total,
    }


def parse_decimal(value):
    if not value:
        return None

    if isinstance(value, str):
        value = value.strip()
        value = value.replace(".", "") if value.count(",") == 1 else value
        value = value.replace(",", ".")
        value = re.sub(r"[^\d.]", "", value)

    return Decimal(value)
