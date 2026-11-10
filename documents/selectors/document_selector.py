from ..models import Document
import re
from datetime import date, timedelta

from django.db.models import Q

ACTIVE_PROCESSING = ("uploaded", "queued", "processing", "batched")


def quarter_range(value):
    """'2026-T2' -> (date(2026,4,1), date(2026,6,30)); (None, None) si no es válido."""
    m = re.fullmatch(r"(\d{4})-T([1-4])", value or "")
    if not m:
        return None, None
    year, q = int(m.group(1)), int(m.group(2))
    start = date(year, 3 * q - 2, 1)
    nxt = date(year + 1, 1, 1) if q == 4 else date(year, 3 * q + 1, 1)
    return start, nxt - timedelta(days=1)


class DocumentSelector:
    @staticmethod
    def for_client(client):
        return Document.all_objects.filter(client=client, is_current=True)

    @staticmethod
    def with_versions(client):
        return Document.all_objects.filter(client=client)

    @staticmethod
    def archived(client):
        return DocumentSelector.for_client(client).filter(is_archived=True)

    @staticmethod
    def pending(client):
        return DocumentSelector.for_client(client).filter(status="pending")

    @staticmethod
    def approved(client):
        return DocumentSelector.for_client(client).filter(status="approved")

    @staticmethod
    def filtered(client, filters: dict, base_qs=None):
        qs = base_qs if base_qs is not None else DocumentSelector.for_client(client)

        doc_status = filters.get("doc_status")

        if doc_status == "archived":
            qs = qs.filter(is_archived=True)
        elif doc_status == "all":
            pass
        else:
            qs = qs.filter(is_archived=False)

        if filters.get("query"):
            qs = qs.filter(
                Q(original_name__icontains=filters["query"])
                | Q(company__name__icontains=filters["query"])
            )

        if filters.get("company"):
            qs = qs.filter(company__name=filters["company"])

        if filters.get("status"):
            qs = qs.filter(status=filters["status"])

        if filters.get("review_level"):
            qs = qs.filter(review_level=filters["review_level"])

        if filters.get("date_from"):
            qs = qs.filter(issue_date__gte=filters["date_from"])

        if filters.get("date_to"):
            qs = qs.filter(issue_date__lte=filters["date_to"])

        if filters.get("document_type"):
            qs = qs.filter(document_type=filters["document_type"])

        if filters.get("flow"):
            qs = qs.filter(flow=filters["flow"])

        if filters.get("folder"):
            qs = qs.filter(folder_id=filters["folder"]) if str(filters["folder"]).isdigit() else qs.none()

        if filters.get("category"):
            qs = qs.filter(category_id=filters["category"]) if str(filters["category"]).isdigit() else qs.none()

        if filters.get("tag"):
            qs = qs.filter(tags__id=filters["tag"]) if str(filters["tag"]).isdigit() else qs.none()

        if filters.get("quarter"):
            start, end = quarter_range(filters["quarter"])
            qs = qs.filter(issue_date__gte=start, issue_date__lte=end) if start else qs.none()

        if filters.get("processing"):
            value = filters["processing"]
            if value == "active":
                qs = qs.filter(processing_status__in=ACTIVE_PROCESSING)
            elif value in dict(Document.PROCESSING_CHOICES):
                qs = qs.filter(processing_status=value)

        return qs

    @staticmethod
    def available_quarters(client):
        """Trimestres con documentos (más reciente primero): [('2026-T1', '1.er trim. 2026'), ...]."""
        months = (
            DocumentSelector.for_client(client)
            .filter(issue_date__isnull=False)
            .dates("issue_date", "month")
        )
        keys = {(d.year, (d.month - 1) // 3 + 1) for d in months}
        return [(f"{y}-T{q}", f"T{q} {y}") for y, q in sorted(keys, reverse=True)]

    @staticmethod
    def processing_count(client):
        return DocumentSelector.for_client(client).filter(
            processing_status__in=ACTIVE_PROCESSING, is_archived=False
        ).count()

    @staticmethod
    def detail_queryset(client):
        return (
            DocumentSelector.with_versions(client)
            .select_related(
                "company",
                "approved_by",
                "rejected_by",
                "reviewed_by",
                "archived_by",
            )
        )

    @staticmethod
    def version_history(document):
        root = document.parent_document or document
        return (
            DocumentSelector.with_versions(document.client)
            .filter(Q(parent_document=root) | Q(pk=root.pk))
            .order_by("version")
        )
