"""Criterio de apagado de n8n (H10), medido con datos reales.

Se puede apagar n8n (`N8N_INGEST_ENABLED=False`) cuando, en una ventana de 28 días:
  1. el volumen subido por la app es > 90 % de lo ingerido (app vs n8n; las importaciones no cuentan);
  2. ≥ 95 % de los campos extraídos coinciden con el valor final tras la revisión humana;
  3. no hay incidencias críticas de extracción;
y la app lleva al menos 28 días en uso.

La exactitud solo se mide sobre documentos revisados por una persona (aprobados sin
auto-aprobación): los auto-aprobados no tienen una verdad con la que comparar.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from documents.models import Document, ExtractionRun
from documents.services.companies import normalize_tax_id
from documents.services.extraction.normalize import normalize
from documents.services.extraction.schemas import ExtractionResult

MIN_APP_SHARE = 0.90
MIN_FIELD_ACCURACY = 0.95
WINDOW_DAYS = 28
CRITICAL_ERROR_CODES = ("unexpected_error", "apply_failed", "configuration")
TOLERANCE = Decimal("0.01")

FIELDS = ("document_number", "issue_date", "base_amount", "tax_amount", "total_amount", "counterparty_tax_id", "flow")


@dataclass
class ExitReport:
    days: int
    app_documents: int = 0
    n8n_documents: int = 0
    app_share: float | None = None
    reviewed_documents: int = 0
    fields_compared: int = 0
    fields_correct: int = 0
    field_accuracy: float | None = None
    errors_by_field: dict = field(default_factory=dict)
    critical_incidents: int = 0
    days_in_use: int = 0
    checks: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return all(self.checks.values())


def _same_money(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(Decimal(a) - Decimal(b)) <= TOLERANCE


def compare_fields(extracted, doc) -> dict:
    """{campo: ¿coincide la extracción con el documento final?}"""
    vat = [t.amount for t in extracted.tax_lines if t.kind == "vat" and t.amount is not None]
    tax_id = normalize_tax_id(doc.company.tax_id) if doc.company and doc.company.tax_id else None
    return {
        "document_number": (extracted.document_number or "").strip().upper() == (doc.document_number or "").strip().upper(),
        "issue_date": extracted.issue_date == doc.issue_date,
        "base_amount": _same_money(extracted.base_amount, doc.base_amount),
        "tax_amount": _same_money(sum(vat, Decimal(0)) if vat else None, doc.tax_amount),
        "total_amount": _same_money(extracted.total_amount, doc.total_amount),
        "counterparty_tax_id": (normalize_tax_id(extracted.counterparty_tax_id) if extracted.counterparty_tax_id else None) == tax_id,
        "flow": extracted.flow == doc.flow,
    }


def build_report(*, days: int = WINDOW_DAYS, client=None, now=None) -> ExitReport:
    now = now or timezone.now()
    since = now - timedelta(days=days)
    docs = Document.all_objects.filter(parent_document__isnull=True)
    runs = ExtractionRun.objects.all()
    if client is not None:
        docs, runs = docs.filter(client=client), runs.filter(client=client)

    r = ExitReport(days=days)

    counts = docs.filter(created_at__gte=since).aggregate(
        app=Count("id", filter=Q(source="upload")), n8n=Count("id", filter=Q(source="n8n")),
    )
    r.app_documents, r.n8n_documents = counts["app"], counts["n8n"]
    total = r.app_documents + r.n8n_documents
    r.app_share = (r.app_documents / total) if total else None

    first_app = docs.filter(source="upload").order_by("created_at").values_list("created_at", flat=True).first()
    r.days_in_use = (now - first_app).days if first_app else 0

    # Exactitud: documento raíz de la app, con extracción correcta, cuya versión vigente fue revisada.
    roots = docs.filter(source="upload", created_at__gte=since, processing_status="processed")
    for root in roots:
        run = root.extraction_runs.filter(status="succeeded").order_by("-created_at").first()
        if run is None or "parsed" not in run.raw_response:
            continue
        current = (
            Document.all_objects.filter(Q(pk=root.pk) | Q(parent_document=root), is_current=True)
            .select_related("company").first()
        )
        if current is None or current.status != "approved" or current.is_auto_approved:
            continue
        extracted = normalize(
            ExtractionResult.model_validate(run.raw_response["parsed"]), client_tax_id=root.client.tax_id or "",
        )
        r.reviewed_documents += 1
        for name, ok in compare_fields(extracted, current).items():
            r.fields_compared += 1
            if ok:
                r.fields_correct += 1
            else:
                r.errors_by_field[name] = r.errors_by_field.get(name, 0) + 1
    r.field_accuracy = (r.fields_correct / r.fields_compared) if r.fields_compared else None

    r.critical_incidents = runs.filter(
        created_at__gte=since, status="failed", error_code__in=CRITICAL_ERROR_CODES
    ).count()

    r.checks = {
        "app_share": r.app_share is not None and r.app_share > MIN_APP_SHARE,
        "field_accuracy": r.field_accuracy is not None and r.field_accuracy >= MIN_FIELD_ACCURACY,
        "no_critical_incidents": r.critical_incidents == 0,
        "enough_history": r.days_in_use >= days,
    }
    return r
