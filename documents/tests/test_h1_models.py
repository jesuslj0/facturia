from datetime import date
from decimal import Decimal as D

import pytest
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction

from documents.models import Company, DocumentAuditLog, TaxBreakdown
from documents.tests import factories as f

pytestmark = pytest.mark.django_db


class TestCompany:
    def test_blank_tax_id_saved_as_null_and_does_not_collide(self):
        client = f.ClientFactory()
        a = Company.objects.create(client=client, name="A", tax_id="")
        b = Company.objects.create(client=client, name="B", tax_id="   ")
        assert a.tax_id is None and b.tax_id is None  # no viola unique(client, tax_id)

    def test_tax_id_normalized(self):
        c = f.CompanyFactory(tax_id=" b-123 456 ")
        assert c.tax_id == "B123456"

    def test_new_address_fields_default(self):
        c = f.CompanyFactory()
        assert c.country == "ES" and c.address == ""


class TestDocumentDefaults:
    def test_new_fields_do_not_change_existing_flow(self):
        d = f.DocumentFactory()
        assert (d.processing_status, d.source, d.currency, d.iban) == ("processed", "n8n", "EUR", "")
        assert d.category is None and d.folder is None and d.tags.count() == 0

    @pytest.mark.parametrize("day,expected", [
        (date(2026, 1, 1), "2026-T1"), (date(2026, 3, 31), "2026-T1"),
        (date(2026, 4, 1), "2026-T2"), (date(2026, 9, 30), "2026-T3"),
        (date(2026, 12, 31), "2026-T4"),
    ])
    def test_quarter(self, day, expected):
        assert f.DocumentFactory(issue_date=day).quarter == expected

    def test_quarter_without_date(self):
        assert f.DocumentFactory(issue_date=None).quarter is None


class TestDocumentFile:
    def test_unique_hash_per_client(self):
        d1 = f.DocumentFactory()
        d2 = f.DocumentFactory(client=d1.client)
        f.DocumentFileFactory(document=d1, sha256="a" * 64)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.DocumentFileFactory(document=d2, sha256="a" * 64)

    def test_same_hash_allowed_in_other_tenant(self):
        f.DocumentFileFactory(sha256="b" * 64)
        f.DocumentFileFactory(sha256="b" * 64)  # otro cliente

    def test_one_file_per_document(self):
        d = f.DocumentFactory()
        f.DocumentFileFactory(document=d)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.DocumentFileFactory(document=d, sha256="c" * 64)

    def test_client_must_match_document(self):
        d = f.DocumentFactory()
        other = f.ClientFactory()
        with pytest.raises(ValueError):
            f.DocumentFileFactory(document=d, client=other)

    def test_cascade_with_document(self):
        d = f.DocumentFactory()
        f.DocumentFileFactory(document=d)
        d.delete()
        from documents.models import DocumentFile
        assert DocumentFile.objects.count() == 0


class TestExtractionRun:
    def test_defaults_and_ordering(self):
        d = f.DocumentFactory()
        r1 = f.ExtractionRunFactory(document=d, attempt=1)
        r2 = f.ExtractionRunFactory(document=d, attempt=2, is_fallback=True, model="claude-sonnet-5-5")
        assert list(d.extraction_runs.all()) == [r2, r1]
        assert r1.status == "pending" and r1.input_tokens == 0 and r1.raw_response == {}

    def test_client_must_match_document(self):
        with pytest.raises(ValueError):
            f.ExtractionRunFactory(document=f.DocumentFactory(), client=f.ClientFactory())


class TestTaxBreakdown:
    def test_unique_kind_rate_per_document(self):
        d = f.DocumentFactory()
        f.TaxBreakdownFactory(document=d)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.TaxBreakdownFactory(document=d)

    def test_vat_and_withholding_can_coexist_and_same_rate_different_kind(self):
        d = f.DocumentFactory()
        f.TaxBreakdownFactory(document=d, kind="vat", rate=D("15"), amount=D("15"))
        f.TaxBreakdownFactory(document=d, kind="withholding", rate=D("15"), amount=D("15"))
        assert d.tax_lines.count() == 2

    @pytest.mark.parametrize("rate,amount", [(D("101"), D("1")), (D("-1"), D("1")), (D("21"), D("-0.01"))])
    def test_check_constraints(self, rate, amount):
        with pytest.raises(IntegrityError), transaction.atomic():
            f.TaxBreakdownFactory(rate=rate, amount=amount)

    def test_total_with_irpf_from_db_rows(self):
        from documents.services import taxes
        d = f.DocumentFactory(base_amount=D("1000"), tax_amount=D("210"), total_amount=D("1060"))
        f.TaxBreakdownFactory(document=d, kind="vat", rate=D("21"), base=D("1000"), amount=D("210"))
        f.TaxBreakdownFactory(document=d, kind="withholding", rate=D("15"), base=D("1000"), amount=D("150"))
        assert taxes.totals_match(d.total_amount, taxes.expected_total_from_lines(d.base_amount, d.tax_lines.all()))


class TestInvoiceLine:
    def test_unique_position_and_rate_range(self):
        d = f.DocumentFactory()
        f.InvoiceLineFactory(document=d, position=1)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.InvoiceLineFactory(document=d, position=1)
        with pytest.raises(IntegrityError), transaction.atomic():
            f.InvoiceLineFactory(document=d, position=2, tax_rate=D("150"))

    def test_ordered_by_position(self):
        d = f.DocumentFactory()
        f.InvoiceLineFactory(document=d, position=2, description="b")
        f.InvoiceLineFactory(document=d, position=1, description="a")
        assert [l.description for l in d.lines.all()] == ["a", "b"]


class TestOrganization:
    def test_unique_names_per_client(self):
        c = f.ClientFactory()
        for factory_cls in (f.DocumentCategoryFactory, f.FolderFactory, f.TagFactory):
            factory_cls(client=c, name="X")
            with pytest.raises(IntegrityError), transaction.atomic():
                factory_cls(client=c, name="X")
            factory_cls(client=f.ClientFactory(), name="X")  # otro tenant: ok

    def test_category_deleted_keeps_document(self):
        cat = f.DocumentCategoryFactory()
        d = f.DocumentFactory(client=cat.client, category=cat)
        cat.delete()
        d.refresh_from_db()
        assert d.category is None

    def test_tags_m2m(self):
        d = f.DocumentFactory()
        t = f.TagFactory(client=d.client)
        d.tags.add(t)
        assert list(t.documents.all()) == [d]


class TestAuditLog:
    def test_append_only(self):
        log = f.DocumentAuditLogFactory()
        log.action = "edited"
        with pytest.raises(ValueError):
            log.save()

    def test_user_set_null_on_delete(self):
        u = f.UserFactory()
        log = f.DocumentAuditLogFactory(user=u)
        u.delete()
        log.refresh_from_db()
        assert log.user is None
