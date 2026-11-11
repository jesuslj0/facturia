from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from documents.services import validation as v
from documents.services.extraction.normalize import normalize
from documents.services.extraction.schemas import Party, TaxLine
from documents.tests import factories as f
from documents.tests.fakes import make_result

pytestmark = pytest.mark.django_db
TODAY = date(2026, 6, 15)
CLIENT_NIF = "A87654323"   # destinatario de make_result() → gasto


@pytest.fixture
def client():
    return f.ClientFactory(tax_id=CLIENT_NIF)


def issues_for(client, today=TODAY, document=None, **over):
    n = normalize(make_result(**over), client_tax_id=client.tax_id)
    return v.validate(n, client=client, document=document, today=today), n


def codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity == severity}


def test_clean_extraction_has_no_issues(client):
    issues, _ = issues_for(client)
    assert issues == []


class TestAmounts:
    def test_consistent_with_vat_and_withholding(self, client):
        r = dict(base_amount="1000.00", total_amount="1060.00", tax_lines=[
            TaxLine(kind="vat", rate="21", base="1000", amount="210.00"),
            TaxLine(kind="withholding", rate="15", base="1000", amount="150.00")])
        assert issues_for(client, **r)[0] == []

    def test_total_that_ignores_withholding_is_flagged(self, client):
        r = dict(base_amount="1000.00", total_amount="1210.00", tax_lines=[
            TaxLine(kind="vat", rate="21", base="1000", amount="210.00"),
            TaxLine(kind="withholding", rate="15", base="1000", amount="150.00")])
        i, _ = issues_for(client, **r)
        assert "totals_mismatch" in codes(i, v.ERROR)
        assert next(x for x in i if x.code == "totals_mismatch").model_fixable

    def test_cent_rounding_is_tolerated(self, client):
        assert "totals_mismatch" not in codes(issues_for(client, total_amount="121.02")[0])
        assert "totals_mismatch" in codes(issues_for(client, total_amount="121.03")[0])

    def test_wrong_vat_amount_for_rate(self, client):
        i, _ = issues_for(client, tax_lines=[TaxLine(kind="vat", rate="21", base="100.00", amount="25.00")], total_amount="125.00")
        assert "tax_line_mismatch" in codes(i, v.ERROR) and "totals_mismatch" not in codes(i)

    def test_withholding_sign_does_not_matter(self, client):
        r = dict(base_amount="100", total_amount="106", tax_lines=[
            TaxLine(kind="vat", rate="21", base="100", amount="21"), TaxLine(kind="withholding", rate="15", base="100", amount="-15")])
        assert "totals_mismatch" not in codes(issues_for(client, **r)[0])

    def test_missing_total_is_error_except_delivery_notes(self, client):
        i, _ = issues_for(client, total_amount=None)
        assert "missing_total" in codes(i, v.ERROR)
        i, _ = issues_for(client, total_amount=None, document_type="delivery_note")
        assert "missing_total" in codes(i, v.WARNING)

    def test_no_tax_breakdown_but_total_differs_is_flagged(self, client):
        assert "totals_mismatch" in codes(issues_for(client, tax_lines=[], total_amount="121.00")[0])
        assert "totals_mismatch" not in codes(issues_for(client, tax_lines=[], total_amount="100.00")[0])  # exento

    def test_bases_by_rate_must_add_up(self, client):
        r = dict(base_amount="100.00", total_amount="131.00", tax_lines=[
            TaxLine(kind="vat", rate="21", base="60", amount="12.60"), TaxLine(kind="vat", rate="10", base="60", amount="6.00")])
        assert "base_split_mismatch" in codes(issues_for(client, **r)[0], v.WARNING)

    def test_unusual_rates_are_warnings(self, client):
        i, _ = issues_for(client, tax_lines=[TaxLine(kind="vat", rate="19", base="100", amount="19")], total_amount="119")
        assert codes(i) == {"unusual_rate"} and codes(i, v.WARNING) == {"unusual_rate"}
        for rate in ("0", "4", "10", "21", "7.5"):
            amt = str(D("100") * D(rate) / 100)
            assert "unusual_rate" not in codes(issues_for(client, tax_lines=[TaxLine(kind="vat", rate=rate, base="100", amount=amt)], total_amount=str(D("100") + D(amt)))[0])

    def test_non_eur_currency(self, client):
        assert "non_eur_currency" in codes(issues_for(client, currency="usd")[0], v.WARNING)

    def test_negative_amount_ok_for_credit_note_only(self, client):
        neg = dict(base_amount="-100", total_amount="-121", tax_lines=[TaxLine(kind="vat", rate="21", base="-100", amount="-21")])
        assert "negative_amount" not in codes(issues_for(client, document_type="credit_note", **neg)[0])
        assert "negative_amount" in codes(issues_for(client, document_type="invoice", **neg)[0])


class TestDates:
    def test_missing(self, client):
        assert "missing_date" in codes(issues_for(client, issue_date=None)[0], v.ERROR)

    def test_future(self, client):
        i, _ = issues_for(client, issue_date=(TODAY + timedelta(days=30)).isoformat())
        assert "future_date" in codes(i, v.ERROR)

    def test_tomorrow_tolerated_for_timezones(self, client):
        assert "future_date" not in codes(issues_for(client, issue_date=(TODAY + timedelta(days=1)).isoformat())[0])

    def test_implausible_and_old(self, client):
        assert "implausible_date" in codes(issues_for(client, issue_date="1987-01-01")[0], v.ERROR)
        assert "old_date" in codes(issues_for(client, issue_date="2019-01-01")[0], v.WARNING)
        assert "old_date" not in codes(issues_for(client, issue_date="2024-01-01")[0])


class TestTaxIds:
    def test_invalid_issuer_tax_id_is_fixable_error(self, client):
        i, _ = issues_for(client, issuer=Party(name="P", tax_id="B12345678", address=None))  # dígito de control erróneo
        bad = next(x for x in i if x.code == "invalid_tax_id")
        assert bad.severity == v.ERROR and bad.model_fixable and "emisor" in bad.message

    def test_invalid_recipient_tax_id(self, client):
        i, _ = issues_for(client, recipient=Party(name="R", tax_id="A87654321", address=None))
        assert any(x.code == "invalid_tax_id" and "destinatario" in x.message for x in i)

    def test_foreign_tax_id_is_info_only(self, client):
        i, _ = issues_for(client, issuer=Party(name="P", tax_id="FR12345678901", address=None))
        assert codes(i) == {"foreign_tax_id"} and codes(i, v.INFO) == {"foreign_tax_id"}

    def test_missing_issuer_nif_error_for_invoice_warning_for_receipt(self, client):
        no_nif = Party(name="P", tax_id=None, address=None)
        assert "missing_issuer_tax_id" in codes(issues_for(client, issuer=no_nif)[0], v.ERROR)
        assert "missing_issuer_tax_id" in codes(issues_for(client, issuer=no_nif, document_type="receipt")[0], v.WARNING)

    def test_missing_recipient_nif_is_fine(self, client):
        # consumidor final: el cliente es el emisor, el destinatario no tiene NIF
        c = f.ClientFactory(tax_id="B12345674")
        i, n = issues_for(c, recipient=Party(name="Juan", tax_id=None, address=None))
        assert n.flow == "in" and i == []


class TestFlow:
    def test_client_without_nif(self):
        c = f.ClientFactory(tax_id=None)
        i, _ = issues_for(c)
        flow = next(x for x in i if x.code == "flow_unknown")
        assert flow.severity == v.ERROR and not flow.model_fixable and "no tiene NIF" in flow.message

    def test_client_nif_not_in_document(self):
        c = f.ClientFactory(tax_id="B99999990")
        flow = next(x for x in issues_for(c)[0] if x.code == "flow_unknown")
        assert "ni como destinatario" in flow.message


class TestOtherRules:
    def test_unsupported_type(self, client):
        i, _ = issues_for(client, document_type="other")
        assert "unsupported_type" in codes(i, v.ERROR)

    def test_missing_number_warning_for_invoices(self, client):
        assert "missing_document_number" in codes(issues_for(client, document_number=None)[0], v.WARNING)

    def test_duplicate_by_issuer_and_number(self, client):
        co = f.CompanyFactory(client=client, tax_id="B12345674")
        f.DocumentFactory(client=client, company=co, document_number="F-001", flow="out")
        i, _ = issues_for(client)
        dup = next(x for x in i if x.code == "duplicate_document")
        assert dup.severity == v.ERROR and not dup.model_fixable and "F-001" in dup.message

    def test_not_a_duplicate_of_itself_or_other_issuer_or_rejected(self, client):
        co = f.CompanyFactory(client=client, tax_id="B12345674")
        same = f.DocumentFactory(client=client, company=co, document_number="F-001", flow="out")
        assert "duplicate_document" not in codes(issues_for(client, document=same)[0])
        other_co = f.CompanyFactory(client=client, tax_id="A82018474")
        f.DocumentFactory(client=client, company=other_co, document_number="F-002", flow="out")
        assert "duplicate_document" not in codes(issues_for(client, document_number="F-002")[0])
        same.status = "rejected"; same.save()
        assert "duplicate_document" not in codes(issues_for(client)[0])

    def test_duplicates_do_not_cross_tenants(self, client):
        other = f.ClientFactory()
        co = f.CompanyFactory(client=other, tax_id="B12345674")
        f.DocumentFactory(client=other, company=co, document_number="F-001", flow="out")
        assert "duplicate_document" not in codes(issues_for(client)[0])

    def test_own_invoice_series_duplicate(self):
        c = f.ClientFactory(tax_id="B12345674")  # el cliente emite → flow in
        f.DocumentFactory(client=c, document_number="F-001", flow="in")
        assert "duplicate_document" in codes(issues_for(c)[0], v.ERROR)


class TestDecide:
    def _decide(self, client, settings=None, **over):
        i, n = issues_for(client, **over)
        return v.decide(i, n), i

    def test_errors_force_required(self, client):
        d, _ = self._decide(client, total_amount="999")
        assert (d.review_level, d.auto_approve) == ("required", False)

    def test_warning_caps_at_recommended_even_with_high_confidence(self, client, settings):
        settings.EXTRACTION_AUTO_APPROVE = True
        d, _ = self._decide(client, currency="USD")
        assert (d.review_level, d.auto_approve) == ("recommended", False)

    def test_clean_and_confident_is_auto_only_when_enabled(self, client, settings):
        settings.EXTRACTION_AUTO_APPROVE = False
        assert self._decide(client)[0] == v.ReviewDecision("recommended", False)
        settings.EXTRACTION_AUTO_APPROVE = True
        assert self._decide(client)[0] == v.ReviewDecision("auto", True)

    def test_min_confidence_setting(self, client, settings):
        settings.EXTRACTION_AUTO_APPROVE = True
        settings.EXTRACTION_AUTO_APPROVE_MIN_CONFIDENCE = 0.99
        assert self._decide(client)[0].auto_approve is False

    def test_low_confidence_is_required_even_if_valid(self, client, settings):
        settings.EXTRACTION_AUTO_APPROVE = True
        r = make_result(); r.confidence.overall = 0.6
        n = normalize(r, client_tax_id=client.tax_id)
        d = v.decide(v.validate(n, client=client, today=TODAY), n)
        assert (d.review_level, d.auto_approve) == ("required", False)

    def test_info_only_does_not_block_auto(self, client, settings):
        settings.EXTRACTION_AUTO_APPROVE = True
        d, i = self._decide(client, issuer=Party(name="P", tax_id="FR12345678901", address=None))
        assert codes(i) == {"foreign_tax_id"} and d.auto_approve

    def test_fallback_problems_only_model_fixable_errors(self, client):
        i, _ = issues_for(client, total_amount="999", currency="USD")
        assert {x.code for x in v.fallback_problems(i)} == {"totals_mismatch"}
        c2 = f.ClientFactory(tax_id=None)
        assert v.fallback_problems(issues_for(c2)[0]) == []   # solo flow_unknown: Sonnet no ayudaría


def test_issues_serialize_to_json(client):
    i, _ = issues_for(client, total_amount="999")
    data = v.issues_to_json(i)
    assert data[0].keys() == {"code", "severity", "message", "field", "model_fixable"}


def test_credit_note_with_withholding_and_negative_amounts_is_consistent(client):
    r = dict(document_type="credit_note", base_amount="-1000", total_amount="-1060", tax_lines=[
        TaxLine(kind="vat", rate="21", base="-1000", amount="-210"),
        TaxLine(kind="withholding", rate="15", base="-1000", amount="150")])   # retención en positivo
    assert issues_for(client, **r)[0] == []


class TestLinesSum:
    @staticmethod
    def _lines(*amounts):
        from documents.services.extraction.schemas import Line
        return [Line(description=f"l{i}", quantity="1", unit_price=a, tax_rate=None, amount=a, page=1)
                for i, a in enumerate(amounts, start=1)]

    def test_lines_that_add_up_to_base_are_fine(self, client):
        i, _ = issues_for(client, lines=self._lines("60.00", "40.00"))
        assert "lines_sum_mismatch" not in codes(i)

    def test_lines_with_vat_that_add_up_to_total_are_fine(self, client):
        i, _ = issues_for(client, lines=self._lines("60.50", "60.50"))
        assert "lines_sum_mismatch" not in codes(i)

    def test_missing_lines_are_flagged_as_warning(self, client):
        i, _ = issues_for(client, lines=self._lines("30.00", "20.00"))
        assert "lines_sum_mismatch" in codes(i, v.WARNING)
        assert not next(x for x in i if x.code == "lines_sum_mismatch").model_fixable

    def test_single_line_is_not_checked(self, client):
        i, _ = issues_for(client, lines=self._lines("10.00"))
        assert "lines_sum_mismatch" not in codes(i)
