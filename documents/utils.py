import csv
from decimal import Decimal, ROUND_HALF_UP
import re

from django.db.models import Sum
from django.http import HttpResponse
from django.template.loader import render_to_string

from openpyxl import Workbook


EXPORT_HEADERS = [
    "Fecha",
    "Tipo",
    "Número documento",
    "Tercero",
    "NIF",
    "Base imponible",
    "IVA %",
    "Importe IVA",
    "Retención",
    "Total",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value):
    """Neutraliza la inyección de fórmulas en CSV/Excel.

    Un texto que empiece por = + - @ (o tab/CR) se interpreta como fórmula al abrirlo
    en Excel/LibreOffice; se antepone una comilla simple. Solo afecta a `str`:
    los números y fechas no se tocan (un importe negativo es un `Decimal`, no texto).
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _withholding_by_document(docs):
    from documents.models import TaxBreakdown

    ids = [d.pk for d in docs]
    totals = {}
    for kind_row in TaxBreakdown.objects.filter(document_id__in=ids, kind="withholding"):
        totals[kind_row.document_id] = totals.get(kind_row.document_id, Decimal("0")) + kind_row.amount
    return totals


def export_rows(qs):
    """Filas exportables (con signo contable: las rectificativas restan) y totales.

    Devuelve `(rows, totals)`; `totals` = (base, iva, retención, total) como `Decimal`.
    Funciona con un queryset vacío y con documentos sin tercero ni importes.
    """
    from documents.services.signs import signed_value

    docs = list(qs.select_related("company").order_by("issue_date", "pk"))
    withholding = _withholding_by_document(docs)
    zero = Decimal("0")
    sums = [zero, zero, zero, zero]
    rows = []
    for doc in docs:
        kind = doc.document_type
        base = signed_value(kind, doc.base_amount)
        tax = signed_value(kind, doc.tax_amount)
        total = signed_value(kind, doc.total_amount)
        held = signed_value(kind, withholding.get(doc.pk))
        for i, v in enumerate((base, tax, held, total)):
            sums[i] += v or zero
        rows.append([
            doc.issue_date,
            doc.get_document_type_display(),
            doc.document_number or "",
            doc.company.name if doc.company else "",
            (doc.company.tax_id or "") if doc.company else "",
            base,
            doc.tax_percentage,
            tax,
            held,
            total,
        ])
    return rows, tuple(sums)


def export_to_csv(qs):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="documentos.csv"'
    writer = csv.writer(response)
    writer.writerow(EXPORT_HEADERS)

    rows, (base, tax, held, total) = export_rows(qs)
    for row in rows:
        writer.writerow([sanitize_cell(v) for v in row])

    writer.writerow(["Totales", "", "", "", "", base, "", tax, held, total])
    return response


def export_to_excel(qs):
    wb = Workbook()
    ws = wb.active
    ws.title = "Documentos"
    ws.append(EXPORT_HEADERS)

    rows, (base, tax, held, total) = export_rows(qs)
    for row in rows:
        ws.append([sanitize_cell(v) for v in row])

    ws.append(["Totales", "", "", "", "", base, "", tax, held, total])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="documentos.xlsx"'

    wb.save(response)
    return response

from weasyprint import HTML
def render_pdf_from_html(html, *, base_url=None):
    return HTML(string=html, base_url=base_url).write_pdf()

def export_invoice_pdf(invoice, *, base_url=None):
    html = render_to_string(
        "private/documents/invoice_pdf.html",
        {"invoice": invoice},
    )
    return render_pdf_from_html(html, base_url=base_url)


def export_invoices_to_pdf(qs, *, base_url=None, inline=False,**context):
    html = render_to_string(
        "private/documents/invoice_list_pdf.html",
        context,
    )
    pdf_bytes = render_pdf_from_html(html, base_url=base_url)

    invoices = context.get("invoices", [])

    filename = "facturas.pdf" if len(invoices) != 1 else f"factura_{invoices[0].document_number}.pdf"

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response

from django.utils import timezone
from django.db.models import Sum, Count

_ROWS_PER_PDF_PAGE = 30


def _paginate_invoices(invoices_list):
    from decimal import Decimal
    zero = Decimal("0")
    pages = []
    for i in range(0, max(len(invoices_list), 1), _ROWS_PER_PDF_PAGE):
        chunk = invoices_list[i:i + _ROWS_PER_PDF_PAGE]
        pages.append({
            "invoices": chunk,
            "subtotals": {
                "base": sum((inv.base_amount or zero) for inv in chunk),
                "tax": sum((inv.tax_amount or zero) for inv in chunk),
                "total": sum((inv.total_amount or zero) for inv in chunk),
            },
        })
    return pages


def _logo_as_data_uri(client):
    if not client.logo:
        return None
    try:
        import base64, mimetypes
        name = client.logo.name.lower()
        mime = mimetypes.guess_type(name)[0] or "image/png"
        with client.logo.open("rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def build_pdf_context(qs, request):
    from documents.services.signs import signed_amount, signed_value

    client = request.user.client
    invoices = list(qs.select_related("company"))
    for inv in invoices:  # solo en memoria (no se guarda): rectificativas con signo negativo
        for field in ("base_amount", "tax_amount", "total_amount"):
            setattr(inv, field, signed_value(inv.document_type, getattr(inv, field)))
    return {
        "invoices": invoices,
        "pages": _paginate_invoices(invoices),
        "client": client,
        "logo_data_uri": _logo_as_data_uri(client),
        "date": timezone.now(),
        "totals": qs.aggregate(
            base_total=Sum(signed_amount("base_amount")),
            tax_total=Sum(signed_amount("tax_amount")),
            total=Sum(signed_amount("total_amount")),
            count=Count("id"),
        ),
    }

from django.shortcuts import render
def render_pdf_preview(request, context):
    return render(request, "private/documents/invoice_list_pdf.html", context)

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
        value = re.sub(r"[^\d.\-]", "", value)

    return Decimal(value)
