from .models import Document, Company
from django.db.models import Q

class DocumentSelector:
    @staticmethod
    def for_client(client):
        return Document.all_objects.filter(client=client)

    @staticmethod
    def archived(client):
        return Document.all_objects.filter(
            client=client,
            is_archived=True
        )
    
    @staticmethod
    def pending(client):
        return DocumentSelector.for_client(client).filter(status="pending")

    @staticmethod
    def filtered(client, filters: dict):
        qs = DocumentSelector.for_client(client)

        doc_status = filters.get("doc_status")

        if doc_status == "archived":
            qs = DocumentSelector.archived(client)

        elif doc_status == "all":
            qs = DocumentSelector.for_client(client)

        if filters.get("query"):
            qs = qs.filter(
                Q(original_name__icontains=filters["query"]) | Q(company__name__icontains=filters["query"])
            )

        if filters.get("company"):
            company = Company.objects.filter(name=filters["company"]).first()
            qs = qs.filter(company=company)

        if filters.get("status"):
            qs = qs.filter(status=filters["status"])

        if filters.get("review_level"):
            qs = qs.filter(review_level=filters["review_level"])

        if filters.get("date_from"):
            qs = qs.filter(issue_date__gte=filters["date_from"], )

        if filters.get("date_to"):
            qs = qs.filter(issue_date__lte=filters["date_to"])

        if filters.get("document_type"):
            qs = qs.filter(document_type=filters["document_type"])

        if filters.get("flow"):
            qs = qs.filter(flow=filters["flow"])

        return qs
    
    @staticmethod
    def detail_queryset(client):
        return (
            DocumentSelector.for_client(client)
            .select_related(
                "company", 
                "approved_by", 
                "rejected_by",
                "reviewed_by",
                "archived_by"
            )
        )