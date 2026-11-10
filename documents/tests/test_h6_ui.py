"""H6: subida, pantalla de revisión, filtros y organización."""
import io
from datetime import date
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pypdf import PdfWriter

from documents.models import Document, DocumentAuditLog, DocumentFile
from documents.selectors.document_selector import DocumentSelector, quarter_range
from documents.services import organization, upload as up
from documents.tests import factories as f

pytestmark = pytest.mark.django_db


def pdf_bytes(tag=b""):
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.add_metadata({"/Title": tag.decode() or "x"})
    b = io.BytesIO(); w.write(b)
    return b.getvalue()


def upload(name="a.pdf", data=None):
    return SimpleUploadedFile(name, data if data is not None else pdf_bytes())


@pytest.fixture(autouse=True)
def no_queue():
    with patch("documents.tasks.process_document.delay") as m:
        yield m


class TestUploadService:
    def test_creates_document_file_audit_and_enqueues(self, user, no_queue, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            r = up.upload_document(client=user.client, user=user, uploaded=upload("fac.pdf"))
        assert r.status == up.CREATED
        d = r.document
        assert (d.status, d.processing_status, d.source, d.flow) == ("pending", "queued", "upload", "unknown")
        assert d.original_name == "fac.pdf"
        assert DocumentFile.objects.get(document=d).origin == "upload"
        assert DocumentFile.objects.get(document=d).uploaded_by == user
        assert DocumentAuditLog.objects.filter(document=d, action="created").exists()
        no_queue.assert_called_once_with(d.pk)

    def test_mobile_origin(self, user):
        r = up.upload_document(client=user.client, user=user, uploaded=upload(), origin="mobile")
        assert DocumentFile.objects.get(document=r.document).origin == "mobile"

    def test_duplicate_by_hash_is_not_created_again(self, user):
        first = up.upload_document(client=user.client, user=user, uploaded=upload("a.pdf"))
        again = up.upload_document(client=user.client, user=user, uploaded=upload("otro-nombre.pdf"))
        assert again.status == up.DUPLICATE
        assert again.document == first.document
        assert Document.all_objects.filter(client=user.client).count() == 1

    def test_same_content_other_tenant_is_not_duplicate(self, user, other_user):
        up.upload_document(client=user.client, user=user, uploaded=upload())
        r = up.upload_document(client=other_user.client, user=other_user, uploaded=upload())
        assert r.status == up.CREATED

    @pytest.mark.parametrize("data", [b"", b"no soy un pdf, solo texto"])
    def test_rejects_empty_and_unknown_types(self, user, data):
        r = up.upload_document(client=user.client, user=user, uploaded=upload("x.pdf", data))
        assert r.status == up.REJECTED
        assert not Document.all_objects.filter(client=user.client).exists()

    def test_rejects_too_big(self, user, settings):
        settings.UPLOAD_MAX_FILE_MB = 0
        r = up.upload_document(client=user.client, user=user, uploaded=upload())
        assert r.status == up.REJECTED and "máximo" in r.message

    def test_name_is_sanitised(self, user):
        r = up.upload_document(client=user.client, user=user, uploaded=upload("../../etc/pas.pdf"))
        assert r.document.original_name == "pas.pdf"

    def test_retry_only_for_failed_pending(self, user):
        d = up.upload_document(client=user.client, user=user, uploaded=upload()).document
        assert up.retry_processing(d) is False        # en cola
        Document.all_objects.filter(pk=d.pk).update(processing_status="failed")
        d.refresh_from_db()
        assert up.retry_processing(d) is True
        d.refresh_from_db()
        assert d.processing_status == "queued"


class TestUploadView:
    def test_requires_login(self, client):
        r = client.get(reverse("documents:upload"))
        assert r.status_code == 302 and "/login/" in r.url

    def test_get_renders_with_camera_input(self, auth_client):
        r = auth_client.get(reverse("documents:upload"))
        assert r.status_code == 200
        assert b'capture="environment"' in r.content and b"multiple" in r.content

    def test_post_multiple_files(self, auth_client, user):
        r = auth_client.post(reverse("documents:upload"), {
            "files": [upload("a.pdf", pdf_bytes(b"a")), upload("b.pdf", pdf_bytes(b"b"))],
            "photos": [upload("c.pdf", pdf_bytes(b"c"))],
        })
        assert r.status_code == 302 and "processing=active" in r.url
        docs = Document.all_objects.filter(client=user.client)
        assert docs.count() == 3
        origins = set(DocumentFile.objects.filter(client=user.client).values_list("origin", flat=True))
        assert origins == {"upload", "mobile"}

    def test_post_without_files_shows_error(self, auth_client):
        r = auth_client.post(reverse("documents:upload"), {})
        assert r.status_code == 200
        assert "al menos un archivo" in r.content.decode()

    def test_post_too_many_files(self, auth_client):
        files = [upload(f"{i}.pdf", pdf_bytes(str(i).encode())) for i in range(21)]
        r = auth_client.post(reverse("documents:upload"), {"files": files})
        assert r.status_code == 200 and Document.all_objects.count() == 0

    def test_duplicate_and_invalid_reported(self, auth_client):
        auth_client.post(reverse("documents:upload"), {"files": [upload("a.pdf")]})
        r = auth_client.post(reverse("documents:upload"), {"files": [upload("a.pdf"), upload("t.pdf", b"texto")]}, follow=True)
        texts = [m.message for m in r.context["messages"]]
        assert any("ya estaba subido" in t for t in texts)
        assert any("tipo no permitido" in t for t in texts)


@pytest.fixture
def pending_doc(user):
    return f.DocumentFactory(client=user.client, status="pending", flow="out")


class TestReviewScreen:
    def url(self, d):
        return reverse("documents:detail", kwargs={"pk": d.pk})

    def test_processing_banner_and_no_edit_or_approve(self, auth_client, pending_doc):
        Document.all_objects.filter(pk=pending_doc.pk).update(processing_status="processing")
        r = auth_client.get(self.url(pending_doc))
        assert b"Extrayendo datos" in r.content and b'name="total_amount"' not in r.content
        r = auth_client.post(self.url(pending_doc), {"action": "approve"})
        pending_doc.refresh_from_db()
        assert pending_doc.status == "pending"

    def test_failed_shows_error_and_retry(self, auth_client, pending_doc, no_queue, django_capture_on_commit_callbacks):
        Document.all_objects.filter(pk=pending_doc.pk).update(processing_status="failed")
        f.ExtractionRunFactory(document=pending_doc, status="failed", error_code="too_many_pages",
                               error_message="El PDF tiene 30 páginas (máximo 20).")
        r = auth_client.get(self.url(pending_doc))
        assert "30 páginas" in r.content.decode() and b'value="retry"' in r.content
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(self.url(pending_doc), {"action": "retry"})
        pending_doc.refresh_from_db()
        assert pending_doc.processing_status == "queued"
        no_queue.assert_called_once_with(pending_doc.pk)

    def test_issues_and_breakdown_are_shown(self, auth_client, pending_doc):
        Document.all_objects.filter(pk=pending_doc.pk).update(validation_issues=[
            {"code": "total_mismatch", "severity": "error", "message": "El total no cuadra.", "field": "total_amount", "model_fixable": True},
        ])
        f.TaxBreakdownFactory(document=pending_doc)
        f.InvoiceLineFactory(document=pending_doc, description="Consultoría")
        r = auth_client.get(self.url(pending_doc))
        body = r.content.decode()
        assert "El total no cuadra." in body and "has-issue" in body
        assert "Consultoría" in body and "Impuestos y retenciones" in body

    def test_next_pending_link_only_same_tenant(self, auth_client, pending_doc, other_user):
        f.DocumentFactory(client=other_user.client, status="pending")
        assert auth_client.get(self.url(pending_doc)).context["next_pending"] is None
        nxt = f.DocumentFactory(client=pending_doc.client, status="pending")
        assert auth_client.get(self.url(pending_doc)).context["next_pending"] == nxt

    def test_save_updates_type_company_category_folder_tags(self, auth_client, user, pending_doc):
        co = f.CompanyFactory(client=user.client)
        cat = f.DocumentCategoryFactory(client=user.client)
        r = auth_client.post(self.url(pending_doc), {
            "action": "save", "document_type": "receipt", "company": co.pk, "category": cat.pk,
            "folder": "", "new_folder": "Gastos 2026", "tags": "viaje, Cliente A, viaje",
        })
        assert r.status_code == 302
        pending_doc.refresh_from_db()
        assert pending_doc.document_type == "receipt" and pending_doc.company == co
        assert pending_doc.category == cat and pending_doc.folder.name == "Gastos 2026"
        assert sorted(t.name for t in pending_doc.tags.all()) == ["Cliente A", "viaje"]

    def test_save_ignores_other_tenant_ids(self, auth_client, pending_doc, other_user):
        foreign_co = f.CompanyFactory(client=other_user.client)
        foreign_folder = f.FolderFactory(client=other_user.client)
        foreign_cat = f.DocumentCategoryFactory(client=other_user.client)
        original_company = pending_doc.company
        auth_client.post(self.url(pending_doc), {
            "action": "save", "company": foreign_co.pk, "folder": foreign_folder.pk, "category": foreign_cat.pk,
        })
        pending_doc.refresh_from_db()
        assert pending_doc.company == original_company
        assert pending_doc.folder is None and pending_doc.category is None

    def test_save_without_org_fields_keeps_them(self, auth_client, user, pending_doc):
        folder = f.FolderFactory(client=user.client)
        Document.all_objects.filter(pk=pending_doc.pk).update(folder=folder)
        auth_client.post(self.url(pending_doc), {"action": "save", "document_number": "X-1"})
        pending_doc.refresh_from_db()
        assert pending_doc.folder == folder and pending_doc.document_number == "X-1"

    def test_tags_reuse_existing_case_insensitive(self, user, pending_doc):
        tag = f.TagFactory(client=user.client, name="Viaje")
        organization.set_tags(pending_doc, "viaje")
        assert list(pending_doc.tags.all()) == [tag]


class TestListFilters:
    def test_filter_by_folder_tag_category_quarter_processing(self, auth_client, user):
        c = user.client
        folder, tag, cat = f.FolderFactory(client=c), f.TagFactory(client=c), f.DocumentCategoryFactory(client=c)
        hit = f.DocumentFactory(client=c, folder=folder, category=cat, issue_date=date(2026, 5, 3))
        hit.tags.add(tag)
        f.DocumentFactory(client=c, issue_date=date(2026, 1, 3))
        f.DocumentFactory(client=c, issue_date=date(2026, 5, 3), processing_status="queued")
        url = reverse("documents:list")

        def ids(**params):
            return [d.pk for d in auth_client.get(url, params).context["documents"]]

        assert ids(folder=folder.pk) == [hit.pk]
        assert ids(tag=tag.pk) == [hit.pk]
        assert ids(category=cat.pk) == [hit.pk]
        assert hit.pk in ids(quarter="2026-T2") and len(ids(quarter="2026-T2")) == 2
        assert len(ids(processing="active")) == 1
        assert ids(folder="abc") == [] and ids(quarter="2026-T9") == []

    def test_filters_do_not_leak_between_tenants(self, auth_client, other_user):
        folder = f.FolderFactory(client=other_user.client)
        f.DocumentFactory(client=other_user.client, folder=folder)
        assert list(auth_client.get(reverse("documents:list"), {"folder": folder.pk}).context["documents"]) == []

    def test_list_context_options_and_processing_count(self, auth_client, user):
        f.DocumentFactory(client=user.client, issue_date=date(2026, 8, 1), processing_status="processing")
        ctx = auth_client.get(reverse("documents:list")).context
        assert ctx["quarters"] == [("2026-T3", "T3 2026")] and ctx["processing_count"] == 1

    def test_quarter_range(self):
        assert quarter_range("2026-T4") == (date(2026, 10, 1), date(2026, 12, 31))
        assert quarter_range("2026-T1") == (date(2026, 1, 1), date(2026, 3, 31))
        assert quarter_range("x") == (None, None)


class TestModel:
    def test_processing_documents_cannot_be_edited_or_approved(self):
        d = f.DocumentFactory(processing_status="queued")
        assert d.is_processing and not d.is_editable and not d.can_be_approved()
        d2 = f.DocumentFactory(processing_status="failed")
        assert d2.is_editable


class TestSharedUi:
    def test_badge_and_icon_registry(self):
        from django.template import Context, Template
        out = Template('{% load ui %}{% badge "status" "approved" %}|{% badge "review" "required" %}|{% icon "approve" %}|{% badge "x" "y" %}').render(Context())
        assert "tone-success" in out and "Aprobado" in out and "fa-circle-check" in out
        assert "tone-danger" in out and "Obligatoria" in out and "fa-check" in out
        assert out.endswith("|")

    def test_same_status_same_icon_everywhere(self, auth_client, user):
        f.DocumentFactory(client=user.client, status="pending", review_level="required")
        for url in (reverse("documents:list"), reverse("dashboard")):
            body = auth_client.get(url).content.decode()
            assert 'data-review="required"' in body and "fa-circle-exclamation" in body

    def test_review_key_follows_effective_state(self):
        d = f.DocumentFactory(status="rejected", review_level="required")
        assert d.review_key == "manual"
        assert f.DocumentFactory(status="pending", review_level="recommended").review_key == "recommended"

    @pytest.mark.parametrize("name,expected", [
        ("documents:list", "Documentos"), ("documents:upload", "Subir"), ("dashboard", "Inicio"),
        ("metrics", "Métricas"), ("finance:movements", "Movimientos"), ("finance:categories", "Categorías"), ("finance:new_movement", "Movimientos"), ("finance:new_category", "Categorías"), ("clients:detail", "Perfil"),
    ])
    def test_sidebar_marks_active_page(self, auth_client, name, expected):
        import re
        body = auth_client.get(reverse(name)).content.decode()
        active = re.findall(r'<a [^>]*class="active"[^>]*>.*?<span class="nav-label">(.*?)</span>', body, re.S)
        assert active == [expected]
        assert "Cerrar sesión" in body

    def test_detail_keeps_documents_active_and_login_has_no_sidebar(self, auth_client, client, user):
        d = f.DocumentFactory(client=user.client)
        body = auth_client.get(reverse("documents:detail", kwargs={"pk": d.pk})).content.decode()
        assert body.count('class="active"') == 1
        assert 'id="sidebar"' not in client.get(reverse("login")).content.decode()


class TestSidebarUser:
    def test_shows_username_and_first_role(self, auth_client, user):
        body = auth_client.get(reverse("dashboard")).content.decode()
        assert 'class="sidebar-user"' in body and user.username in body
        assert 'class="sidebar-role">Owner<' in body

    def test_no_role_badge_without_roles(self, auth_client, user):
        user.roles.clear()
        assert "sidebar-role" not in auth_client.get(reverse("dashboard")).content.decode().split("sidebar-user-name")[1].split("</aside>")[0]


class TestLogoutConfirmation:
    def test_logout_button_opens_dialog_instead_of_posting(self, auth_client):
        body = auth_client.get(reverse("dashboard")).content.decode()
        assert 'id="logout-open"' in body and 'type="button"' in body.split('id="logout-open"')[0][-80:]
        dialog = body.split('<dialog')[1].split('</dialog>')[0]
        assert f'action="{reverse("logout")}"' in dialog and 'method="post"' in dialog and "csrfmiddlewaretoken" in dialog

    def test_logout_still_works_via_post(self, auth_client):
        assert auth_client.post(reverse("logout")).status_code == 302
        assert auth_client.get(reverse("documents:list")).status_code == 302


class TestFinanceSeparateEntries:
    def test_movements_and_categories_are_separate_top_level_links(self, auth_client):
        body = auth_client.get(reverse("dashboard")).content.decode()
        assert "nav-group" not in body and "nav-sub" not in body
        nav = body.split('class="sidebar-nav"')[1].split("</nav>")[0]
        assert nav.count("<a ") == 7
        assert nav.index("Documentos") < nav.index("Movimientos") < nav.index("Categorías") < nav.index("Métricas")

    def test_edit_category_keeps_categories_active(self, auth_client, user):
        import re
        from finance.models import MovementCategory
        c = MovementCategory.objects.create(client=user.client, name="X", type="expense")
        body = auth_client.get(reverse("finance:edit_category", kwargs={"pk": c.pk})).content.decode()
        active = re.findall(r'<a [^>]*class="active"[^>]*>.*?<span class="nav-label">(.*?)</span>', body, re.S)
        assert active == ["Categorías"]


class TestUploadPageLayout:
    def test_side_panels_and_recent_documents(self, auth_client, user, other_user):
        f.DocumentFactory(client=user.client, original_name="mia.pdf")
        f.DocumentFactory(client=other_user.client, original_name="ajena.pdf")
        r = auth_client.get(reverse("documents:upload"))
        body = r.content.decode()
        for text in ("Cómo funciona", "Requisitos", "Últimos documentos", "Hasta 20 archivos por subida"):
            assert text in body
        assert "mia.pdf" in body and "ajena.pdf" not in body and len(r.context["recent_documents"]) == 1

    def test_empty_account_message(self, auth_client):
        assert "Todavía no has subido ningún documento" in auth_client.get(reverse("documents:upload")).content.decode()
