"""
Tests for document approval / rejection / archive / unarchive flows and
multi-tenancy isolation.  These tests focus on the *happy-path* and
*edge-case* scenarios that the other test files do not already cover.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from documents.models import Company, Document
from documents.services.documents_service import DocumentService
from documents.selectors.document_selector import DocumentSelector
from documents.filters.document_filters import get_exportable_documents

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_document(client_entity, company, *, external_id, status="pending", flow="in"):
    return Document.all_objects.create(
        client=client_entity,
        company=company,
        external_id=external_id,
        original_name="doc.pdf",
        file=SimpleUploadedFile("doc.pdf", b"x", content_type="application/pdf"),
        document_type="invoice",
        document_number=f"INV-{external_id}",
        confidence={"confianza_extraccion": 0.95, "fecha": 0.9, "total": 0.95},
        status=status,
        review_level="required",
        issue_date=date(2026, 3, 10),
        base_amount=Decimal("100.00"),
        tax_amount=Decimal("21.00"),
        tax_percentage=Decimal("21.00"),
        total_amount=Decimal("121.00"),
        confidence_global=Decimal("0.9500"),
        flow=flow,
        is_current=True,
    )


# ---------------------------------------------------------------------------
# Document approve / reject / archive lifecycle
# ---------------------------------------------------------------------------

class TestDocumentApprovalFlow:
    def test_approve_pending_document_sets_status_and_metadata(self, document, user):
        DocumentService.approve(document, user=user)
        document.refresh_from_db()

        assert document.status == "approved"
        assert document.approved_by == user
        assert document.approved_at is not None
        assert document.is_auto_approved is False

    def test_auto_approve_does_not_set_approved_by(self, document):
        DocumentService.auto_approve(document)
        document.refresh_from_db()

        assert document.status == "approved"
        assert document.approved_by is None
        assert document.approved_at is None
        assert document.is_auto_approved is True

    def test_approve_document_missing_total_amount_raises(self, document, user):
        document.total_amount = None
        document.save()

        with pytest.raises(ValueError, match="Document cannot be approved"):
            DocumentService.approve(document, user=user)

    def test_approve_document_missing_issue_date_raises(self, document, user):
        document.issue_date = None
        document.save()

        with pytest.raises(ValueError, match="Document cannot be approved"):
            DocumentService.approve(document, user=user)

    def test_reject_pending_document_sets_reason_and_user(self, document, user):
        DocumentService.reject(document, user=user, reason="Factura duplicada")
        document.refresh_from_db()

        assert document.status == "rejected"
        assert document.rejected_by == user
        assert document.rejected_at is not None
        assert document.rejection_reason == "Factura duplicada"

    def test_reject_already_approved_document_raises(self, approved_document, user):
        with pytest.raises(ValidationError, match="Document cannot be rejected"):
            DocumentService.reject(approved_document, user=user, reason="No válido")

    def test_archive_approved_document_hides_from_active_manager(self, approved_document, user):
        DocumentService.archive(approved_document, user=user)
        approved_document.refresh_from_db()

        assert approved_document.is_archived is True
        assert approved_document.archived_by == user
        assert approved_document.archived_at is not None
        # ActiveDocumentManager must exclude it
        assert not Document.objects.filter(pk=approved_document.pk).exists()
        # all_objects still finds it
        assert Document.all_objects.filter(pk=approved_document.pk).exists()

    def test_archive_pending_document_raises(self, document, user):
        with pytest.raises(ValidationError, match="Document cannot be archived"):
            DocumentService.archive(document, user=user)

    def test_unarchive_restores_document_to_active_manager(self, approved_document, user):
        DocumentService.archive(approved_document, user=user)
        DocumentService.unarchive(approved_document, user=user)
        approved_document.refresh_from_db()

        assert approved_document.is_archived is False
        assert approved_document.archived_at is None
        assert Document.objects.filter(pk=approved_document.pk).exists()

    def test_unarchive_non_archived_document_raises(self, approved_document, user):
        with pytest.raises(ValidationError, match="Document is not archived"):
            DocumentService.unarchive(approved_document, user=user)

    def test_archive_rejected_document_is_allowed(self, client_entity, company, user):
        doc = make_document(client_entity, company, external_id="rej-arc-1", status="pending")
        DocumentService.reject(doc, user=user, reason="Wrong")
        DocumentService.archive(doc, user=user)
        doc.refresh_from_db()
        assert doc.is_archived is True


# ---------------------------------------------------------------------------
# Multi-tenancy isolation
# ---------------------------------------------------------------------------

class TestMultiTenancyIsolation:
    def test_document_selector_for_client_excludes_other_client_docs(
        self, client_entity, other_client_entity, company, document
    ):
        # document belongs to client_entity; create one for other_client_entity too
        foreign_company = Company.objects.create(
            client=other_client_entity, name="Foreign Co", is_provider=True
        )
        make_document(other_client_entity, foreign_company, external_id="foreign-1")

        qs = DocumentSelector.for_client(client_entity)
        client_ids = set(qs.values_list("client_id", flat=True))
        assert client_ids == {client_entity.pk}

    def test_document_detail_view_returns_404_for_wrong_client(
        self, auth_client, other_client_entity
    ):
        foreign_company = Company.objects.create(
            client=other_client_entity, name="ForeignCo", is_provider=True
        )
        foreign_doc = make_document(
            other_client_entity, foreign_company, external_id="foreign-view-1"
        )

        response = auth_client.get(reverse("documents:detail", kwargs={"pk": foreign_doc.pk}))
        assert response.status_code == 404

    def test_document_list_view_isolates_per_client(
        self, auth_client, document, other_client_entity
    ):
        foreign_company = Company.objects.create(
            client=other_client_entity, name="OtherCo", is_provider=True
        )
        make_document(other_client_entity, foreign_company, external_id="other-list-1")

        response = auth_client.get(reverse("documents:list"))
        assert response.status_code == 200
        pks = [d.pk for d in response.context["documents"]]
        assert document.pk in pks
        # Must not show the foreign doc
        assert all(d.client == document.client for d in response.context["documents"])

    def test_rectify_view_returns_404_for_other_client_document(
        self, auth_client, other_client_entity, user
    ):
        foreign_company = Company.objects.create(
            client=other_client_entity, name="ForeignRectify", is_provider=True
        )
        foreign_doc = make_document(
            other_client_entity, foreign_company, external_id="foreign-rect-1", status="approved"
        )
        foreign_doc.approved_by = user
        foreign_doc.save(update_fields=["approved_by"])

        response = auth_client.get(reverse("documents:rectify", kwargs={"pk": foreign_doc.pk}))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Document view — reject action
# ---------------------------------------------------------------------------

class TestDocumentDetailViewReject:
    def test_reject_action_sets_rejection_status(self, auth_client, document):
        response = auth_client.post(
            reverse("documents:detail", kwargs={"pk": document.pk}),
            data={"action": "reject", "rejection_reason": "Datos incorrectos"},
        )
        document.refresh_from_db()

        assert response.status_code == 302
        assert document.status == "rejected"
        assert document.rejection_reason == "Datos incorrectos"

    def test_archive_action_archives_approved_document(self, auth_client, approved_document):
        response = auth_client.post(
            reverse("documents:detail", kwargs={"pk": approved_document.pk}),
            data={"action": "archive"},
        )
        approved_document.refresh_from_db()

        assert response.status_code == 302
        assert approved_document.is_archived is True

    def test_unarchive_action_restores_archived_document(self, auth_client, approved_document, user):
        DocumentService.archive(approved_document, user=user)

        response = auth_client.post(
            reverse("documents:detail", kwargs={"pk": approved_document.pk}),
            data={"action": "unarchive"},
        )
        approved_document.refresh_from_db()

        assert response.status_code == 302
        assert approved_document.is_archived is False

    def test_unknown_action_redirects_with_warning(self, auth_client, document):
        from django.contrib.messages import get_messages

        response = auth_client.post(
            reverse("documents:detail", kwargs={"pk": document.pk}),
            data={"action": "teleport"},
            follow=True,
        )
        msgs = [m.message for m in get_messages(response.wsgi_request)]
        assert any("Acción no reconocida" in m for m in msgs)


# ---------------------------------------------------------------------------
# Document is_editable / display_review_level properties
# ---------------------------------------------------------------------------

class TestDocumentProperties:
    def test_is_editable_true_for_pending_non_archived(self, document):
        assert document.is_editable is True

    def test_is_editable_false_for_approved_document(self, approved_document):
        assert approved_document.is_editable is False

    def test_is_editable_false_for_archived_document(self, document, user):
        # Approve first so we can archive
        DocumentService.approve(document, user=user)
        DocumentService.archive(document, user=user)
        document.refresh_from_db()
        assert document.is_editable is False

    def test_display_review_level_returns_manual_for_approved_with_timestamp(
        self, approved_document
    ):
        assert approved_document.display_review_level == "Manual"

    def test_display_review_level_returns_auto_for_auto_approved(self, document):
        document.review_level = "auto"
        document.status = "approved"
        document.approved_at = None
        document.save()
        assert document.display_review_level == "Auto"

    def test_ocr_confidence_medium_bucket(self, document):
        document.confidence_global = Decimal("0.75")
        document.save()
        assert document.ocr_confidence == "medium"

    def test_ocr_confidence_low_bucket(self, document):
        document.confidence_global = Decimal("0.50")
        document.save()
        assert document.ocr_confidence == "low"

    def test_ocr_confidence_returns_low_when_none(self, document):
        document.confidence_global = None
        document.save()
        assert document.ocr_confidence == "low"

    def test_status_message_shows_archived_info(self, approved_document, user):
        DocumentService.archive(approved_document, user=user)
        approved_document.refresh_from_db()
        assert "archivado" in approved_document.status_message.lower()

    def test_status_message_shows_rejected_info(self, document, user):
        DocumentService.reject(document, user=user, reason="Wrong")
        document.refresh_from_db()
        assert "rechazado" in document.status_message.lower()


# ---------------------------------------------------------------------------
# Document filters — exportable queryset
# ---------------------------------------------------------------------------

class TestGetExportableDocuments:
    def test_excludes_archived_documents(self, approved_document, user):
        DocumentService.archive(approved_document, user=user)
        qs = get_exportable_documents(
            DocumentSelector.for_client(approved_document.client)
        )
        assert approved_document not in qs

    def test_excludes_pending_documents(self, document):
        qs = get_exportable_documents(DocumentSelector.for_client(document.client))
        assert document not in qs

    def test_includes_only_invoice_and_corrected_invoice_types(
        self, client_entity, company, user
    ):
        delivery = make_document(client_entity, company, external_id="delivery-1")
        delivery.document_type = "delivery"
        delivery.status = "approved"
        delivery.save()

        inv = make_document(client_entity, company, external_id="inv-export-1")
        inv.status = "approved"
        inv.review_level = "manual"
        inv.save()

        qs = get_exportable_documents(DocumentSelector.for_client(client_entity))
        types = set(qs.values_list("document_type", flat=True))
        assert "delivery" not in types
        assert "invoice" in types

    def test_raises_if_base_qs_is_none(self):
        with pytest.raises(ValueError, match="base_qs is required"):
            get_exportable_documents(base_qs=None)


# ---------------------------------------------------------------------------
# Document selector — additional filter paths
# ---------------------------------------------------------------------------

class TestDocumentSelectorFilters:
    def test_filtered_by_company_name(self, client_entity, company, document):
        result = list(DocumentSelector.filtered(client_entity, {"company": company.name}))
        assert document in result

    def test_filtered_by_flow(self, client_entity, company, document):
        result = DocumentSelector.filtered(client_entity, {"flow": "in"})
        assert document in list(result)

        result_out = DocumentSelector.filtered(client_entity, {"flow": "out"})
        assert document not in list(result_out)

    def test_filtered_by_date_range(self, client_entity, document):
        result_in = DocumentSelector.filtered(
            client_entity,
            {"date_from": date(2026, 3, 1), "date_to": date(2026, 3, 31)},
        )
        assert document in list(result_in)

        result_out = DocumentSelector.filtered(
            client_entity,
            {"date_from": date(2026, 4, 1), "date_to": date(2026, 4, 30)},
        )
        assert document not in list(result_out)

    def test_filtered_by_review_level(self, client_entity, document):
        result = DocumentSelector.filtered(client_entity, {"review_level": "required"})
        assert document in list(result)

        result_none = DocumentSelector.filtered(client_entity, {"review_level": "auto"})
        assert document not in list(result_none)

    def test_filtered_doc_status_archived(self, client_entity, approved_document, user):
        DocumentService.archive(approved_document, user=user)
        result = list(
            DocumentSelector.filtered(client_entity, {"doc_status": "archived"})
        )
        assert approved_document in result

    def test_filtered_doc_status_all_includes_archived(
        self, client_entity, approved_document, user
    ):
        DocumentService.archive(approved_document, user=user)
        result = list(
            DocumentSelector.filtered(client_entity, {"doc_status": "all"})
        )
        assert approved_document in result

    def test_pending_selector(self, client_entity, document):
        result = list(DocumentSelector.pending(client_entity))
        assert document in result

    def test_approved_selector(self, client_entity, approved_document):
        result = list(DocumentSelector.approved(client_entity))
        assert approved_document in result

    def test_archived_selector(self, client_entity, approved_document, user):
        DocumentService.archive(approved_document, user=user)
        result = list(DocumentSelector.archived(client_entity))
        assert approved_document in result


# ---------------------------------------------------------------------------
# Rectification — edge cases
# ---------------------------------------------------------------------------

class TestDocumentRectification:
    def test_rectification_carries_forward_original_amounts_when_not_overridden(
        self, approved_document, user
    ):
        new_doc = DocumentService.rectify(
            document=approved_document,
            user=user,
            reason="Corrección menor",
        )
        assert new_doc.base_amount == approved_document.base_amount
        assert new_doc.total_amount == approved_document.total_amount

    def test_rectification_stores_amount_snapshot_of_parent(
        self, approved_document, user
    ):
        new_doc = DocumentService.rectify(
            document=approved_document,
            user=user,
            reason="Fix snapshot",
            form_data={"base_amount": Decimal("200.00"), "total_amount": Decimal("242.00")},
        )
        assert new_doc.amount_snapshot["base_amount"] == float(
            approved_document.base_amount
        )
        assert new_doc.amount_snapshot["total_amount"] == float(
            approved_document.total_amount
        )

    def test_cannot_rectify_pending_document(self, auth_client, document):
        """GET on rectify view for a pending document should redirect with warning."""
        from django.contrib.messages import get_messages

        response = auth_client.get(
            reverse("documents:rectify", kwargs={"pk": document.pk}),
            follow=True,
        )
        msgs = [m.message for m in get_messages(response.wsgi_request)]
        assert response.redirect_chain[-1][0] == reverse(
            "documents:detail", kwargs={"pk": document.pk}
        )
        assert any("no puede ser rectificado" in m.lower() for m in msgs)

    def test_rectify_archived_document_is_blocked(self, auth_client, approved_document, user):
        """Archived documents must not be rectifiable."""
        from django.contrib.messages import get_messages

        DocumentService.archive(approved_document, user=user)

        response = auth_client.get(
            reverse("documents:rectify", kwargs={"pk": approved_document.pk}),
            follow=True,
        )
        msgs = [m.message for m in get_messages(response.wsgi_request)]
        assert any("no puede ser rectificado" in m.lower() for m in msgs)
