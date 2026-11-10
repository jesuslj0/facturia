"""H7: métricas agregadas, signos de rectificativas y exports seguros."""
import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from documents.models import Document
from documents.services import MetricsService
from documents.services.signs import signed_value
from documents.tests.factories import (
    CompanyFactory, DocumentCategoryFactory, DocumentFactory, TaxBreakdownFactory,
)
from documents.utils import export_to_csv, export_to_excel, sanitize_cell

pytestmark = pytest.mark.django_db

START, END = date(2026, 1, 1), date(2026, 12, 31)


def make(client, **kw):
    kw.setdefault("status", "approved")
    return DocumentFactory(client=client, company__client=client, **kw)


def metrics(user):
    return MetricsService.get_user_metrics(user, START, END)


class TestSigns:
    def test_corrected_always_negative(self):
        assert signed_value("corrected_invoice", Decimal("10")) == Decimal("-10")
        assert signed_value("corrected_invoice", Decimal("-10")) == Decimal("-10")
        assert signed_value("invoice", Decimal("10")) == Decimal("10")
        assert signed_value("invoice", None) is None


class TestMetrics:
    def test_corrected_expense_reduces_expense(self, user, client_entity):
        make(client_entity, flow="out", base_amount=Decimal("100"))
        make(client_entity, flow="out", document_type="corrected_invoice", base_amount=Decimal("30"))
        assert metrics(user)["financials"]["documents"]["expense"] == 70.0

    def test_corrected_stored_negative_gives_same_result(self, user, client_entity):
        make(client_entity, flow="in", base_amount=Decimal("100"))
        make(client_entity, flow="in", document_type="corrected_invoice", base_amount=Decimal("-30"))
        assert metrics(user)["financials"]["documents"]["income"] == 70.0

    def test_without_period_uses_current_month(self, user):
        assert MetricsService.get_user_metrics(user)["period"]["start"].day == 1

    def test_by_company_and_category(self, user, client_entity):
        cat = DocumentCategoryFactory(client=client_entity, name="Oficina")
        a = CompanyFactory(client=client_entity, name="Acme")
        DocumentFactory(client=client_entity, company=a, status="approved", flow="out", category=cat, base_amount=Decimal("50"))
        DocumentFactory(client=client_entity, company=a, status="approved", flow="out", base_amount=Decimal("25"))
        charts = metrics(user)["charts"]
        assert charts["by_company"][0]["name"] == "Acme"
        assert charts["by_company"][0]["expense"] == 75.0
        names = {c["name"]: c["expense"] for c in charts["by_category"]}
        assert names == {"Oficina": 50.0, "Sin asignar": 25.0}

    def test_by_quarter(self, user, client_entity):
        make(client_entity, flow="out", issue_date=date(2026, 2, 1), base_amount=Decimal("10"), tax_amount=Decimal("2"))
        make(client_entity, flow="in", issue_date=date(2026, 5, 1), base_amount=Decimal("40"), tax_amount=Decimal("8"))
        q = {r["period"]: r for r in metrics(user)["charts"]["by_quarter"]}
        assert q["2026-T1"]["expense"] == 10.0 and q["2026-T1"]["vat_paid"] == 2.0
        assert q["2026-T2"]["income"] == 40.0 and q["2026-T2"]["vat_collected"] == 8.0

    def test_withholding_with_sign(self, user, client_entity):
        d = make(client_entity, flow="out")
        TaxBreakdownFactory(document=d, kind="withholding", rate=Decimal("15"), amount=Decimal("15"))
        r = make(client_entity, flow="out", document_type="corrected_invoice")
        TaxBreakdownFactory(document=r, kind="withholding", rate=Decimal("15"), amount=Decimal("5"))
        assert metrics(user)["financials"]["documents"]["withholding"]["applied"] == 10.0

    def test_other_tenant_excluded(self, user, other_client_entity):
        make(other_client_entity, flow="out", base_amount=Decimal("999"))
        assert metrics(user)["financials"]["documents"]["expense"] == 0.0

    def test_dashboard_view_tolerates_bad_dates(self, auth_client):
        r = auth_client.get("/metrics/dashboard/", {"start": "xx", "end": "2026-99-99"})
        assert r.status_code == 200


class TestExport:
    def csv_rows(self, qs):
        content = export_to_csv(qs).content.decode()
        return list(csv.reader(io.StringIO(content)))

    def test_empty_queryset(self):
        rows = self.csv_rows(Document.all_objects.none())
        assert rows[0][0] == "Fecha" and rows[-1][0] == "Totales"
        assert export_to_excel(Document.all_objects.none()).status_code == 200

    def test_document_without_company_or_amounts(self, client_entity):
        d = make(client_entity, company=None, base_amount=None, tax_amount=None, total_amount=None, issue_date=None)
        rows = self.csv_rows(Document.all_objects.filter(pk=d.pk))
        assert rows[1][3] == "" and rows[-1][-1] == "0"

    def test_corrected_exported_negative_and_totals(self, client_entity):
        make(client_entity, base_amount=Decimal("100"), tax_amount=Decimal("21"), total_amount=Decimal("121"))
        make(client_entity, document_type="corrected_invoice", base_amount=Decimal("10"),
             tax_amount=Decimal("2.1"), total_amount=Decimal("12.1"))
        rows = self.csv_rows(Document.all_objects.filter(client=client_entity))
        assert Decimal(rows[-1][5]) == 90 and Decimal(rows[-1][-1]) == Decimal("108.9")

    def test_withholding_column(self, client_entity):
        d = make(client_entity, total_amount=Decimal("106"))
        TaxBreakdownFactory(document=d, kind="withholding", rate=Decimal("15"), amount=Decimal("15"))
        rows = self.csv_rows(Document.all_objects.filter(pk=d.pk))
        assert rows[1][8] == "15.00"

    @pytest.mark.parametrize("raw", ["=SUM(A1)", "+1", "-1+1", "@cmd", "\tx"])
    def test_formula_injection_neutralized(self, raw):
        assert sanitize_cell(raw).startswith("'")

    def test_numbers_and_normal_text_untouched(self):
        assert sanitize_cell(Decimal("-5")) == Decimal("-5")
        assert sanitize_cell("Acme SL") == "Acme SL"

    def test_malicious_company_name_in_csv_and_xlsx(self, client_entity):
        from openpyxl import load_workbook
        d = make(client_entity, company__name="=HYPERLINK(\"http://x\")")
        qs = Document.all_objects.filter(pk=d.pk)
        assert self.csv_rows(qs)[1][3].startswith("'=")
        ws = load_workbook(io.BytesIO(export_to_excel(qs).content)).active
        assert ws.cell(row=2, column=4).value.startswith("'=")
