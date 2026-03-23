from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.models import Company, Document
from documents.selectors.document_selector import DocumentSelector


@pytest.mark.django_db
class TestDocumentSelector:
    def test_for_client_and_with_versions_scope_results(self, client_entity, company, other_client_entity):
        root = Document.all_objects.create(
            client=client_entity,
            company=company,
            external_id="v1",
            original_name="root.pdf",
            file=SimpleUploadedFile("root.pdf", b"x", content_type="application/pdf"),
            document_type="invoice",
            confidence={"score": 0.1},
            status="approved",
            review_level="manual",
            issue_date=date(2026, 3, 1),
            base_amount=Decimal("100.00"),
            tax_amount=Decimal("21.00"),
            tax_percentage=Decimal("21.00"),
            total_amount=Decimal("121.00"),
            flow="in",
            is_current=False,
        )
        current = Document.all_objects.create(
            client=client_entity,
            company=company,
            parent_document=root,
            external_id="v2",
            original_name="current.pdf",
            file=SimpleUploadedFile("current.pdf", b"x", content_type="application/pdf"),
            document_type="invoice",
            confidence={"score": 0.1},
            status="approved",
            review_level="manual",
            issue_date=date(2026, 3, 2),
            base_amount=Decimal("200.00"),
            tax_amount=Decimal("42.00"),
            tax_percentage=Decimal("21.00"),
            total_amount=Decimal("242.00"),
            flow="in",
            version=2,
            is_current=True,
        )
        foreign_company = Company.objects.create(client=other_client_entity, name="Foreign", is_provider=True)
        Document.all_objects.create(
            client=other_client_entity,
            company=foreign_company,
            external_id="foreign",
            original_name="foreign.pdf",
            file=SimpleUploadedFile("foreign.pdf", b"x", content_type="application/pdf"),
            document_type="invoice",
            confidence={"score": 0.1},
            status="approved",
            review_level="manual",
            issue_date=date(2026, 3, 2),
            base_amount=Decimal("50.00"),
            tax_amount=Decimal("10.50"),
            tax_percentage=Decimal("21.00"),
            total_amount=Decimal("60.50"),
            flow="in",
        )

        assert list(DocumentSelector.for_client(client_entity)) == [current]
        assert DocumentSelector.with_versions(client_entity).count() == 2

    def test_filtered_applies_query_and_status_filters(self, client_entity, company, approved_document, document):
        approved_document.original_name = "approved-invoice.pdf"
        approved_document.save(update_fields=["original_name"])

        filters = {"query": "approved", "status": "approved", "doc_status": "all"}
        qs = DocumentSelector.filtered(client_entity, filters)

        assert list(qs) == [approved_document]

    def test_version_history_and_exportable(self, client_entity, company, approved_document):
        from documents.filters.document_filters import get_exportable_documents

        rectified = approved_document.create_rectification(
            user=approved_document.approved_by,
            reason="Fix",
            total_amount=Decimal("130.00"),
        )
        approved_document.refresh_from_db()
        rectified.status = "approved"
        rectified.review_level = "manual"
        rectified.save(update_fields=["status", "review_level"])

        history = list(DocumentSelector.version_history(rectified))
        exportable = list(get_exportable_documents(DocumentSelector.for_client(client_entity)))

        assert history == [approved_document, rectified]
        assert exportable == [rectified]
