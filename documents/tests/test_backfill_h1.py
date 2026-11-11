from datetime import timedelta
from decimal import Decimal as D
from hashlib import sha256
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from documents.models import DocumentAuditLog, DocumentFile, TaxBreakdown
from documents.tests import factories as f

pytestmark = pytest.mark.django_db


def run(*args):
    out, err = StringIO(), StringIO()
    call_command("backfill_h1", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_creates_file_tax_and_audit_and_is_idempotent():
    d = f.DocumentFactory(external_id="bf-1")
    d.file.open("rb")
    digest = sha256(d.file.read()).hexdigest()
    d.file.close()

    run()
    stored = DocumentFile.objects.get(document=d)
    assert stored.sha256 == digest and stored.client_id == d.client_id
    assert stored.mime_type == "application/pdf" and stored.size_bytes > 0
    vat = TaxBreakdown.objects.get(document=d)
    assert (vat.kind, vat.rate, vat.base, vat.amount) == ("vat", D("21.00"), D("100.00"), D("21.00"))
    assert DocumentAuditLog.objects.filter(document=d, action="created").count() == 1

    run()  # segunda vez: no duplica
    assert DocumentFile.objects.count() == 1
    assert TaxBreakdown.objects.count() == 1
    assert DocumentAuditLog.objects.filter(document=d).count() == 1


def test_dry_run_writes_nothing():
    f.DocumentFactory()
    out, _ = run("--dry-run")
    assert "[dry-run]" in out
    assert not DocumentFile.objects.exists()
    assert not TaxBreakdown.objects.exists()
    assert not DocumentAuditLog.objects.exists()


def test_duplicate_content_is_reported_not_failed():
    d1 = f.DocumentFactory(external_id="same")
    d2 = f.DocumentFactory(client=d1.client, external_id="same2")
    d2.file.save("copia.pdf", d1.file.open("rb"), save=False)
    d2.save()
    _, err = run()
    assert DocumentFile.objects.count() == 1
    assert "duplicado" in err


def test_missing_file_is_reported_not_failed(settings):
    d = f.DocumentFactory()
    d.file.storage.delete(d.file.name)
    _, err = run()
    assert "ausente" in err
    assert not DocumentFile.objects.filter(document=d).exists()
    assert TaxBreakdown.objects.filter(document=d).exists()  # el resto sigue


def test_rectification_has_no_own_file_row():
    root = f.DocumentFactory()
    child = f.DocumentFactory(client=root.client, parent_document=root, version=2, is_current=False)
    run()
    assert DocumentFile.objects.filter(document=root).exists()
    assert not DocumentFile.objects.filter(document=child).exists()


def test_audit_events_use_real_dates_and_users():
    u = f.UserFactory()
    d = f.DocumentFactory(client=u.client)
    when = timezone.now() - timedelta(days=3)
    type(d).all_objects.filter(pk=d.pk).update(approved_at=when, approved_by=u, status="approved")
    run()
    ev = DocumentAuditLog.objects.get(document=d, action="approved")
    assert ev.user_id == u.pk and abs((ev.created_at - when).total_seconds()) < 1


def test_skips_tax_row_when_amounts_missing():
    f.DocumentFactory(base_amount=None, tax_amount=None, tax_percentage=None)
    run()
    assert not TaxBreakdown.objects.exists()
