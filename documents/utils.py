import csv
from django.http import HttpResponse

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
    return response

from openpyxl import Workbook

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

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="documentos.xlsx"'

    wb.save(response)
    return response

from decimal import Decimal, ROUND_HALF_UP

def normalize_tax(base, tax_amount, tax_percentage, total):
    if base and tax_percentage and not tax_amount:
        tax_amount = (base * tax_percentage / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    if base and tax_amount and not tax_percentage:
        tax_percentage = (tax_amount / base * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    if base and tax_amount and not total:
        total = base + tax_amount

    return {
        "base": base,
        "tax_amount": tax_amount,
        "tax_percentage": tax_percentage,
        "total": total,
    }

from decimal import Decimal
import re

def parse_decimal(value):
    if not value:
        return None

    if isinstance(value, str):
        value = value.strip()
        value = value.replace(".", "") if value.count(",") == 1 else value
        value = value.replace(",", ".")
        value = re.sub(r"[^\d.]", "", value)

    return Decimal(value)