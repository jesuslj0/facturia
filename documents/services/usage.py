"""Coste y tokens de la extracción (a partir de `ExtractionRun`)."""
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate

from documents.models import ExtractionRun

_SUMS = {
    "runs": Count("id"),
    "input_tokens": Sum("input_tokens"),
    "output_tokens": Sum("output_tokens"),
    "cache_read_tokens": Sum("cache_read_tokens"),
    "cache_creation_tokens": Sum("cache_creation_tokens"),
    "cost_usd": Sum("cost_usd"),
}


def _clean(row):
    return {k: (v if v is not None else (Decimal("0") if k == "cost_usd" else 0)) for k, v in row.items()}


def extraction_usage(client=None, start=None, end=None):
    """Totales y desglose por modelo y por día. `start`/`end` son fechas (inclusivas).

    Sin `client` agrega todos los tenants (uso interno/operación).
    """
    qs = ExtractionRun.objects.all()
    if client is not None:
        qs = qs.filter(client=client)
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)

    total = _clean(qs.aggregate(**_SUMS))
    documents = qs.values("document_id").distinct().count()
    failed = qs.filter(status="failed").count()
    fallback = qs.filter(is_fallback=True).count()
    by_model = [
        {"model": r.pop("model") or "—", **_clean(r)}
        for r in qs.values("model").annotate(**_SUMS).order_by("-cost_usd")
    ]
    by_day = [
        {"day": r.pop("day"), **_clean(r)}
        for r in qs.annotate(day=TruncDate("created_at")).values("day").annotate(**_SUMS).order_by("day")
    ]
    return {
        **total,
        "documents": documents,
        "failed_runs": failed,
        "fallback_runs": fallback,
        "cost_per_document": (total["cost_usd"] / documents) if documents else Decimal("0"),
        "by_model": by_model,
        "by_day": by_day,
    }
