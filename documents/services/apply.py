"""Aplica el resultado normalizado de una extracción a un Document.

Idempotente: se puede ejecutar varias veces; desglose de impuestos y líneas se
reemplazan. No aprueba nada (la política de auto-aprobación llega con la validación, H5).
"""
from decimal import Decimal

from django.db import transaction

from documents.models import Document, DocumentAuditLog, InvoiceLine, TaxBreakdown
from documents.services.companies import get_or_create_company
from documents.services.review import get_review_level

CENT = Decimal("0.01")
MAX_MONEY = Decimal("100000000")  # Document: max_digits=10, decimal_places=2


def _money(value):
    if value is None or abs(value) >= MAX_MONEY:
        return None
    return value.quantize(CENT)


def _rate_ok(rate):
    return rate is not None and Decimal(0) <= rate <= Decimal(100)


def apply_extraction(document, outcome, *, user=None) -> Document:
    n = outcome.normalized
    with transaction.atomic():
        doc = Document.all_objects.select_for_update().get(pk=document.pk)

        company = None
        if n.counterparty_name or n.counterparty_tax_id:
            company = get_or_create_company(
                client=doc.client,
                name=n.counterparty_name or n.counterparty_tax_id,
                tax_id=n.counterparty_tax_id,
                is_provider=n.flow == "out",
                is_customer=n.flow == "in",
            )
        doc.company = company

        if n.document_type:
            doc.document_type = n.document_type
        doc.document_number = n.document_number
        doc.issue_date = n.issue_date
        doc.currency = n.currency
        doc.iban = n.iban
        doc.flow = n.flow
        doc.flow_source = "auto"

        vat = [
            t for t in n.tax_lines
            if t.kind == "vat" and t.amount is not None and (t.rate is None or _rate_ok(t.rate))
        ]
        doc.base_amount = _money(n.base_amount)
        doc.total_amount = _money(n.total_amount)
        doc.tax_amount = _money(sum((t.amount for t in vat), Decimal(0))) if vat else None
        rates = {t.rate for t in vat if t.rate is not None}
        doc.tax_percentage = rates.pop() if len(rates) == 1 and _rate_ok(next(iter(rates), None)) else None
        if doc.total_amount is not None:
            doc.total_source = "explicit"
        elif doc.base_amount is not None and doc.tax_amount is not None:
            doc.total_source = "base_tax"
        else:
            doc.total_source = "unknown"

        doc.confidence = n.legacy_confidence()
        doc.confidence_global = Decimal(str(round(n.confidence_global, 4)))
        doc.review_level = _review_level(doc, n)
        doc.is_auto_approved = False
        doc.processing_status = "processed"
        doc.save()

        _replace_tax_lines(doc, n)
        _replace_lines(doc, n)

        DocumentAuditLog(
            document=doc, user=user, action="extracted",
            changes={
                "run_id": outcome.run.pk, "model": outcome.run.model,
                "fallback": outcome.used_fallback, "flow": n.flow,
                "confidence": round(n.confidence_global, 4),
            },
        ).save()
    return doc


def _review_level(doc, n) -> str:
    incomplete = (
        n.flow == "unknown" or doc.total_amount is None
        or doc.issue_date is None or n.document_type is None
    )
    if incomplete:
        return "required"
    level = get_review_level(doc.confidence, doc.document_type)
    # Sin auto-aprobación hasta que exista validación determinista (H5).
    return "recommended" if level == "auto" else level


def _replace_tax_lines(doc, n) -> None:
    doc.tax_lines.all().delete()
    agg: dict[tuple, list] = {}
    for t in n.tax_lines:
        if t.amount is None or not _rate_ok(t.rate):
            continue
        key = (t.kind, t.rate)
        base = t.base if t.base is not None else (doc.base_amount or Decimal(0))
        cur = agg.setdefault(key, [Decimal(0), Decimal(0)])
        cur[0] += abs(t.amount)
        cur[1] = max(cur[1], abs(base))
    TaxBreakdown.objects.bulk_create([
        TaxBreakdown(document=doc, kind=k, rate=r, base=_money(b) or Decimal(0), amount=_money(a) or Decimal(0))
        for (k, r), (a, b) in agg.items()
    ])


def _replace_lines(doc, n) -> None:
    doc.lines.all().delete()
    rows = []
    for ln in n.lines:
        rows.append(InvoiceLine(
            document=doc, position=ln.position, description=ln.description,
            quantity=ln.quantity if ln.quantity is not None and abs(ln.quantity) < Decimal(10) ** 8 else Decimal(1),
            unit_price=ln.unit_price if ln.unit_price is not None and abs(ln.unit_price) < Decimal(10) ** 10 else None,
            tax_rate=ln.tax_rate if _rate_ok(ln.tax_rate) else None,
            amount=_money(ln.amount),
        ))
    InvoiceLine.objects.bulk_create(rows)
