"""H10: convivencia con n8n, importación y criterio de apagado."""
import json
from datetime import timedelta
from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from documents.models import Document, DocumentFile
from documents.services import n8n_exit, processing
from documents.services.n8n_import import import_directory
from documents.tests import factories as f
from documents.tests.fakes import FakeExtractor, make_result
from documents.tests.test_processing import client_a, new_doc, pdf  # noqa: F401

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "external_id": "old-1", "document_type": "invoice", "provider_name": "Proveedor SL",
    "provider_tax_id": "B12345674", "document_number": "F-1", "issue_date": "2026-01-10",
    "base_amount": 100, "tax_amount": 21, "tax_percentage": 21, "total_amount": 121,
    "confidence": {"confianza_extraccion": 0.95, "fecha": 0.9, "total": 0.9}, "flow": "out",
}


def write(dir_, name, payload=None, content=None, ext=".pdf"):
    (dir_ / f"{name}{ext}").write_bytes(content or pdf())
    (dir_ / f"{name}.json").write_text(json.dumps(payload if payload is not None else PAYLOAD))


class TestImport:
    def test_imports_with_source_import(self, tmp_path, client_a):
        write(tmp_path, "a")
        r = import_directory(client_a, tmp_path)
        assert (r.imported, r.duplicates, r.errors) == (1, 0, [])
        doc = Document.all_objects.get()
        assert doc.source == "import" and doc.processing_status == "processed"
        assert doc.original_name == "a.pdf" and doc.company.tax_id == "B12345674"
        assert DocumentFile.objects.get(document=doc).origin == "import"

    def test_idempotent(self, tmp_path, client_a):
        write(tmp_path, "a")
        import_directory(client_a, tmp_path)
        r = import_directory(client_a, tmp_path)
        assert (r.imported, r.duplicates) == (0, 1)
        assert Document.all_objects.count() == 1

    def test_same_content_other_name_is_duplicate(self, tmp_path, client_a):
        same = pdf()
        write(tmp_path, "a", content=same)
        write(tmp_path, "b", payload={**PAYLOAD, "external_id": "old-2"}, content=same)
        r = import_directory(client_a, tmp_path)
        assert (r.imported, r.duplicates) == (1, 1)

    def test_duplicate_of_app_upload_is_detected(self, tmp_path, client_a):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from documents.services.upload import upload_document
        data = pdf()
        upload_document(client=client_a, user=None, uploaded=SimpleUploadedFile("x.pdf", data))
        write(tmp_path, "a", content=data)
        assert import_directory(client_a, tmp_path).duplicates == 1

    def test_errors_do_not_stop_the_import(self, tmp_path, client_a):
        write(tmp_path, "bad", payload={"provider_name": "x"})
        (tmp_path / "orphan.json").write_text("{}")
        (tmp_path / "broken.pdf").write_bytes(pdf())
        (tmp_path / "broken.json").write_text("{no json")
        write(tmp_path, "good", payload={**PAYLOAD, "external_id": "g"}, content=pdf(2))
        r = import_directory(client_a, tmp_path)
        assert r.imported == 1 and len(r.errors) == 3
        assert {n for n, _ in r.errors} == {"bad.json", "orphan.json", "broken.json"}

    def test_dry_run_creates_nothing(self, tmp_path, client_a):
        write(tmp_path, "a")
        assert import_directory(client_a, tmp_path, dry_run=True).imported == 1
        assert Document.all_objects.count() == 0

    def test_command(self, tmp_path, client_a):
        write(tmp_path, "a")
        out = StringIO()
        call_command("import_n8n", str(tmp_path), "--client", str(client_a.pk), stdout=out)
        assert "Importados: 1" in out.getvalue()


def processed_app_doc(client, result=None, *, approve=True, auto=False, age_days=40):
    d = new_doc(client)
    processing.run_processing(d.pk, extractor=FakeExtractor("claude-haiku-5-5", [result or make_result()]))
    d.refresh_from_db()
    Document.all_objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(days=age_days))
    if approve:
        d.status, d.is_auto_approved = "approved", auto
        d.save()
    return d


class TestExitReport:
    def test_no_data(self):
        r = n8n_exit.build_report()
        assert r.app_share is None and r.field_accuracy is None and not r.ready

    def test_all_criteria_met(self, client_a):
        for i in range(10):
            processed_app_doc(client_a, make_result(document_number=f"F-{i}"), age_days=10 + i)
        Document.all_objects.filter(pk=Document.all_objects.order_by("pk").first().pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        r = n8n_exit.build_report(client=client_a)
        assert r.app_share == 1.0 and r.field_accuracy == 1.0 and r.reviewed_documents == 9  # el de 40 días queda fuera de la ventana
        assert r.critical_incidents == 0 and r.ready

    def test_corrections_lower_accuracy(self, client_a):
        d = processed_app_doc(client_a)
        Document.all_objects.filter(pk=d.pk).update(total_amount=D("999.00"), document_number="OTRO")
        r = n8n_exit.build_report(client=client_a)
        assert r.errors_by_field == {"document_number": 1, "total_amount": 1}
        assert r.fields_correct == r.fields_compared - 2 and not r.checks["field_accuracy"]

    def test_auto_approved_and_pending_not_measured(self, client_a):
        processed_app_doc(client_a, auto=True)
        processed_app_doc(client_a, make_result(document_number="F-2"), approve=False)
        assert n8n_exit.build_report(client=client_a).reviewed_documents == 0

    def test_n8n_volume_breaks_share(self, client_a):
        processed_app_doc(client_a)
        for i in range(2):
            f.DocumentFactory(client=client_a, source="n8n", external_id=f"n{i}")
        r = n8n_exit.build_report(client=client_a)
        assert (r.app_documents, r.n8n_documents) == (1, 2) and not r.checks["app_share"]

    def test_imports_do_not_count(self, client_a):
        processed_app_doc(client_a)
        f.DocumentFactory(client=client_a, source="import")
        assert n8n_exit.build_report(client=client_a).n8n_documents == 0

    def test_critical_incident_blocks(self, client_a):
        d = processed_app_doc(client_a)
        f.ExtractionRunFactory(document=d, client=client_a, status="failed", error_code="unexpected_error")
        r = n8n_exit.build_report(client=client_a)
        assert r.critical_incidents == 1 and not r.checks["no_critical_incidents"]
        f.ExtractionRunFactory(document=d, client=client_a, status="failed", error_code="rate_limited")
        assert n8n_exit.build_report(client=client_a).critical_incidents == 1

    def test_short_history_blocks(self, client_a):
        processed_app_doc(client_a, age_days=3)
        assert not n8n_exit.build_report(client=client_a).checks["enough_history"]

    def test_tenant_isolation(self, client_a):
        processed_app_doc(client_a)
        assert n8n_exit.build_report(client=f.ClientFactory()).app_documents == 0

    def test_command_output(self, client_a):
        processed_app_doc(client_a)
        out = StringIO()
        call_command("n8n_exit_report", stdout=out)
        assert "NO se cumple" in out.getvalue() and "Campos correctos" in out.getvalue()
