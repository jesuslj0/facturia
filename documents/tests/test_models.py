from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.models import Company, Document


@pytest.mark.django_db
class TestCompanyModel:
    def test_company_normalizes_name_and_tax_id_on_save(self, client_entity):
        company = Company.objects.create(
            client=client_entity,
            name="  Example Supplier  ",
            tax_id=" b-12345678 ",
            is_provider=True,
        )

        assert company.name == "Example Supplier"
        assert company.tax_id == "B12345678"
        assert company.get_type() == "Proveedor"

    def test_company_string_representation_uses_type_label(self, customer_company):
        assert str(customer_company) == "Cliente Uno (Cliente)"


@pytest.mark.django_db
class TestDocumentModel:
    def test_document_file_helpers(self, document):
        assert document.extension == ".pdf"
        assert document.is_pdf is True
        assert document.is_image is False

    def test_document_status_and_confidence_helpers(self, document, user):
        assert document.display_review_level == "Revisión obligatoria"
        assert document.status_message == "Documento pendiente de revisión"
        assert document.ocr_confidence == "high"

        document.mark_as_manually_reviewed(user)

        assert document.review_level == "manual"
        assert document.reviewed_by == user
        assert document.is_auto_approved is False
        assert document.edited_at is not None

    def test_document_approve_reject_archive_unarchive_flow(self, document, user):
        document.approve(user=user, auto=False)
        document.refresh_from_db()

        assert document.status == "approved"
        assert document.approved_by == user
        assert document.approved_at is not None

        document.archive(user=user)
        document.refresh_from_db()
        assert document.is_archived is True
        assert "archivado" in document.status_message.lower()

        document.unarchive(user=user)
        document.refresh_from_db()
        assert document.is_archived is False
        assert document.archived_at is None

    def test_document_reject_requires_pending_status(self, approved_document, user):
        with pytest.raises(ValidationError, match="Document cannot be rejected"):
            approved_document.reject(user=user, reason="No válido")

    def test_document_approve_requires_required_fields(self, document, user):
        document.issue_date = None
        document.save()

        with pytest.raises(ValueError, match="Document cannot be approved"):
            document.approve(user=user, auto=False)

    def test_document_company_must_belong_to_same_client(self, client_entity, other_client_entity):
        foreign_company = Company.objects.create(client=other_client_entity, name="Foreign", is_provider=True)

        with pytest.raises(ValueError, match="Company must belong to the same client"):
            Document.objects.create(
                client=client_entity,
                company=foreign_company,
                external_id="bad-company",
                original_name="invoice.pdf",
                file=SimpleUploadedFile("invoice.pdf", b"x", content_type="application/pdf"),
                document_type="invoice",
                confidence={"score": 0.1},
                issue_date=date(2026, 3, 10),
                base_amount=Decimal("10.00"),
                tax_amount=Decimal("2.10"),
                tax_percentage=Decimal("21.00"),
                total_amount=Decimal("12.10"),
                flow="in",
            )

    def test_create_rectification_creates_new_current_version(self, approved_document, user):
        new_doc = approved_document.create_rectification(
            user=user,
            reason="Datos corregidos",
            base_amount=Decimal("150.00"),
            total_amount=Decimal("181.50"),
        )

        approved_document.refresh_from_db()
        assert approved_document.is_current is False
        assert new_doc.parent_document_id == approved_document.id
        assert new_doc.version == 2
        assert new_doc.is_current is True
        assert new_doc.base_amount == Decimal("150.00")
        assert new_doc.amount_snapshot["base_amount"] == 100.0
