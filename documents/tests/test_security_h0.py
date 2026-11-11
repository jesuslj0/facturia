"""Regresión de seguridad / multi-tenant (hito H0)."""
import pytest
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from documents.forms import DocumentRectificationForm


@pytest.fixture
def other_document(db, other_client_entity):
    Document = apps.get_model("documents", "Document")
    Company = apps.get_model("documents", "Company")
    other_company = Company.objects.create(client=other_client_entity, name="Ajena SL", tax_id="A11111111")
    return Document.all_objects.create(
        client=other_client_entity,
        company=other_company,
        external_id="other-001",
        original_name="secret.pdf",
        file=SimpleUploadedFile("secret.pdf", b"%PDF-1.4 other tenant"),
        document_type="invoice",
        document_number="X-1",
        confidence={"confianza_extraccion": 0.5},
        status="pending",
        review_level="required",
    )


@pytest.mark.django_db
class TestPrivateFiles:
    def test_media_url_is_not_served(self, client, document):
        assert client.get("/media/anything.pdf").status_code == 404
        assert client.get(f"/media/{document.file.name}").status_code == 404

    def test_file_requires_login(self, client, document):
        resp = client.get(reverse("documents:file", args=[document.pk]))
        assert resp.status_code == 302
        assert "/login/" in resp["Location"]

    def test_owner_gets_file(self, auth_client, document):
        resp = auth_client.get(reverse("documents:file", args=[document.pk]))
        assert resp.status_code == 200
        assert b"".join(resp.streaming_content)
        assert resp["X-Content-Type-Options"] == "nosniff"
        assert "no-store" in resp["Cache-Control"]

    def test_other_tenant_cannot_get_file(self, auth_client, other_document):
        resp = auth_client.get(reverse("documents:file", args=[other_document.pk]))
        assert resp.status_code == 404

    def test_upload_path_is_per_tenant_and_not_user_controlled(self, document, client_entity):
        assert document.file.name.startswith(f"{client_entity.pk}/documents/")
        assert "invoice" not in document.file.name.split("/")[-1].replace(".pdf", "")

    def test_key_is_sha256_of_content(self, client_entity):
        import hashlib
        from billing_ai.storage import document_upload_to

        content = b"%PDF-1.4 contenido determinista"
        doc = apps.get_model("documents", "Document")(client=client_entity)
        doc.file = SimpleUploadedFile("Factura Cliente.PDF", content)  # asignado, sin guardar
        key = document_upload_to(doc, "Factura Cliente.PDF")
        digest = hashlib.sha256(content).hexdigest()
        assert key.startswith(f"{client_entity.pk}/documents/")
        assert key.endswith(f"/{digest}.pdf")
        assert doc.file.file.read() == content  # puntero restaurado

    def test_same_content_same_key_different_content_different_key(self, client_entity):
        from billing_ai.storage import document_upload_to
        Document = apps.get_model("documents", "Document")

        def key(content):
            doc = Document(client=client_entity)
            doc.file = SimpleUploadedFile("a.pdf", content)
            return document_upload_to(doc, "a.pdf")

        assert key(b"%PDF-1 A") == key(b"%PDF-1 A")
        assert key(b"%PDF-1 A") != key(b"%PDF-1 B")

    def test_saved_file_is_never_hashed_as_new_content(self, document):
        """Un archivo ya guardado no debe usarse para nombrar otro (sería el contenido antiguo)."""
        from billing_ai.storage import document_upload_to
        key = document_upload_to(document, "x.pdf")
        import hashlib
        with document.file.open("rb") as fh:
            old_hash = hashlib.sha256(fh.read()).hexdigest()
        assert old_hash not in key


@pytest.mark.django_db
class TestRectificationTenantScope:
    def test_form_only_lists_own_companies(self, client_entity, other_client_entity, company):
        Company = apps.get_model("documents", "Company")
        foreign = Company.objects.create(client=other_client_entity, name="Ajena", tax_id="A99999999")
        form = DocumentRectificationForm(client=client_entity)
        qs = form.fields["company"].queryset
        assert company in qs
        assert foreign not in qs

    def test_form_rejects_foreign_company(self, client_entity, other_client_entity):
        Company = apps.get_model("documents", "Company")
        foreign = Company.objects.create(client=other_client_entity, name="Ajena", tax_id="A99999999")
        form = DocumentRectificationForm(
            client=client_entity,
            data={"company": foreign.pk, "rectification_reason": "x"},
        )
        assert not form.is_valid()
        assert "company" in form.errors

    def test_form_without_client_offers_nothing(self):
        form = DocumentRectificationForm()
        assert form.fields["company"].queryset.count() == 0


@pytest.mark.django_db
class TestIngestHardening:
    def _post(self, api_client, api_key, content, name="f.pdf"):
        return api_client.post(
            "/api/v1/documents/ingest/",
            {
                "file": SimpleUploadedFile(name, content),
                "external_id": "ext-h0",
                "original_name": name,
                "document_type": "invoice",
                "provider_name": "Prov",
                "provider_tax_id": "B12345678",
                "base_amount": 100, "tax_amount": 21, "tax_percentage": 21,
                "total_amount": 121, "flow": "out",
                "confidence": '{"confianza_extraccion": 0.5, "fecha": 0.5, "total": 0.5}',
            },
            format="multipart",
            HTTP_X_API_KEY=self.header,
        )

    @pytest.fixture(autouse=True)
    def _header(self, api_key):
        self.header = api_key.raw_key

    def test_rejects_non_allowed_file_type(self, api_client, api_key):
        resp = self._post(api_client, api_key, b"MZ\x90\x00 not a document", "evil.pdf")
        assert resp.status_code == 400
        assert "file" in resp.json()

    def test_rejects_oversized_file(self, api_client, api_key, settings):
        settings.UPLOAD_MAX_FILE_MB = 0
        resp = self._post(api_client, api_key, b"%PDF-1.4 data")
        assert resp.status_code == 400

    def test_inactive_client_cannot_ingest(self, api_client, api_key, client_entity):
        client_entity.is_active = False
        client_entity.save()
        resp = self._post(api_client, api_key, b"%PDF-1.4 data")
        assert resp.status_code in (401, 403)

    def test_api_key_not_printed(self, api_client, api_key, capsys):
        self._post(api_client, api_key, b"%PDF-1.4 data")
        out = capsys.readouterr().out
        assert "test-secret-value" not in out

    def test_existing_company_gets_provider_flag(self, api_client, api_key, client_entity):
        Company = apps.get_model("documents", "Company")
        existing = Company.objects.create(client=client_entity, name="Prov", tax_id="B12345678", is_customer=True)
        resp = self._post(api_client, api_key, b"%PDF-1.4 data")
        assert resp.status_code == 201
        existing.refresh_from_db()
        assert existing.is_provider is True


@pytest.mark.django_db
class TestRoutes:
    def test_broken_approve_reject_routes_removed(self):
        from django.urls import NoReverseMatch
        for name in ("documents:approve", "documents:reject"):
            with pytest.raises(NoReverseMatch):
                reverse(name, args=[1])

    def test_metrics_api_missing_dates_returns_400(self, auth_client):
        resp = auth_client.get("/api/v1/metrics/dashboard/")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestSyncMedia:
    def test_copies_files_keeping_keys_and_is_idempotent(self, tmp_path, settings):
        from django.core.files.storage import default_storage
        from django.core.management import call_command

        old = tmp_path / "old_media"
        (old / "documents").mkdir(parents=True)
        (old / "documents" / "a.pdf").write_bytes(b"%PDF-1.4 a")
        settings.MEDIA_ROOT = old

        call_command("sync_media_to_storage")
        assert default_storage.exists("documents/a.pdf")
        call_command("sync_media_to_storage")  # segunda vez: no duplica
        assert not default_storage.exists("documents/a_1.pdf")


@pytest.mark.django_db
class TestFieldFileSaveHashing:
    """`FieldFile.save(nombre, contenido)`: Django no pasa el contenido a upload_to."""

    def _sha(self, data):
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def test_save_on_empty_field_uses_content_hash(self, client_entity):
        from django.core.files.base import ContentFile
        Document = apps.get_model("documents", "Document")
        doc = Document(client=client_entity)
        content = b"%PDF-1.4 subido con save()"
        doc.file.save("Mi Factura.PDF", ContentFile(content), save=False)
        assert doc.file.name.startswith(f"{client_entity.pk}/documents/")
        assert doc.file.name.endswith(f"/{self._sha(content)}.pdf")
        assert default_storage_read(doc.file.name) == content

    def test_save_on_field_with_existing_file_does_not_hash_the_old_one(self, document, client_entity):
        from django.core.files.base import ContentFile
        old_name = document.file.name
        new = b"%PDF-1.4 contenido NUEVO"
        document.file.save("otra.pdf", ContentFile(new), save=False)
        assert document.file.name != old_name
        assert document.file.name.endswith(f"/{self._sha(new)}.pdf")

    def test_pending_hash_does_not_leak_between_saves(self, client_entity):
        from django.core.files.base import ContentFile
        Document = apps.get_model("documents", "Document")
        doc = Document(client=client_entity)
        doc.file.save("a.pdf", ContentFile(b"%PDF-1.4 A"), save=False)
        assert doc.__dict__["_pending_upload_sha256"] == {}

    def test_logo_and_receipt_fields_also_hash(self, client_entity):
        import io
        from django.core.files.base import ContentFile
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (4, 4), "red").save(buf, "PNG")
        client_entity.logo.save("logo.png", ContentFile(buf.getvalue()), save=False)
        assert client_entity.logo.name.endswith(f"/{self._sha(buf.getvalue())}.png")
        assert f"{client_entity.pk}/logos/" in client_entity.logo.name

        from finance.models import FinancialMovement
        m = FinancialMovement()
        m.client = client_entity
        m.receipt.save("r.pdf", ContentFile(b"%PDF-1.4 recibo"), save=False)
        assert m.receipt.name.endswith(f"/{self._sha(b'%PDF-1.4 recibo')}.pdf")
        assert f"{client_entity.pk}/receipts/" in m.receipt.name


def default_storage_read(name):
    from django.core.files.storage import default_storage
    with default_storage.open(name, "rb") as fh:
        return fh.read()
