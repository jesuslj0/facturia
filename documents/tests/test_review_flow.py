"""Guardar, aprobar y rectificar desde el detalle: edición + aprobación sin pasos perdidos."""
from datetime import date
from decimal import Decimal as D

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from documents.models import Document
from documents.tests import factories as f
from documents.utils import parse_decimal

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending(client_entity):
    return f.DocumentFactory(client=client_entity, status="pending", flow="unknown")


def url(doc):
    return reverse("documents:detail", kwargs={"pk": doc.pk})


def texts(response):
    return [m.message for m in get_messages(response.wsgi_request)]


class TestApprove:
    def test_cannot_approve_without_flow(self, auth_client, pending):
        r = auth_client.post(url(pending), {"action": "approve"}, follow=True)
        pending.refresh_from_db()
        assert pending.status == "pending"
        assert any("compra o venta" in t for t in texts(r))

    @pytest.mark.parametrize("field, label", [("total_amount", "total"), ("issue_date", "fecha")])
    def test_missing_data_is_a_message_not_a_500(self, auth_client, client_entity, field, label):
        doc = f.DocumentFactory(client=client_entity, status="pending", flow="out", **{field: None})
        r = auth_client.post(url(doc), {"action": "approve"}, follow=True)
        doc.refresh_from_db()
        assert r.status_code == 200 and doc.status == "pending"
        assert any(label in t for t in texts(r))

    def test_approve_saves_the_unsaved_edits_first(self, auth_client, pending, user):
        """Aprobar con el formulario de revisión sin guardar aplica antes los cambios (flujo incluido)."""
        auth_client.post(url(pending), {
            "action": "approve", "flow": "out", "document_number": "NUEVO-1", "total_amount": "242,00",
        })
        pending.refresh_from_db()
        assert pending.status == "approved"
        assert pending.flow == "out" and pending.flow_source == "manual"
        assert pending.document_number == "NUEVO-1" and pending.total_amount == D("242.00")
        assert pending.approved_by == user

    def test_edits_are_kept_even_if_approval_is_blocked(self, auth_client, pending):
        r = auth_client.post(url(pending), {"action": "approve", "flow": "unknown", "document_number": "KEEP-1"}, follow=True)
        pending.refresh_from_db()
        assert pending.status == "pending" and pending.document_number == "KEEP-1"
        assert any("compra o venta" in t for t in texts(r))

    def test_invalid_data_on_approve_does_not_approve(self, auth_client, pending):
        r = auth_client.post(url(pending), {"action": "approve", "flow": "out", "issue_date": "no-es-fecha"}, follow=True)
        pending.refresh_from_db()
        assert r.status_code == 200 and pending.status == "pending"

    def test_plain_approve_still_works(self, auth_client, client_entity):
        doc = f.DocumentFactory(client=client_entity, status="pending", flow="in")
        auth_client.post(url(doc), {"action": "approve"})
        doc.refresh_from_db()
        assert doc.status == "approved"

    def test_auto_approval_requires_a_flow(self, pending):
        assert pending.can_be_approved() is False
        pending.flow = "in"
        assert pending.can_be_approved() is True


class TestSave:
    def test_unknown_flow_is_shown_as_such_not_as_venta(self, auth_client, pending):
        body = auth_client.get(url(pending)).content.decode()
        assert 'value="unknown" selected' in body

    def test_changing_flow_marks_it_manual(self, auth_client, pending):
        auth_client.post(url(pending), {"action": "save", "flow": "in"})
        pending.refresh_from_db()
        assert (pending.flow, pending.flow_source) == ("in", "manual")

    def test_invalid_flow_or_date_is_a_message_not_a_500(self, auth_client, pending):
        for data in ({"flow": "otro"}, {"issue_date": "31/31/2026"}):
            r = auth_client.post(url(pending), {"action": "save", **data}, follow=True)
            assert r.status_code == 200
            assert any("no válid" in t.lower() or "inválid" in t.lower() for t in texts(r))
        pending.refresh_from_db()
        assert pending.flow == "unknown"

    def test_negative_amounts_keep_their_sign(self, auth_client, client_entity):
        doc = f.DocumentFactory(client=client_entity, status="pending", flow="out", document_type="corrected_invoice",
                                total_amount=D("-121.00"))
        auth_client.post(url(doc), {"action": "save", "total_amount": "-121.00"})
        doc.refresh_from_db()
        assert doc.total_amount == D("-121.00")

    def test_parse_decimal(self):
        assert parse_decimal("1.234,56") == D("1234.56")
        assert parse_decimal("121.00") == D("121.00")
        assert parse_decimal("-10,5") == D("-10.5")
        assert parse_decimal("") is None
        with pytest.raises(Exception):
            parse_decimal("abc")


class TestRectify:
    def rectify(self, auth_client, doc, **extra):
        data = {"base_amount": "150.00", "tax_amount": "31.50", "tax_percentage": "21.00", "total_amount": "181.50",
                "issue_date": "2026-03-10", "document_number": "R-1", "company": "", "rectification_reason": "Corrección"}
        data.update(extra)
        auth_client.post(reverse("documents:rectify", kwargs={"pk": doc.pk}), data)
        return Document.objects.exclude(pk=doc.pk).get()

    def test_blank_company_keeps_the_original(self, auth_client, approved_document):
        new = self.rectify(auth_client, approved_document)
        assert new.company_id == approved_document.company_id

    def test_organization_and_origin_are_kept(self, auth_client, approved_document, client_entity):
        cat = f.DocumentCategoryFactory(client=client_entity)
        folder = f.FolderFactory(client=client_entity)
        tag = f.TagFactory(client=client_entity)
        Document.all_objects.filter(pk=approved_document.pk).update(
            category=cat, folder=folder, source="upload", currency="USD", iban="ES9121000418450200051332")
        approved_document.tags.add(tag)
        new = self.rectify(auth_client, Document.all_objects.get(pk=approved_document.pk))
        assert (new.category, new.folder, new.source, new.currency) == (cat, folder, "upload", "USD")
        assert new.iban == "ES9121000418450200051332"
        assert list(new.tags.all()) == [tag]
        assert new.flow == approved_document.flow


class TestOrganize:
    """Carpeta y etiquetas se cambian en cualquier estado sin rectificar ni tocar la revisión."""

    def post(self, auth_client, doc, **data):
        return auth_client.post(url(doc), {"action": "organize", **data}, follow=True)

    @pytest.mark.parametrize("status", ["approved", "rejected"])
    def test_organize_non_pending_document(self, auth_client, client_entity, user, status):
        folder = f.FolderFactory(client=client_entity)
        doc = f.DocumentFactory(client=client_entity, status=status, flow="out", review_level="auto")
        r = self.post(auth_client, doc, folder=folder.pk, tags="viaje, deducible")
        doc = Document.all_objects.get(pk=doc.pk)
        assert doc.folder == folder
        assert sorted(t.name for t in doc.tags.all()) == ["deducible", "viaje"]
        assert doc.status == status and doc.review_level == "auto"  # no cuenta como revisión manual
        assert doc.edited_at is None and doc.version == 1
        assert Document.all_objects.filter(client=client_entity).count() == 1  # sin rectificación
        assert any("Organización guardada" in t for t in texts(r))
        log = doc.audit_logs.filter(action="edited").get()
        assert log.user == user and log.changes["organization"]["to"]["folder"] == folder.pk

    def test_archived_document_can_be_organized(self, auth_client, client_entity):
        folder = f.FolderFactory(client=client_entity)
        doc = f.DocumentFactory(client=client_entity, status="approved", is_archived=True)
        self.post(auth_client, doc, folder=folder.pk)
        assert Document.all_objects.get(pk=doc.pk).folder == folder

    def test_does_not_touch_data_even_if_posted(self, auth_client, client_entity):
        doc = f.DocumentFactory(client=client_entity, status="approved", flow="out", total_amount=D("121.00"))
        self.post(auth_client, doc, folder="", total_amount="999", flow="in", document_type="receipt", company="")
        doc = Document.all_objects.get(pk=doc.pk)
        assert (doc.total_amount, doc.flow, doc.document_type) == (D("121.00"), "out", "invoice")

    def test_new_folder_and_clear(self, auth_client, client_entity):
        folder = f.FolderFactory(client=client_entity)
        doc = f.DocumentFactory(client=client_entity, status="approved", folder=folder)
        self.post(auth_client, doc, folder="", new_folder="Gestoría")
        doc = Document.all_objects.get(pk=doc.pk)
        assert doc.folder.name == "Gestoría"
        self.post(auth_client, doc, folder="")
        assert Document.all_objects.get(pk=doc.pk).folder is None

    def test_foreign_folder_is_ignored(self, auth_client, client_entity, other_client_entity):
        foreign = f.FolderFactory(client=other_client_entity)
        doc = f.DocumentFactory(client=client_entity, status="approved")
        self.post(auth_client, doc, folder=foreign.pk)
        assert Document.all_objects.get(pk=doc.pk).folder is None

    def test_other_tenant_document_is_404(self, auth_client, other_client_entity):
        doc = f.DocumentFactory(client=other_client_entity, status="approved")
        assert auth_client.post(url(doc), {"action": "organize", "tags": "x"}).status_code == 404

    def test_blocked_while_processing(self, auth_client, client_entity):
        doc = f.DocumentFactory(client=client_entity, status="pending", processing_status="processing")
        r = self.post(auth_client, doc, tags="x")
        assert not Document.all_objects.get(pk=doc.pk).tags.exists()
        assert any("procesando" in t for t in texts(r))

    def test_detail_page_has_own_form_for_approved_but_not_for_pending(self, auth_client, client_entity):
        approved = f.DocumentFactory(client=client_entity, status="approved")
        body = auth_client.get(url(approved)).content.decode()
        assert 'id="organization-form"' in body and "Guardar organización" in body
        assert 'name="tags" form="organization-form"' in body
        pending = f.DocumentFactory(client=client_entity, status="pending", flow="out")
        body = auth_client.get(url(pending)).content.decode()
        assert "Guardar organización" not in body and 'name="tags" form="review-form"' in body

    def test_pending_save_still_saves_organization(self, auth_client, client_entity):
        folder = f.FolderFactory(client=client_entity)
        doc = f.DocumentFactory(client=client_entity, status="pending", flow="out")
        auth_client.post(url(doc), {"action": "save", "folder": folder.pk, "tags": "a"})
        doc = Document.all_objects.get(pk=doc.pk)
        assert doc.folder == folder and [t.name for t in doc.tags.all()] == ["a"]
