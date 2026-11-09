from datetime import date
from decimal import Decimal as D

import pytest

from documents.services.extraction.normalize import (
    compute_flow, normalize, normalize_tax_id, parse_amount, parse_date,
)
from documents.services.extraction.schemas import Party
from documents.tests.fakes import make_result


@pytest.mark.parametrize("raw,expected", [
    ("1234.56", D("1234.56")), ("1.234,56", D("1234.56")), ("1,234.56", D("1234.56")),
    ("12,5", D("12.5")), ("12.5", D("12.5")), ("1.234", D("1234")), ("1,234", D("1234")),
    ("1.234.567", D("1234567")), ("€ 99,90", D("99.90")), ("99.90 EUR", D("99.90")),
    ("-15.00", D("-15.00")), ("(15.00)", D("-15.00")), ("0", D("0")), (" 21 ", D("21")),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "abc", "€", "--"])
def test_parse_amount_invalid(raw):
    assert parse_amount(raw) is None


def test_parse_date():
    assert parse_date("2026-03-15") == date(2026, 3, 15)
    assert parse_date("15/03/2026") is None
    assert parse_date("2026-02-30") is None
    assert parse_date(None) is None


def test_normalize_tax_id():
    assert normalize_tax_id(" b-123.456 78 ") == "B12345678"
    assert normalize_tax_id("ESB12345678") == "B12345678"
    assert normalize_tax_id("") is None and normalize_tax_id(None) is None


class TestFlow:
    def test_client_is_issuer_is_income(self):
        assert compute_flow("B1", "A2", "B1") == "in"

    def test_client_is_recipient_is_expense(self):
        assert compute_flow("B1", "A2", "a-2") == "out"

    def test_neither_or_no_client_nif(self):
        assert compute_flow("B1", "A2", "Z9") == "unknown"
        assert compute_flow("B1", "A2", "") == "unknown"
        assert compute_flow(None, None, "B1") == "unknown"


class TestNormalize:
    def test_expense_invoice(self):
        n = normalize(make_result(), client_tax_id="A87654321")
        assert n.flow == "out"
        assert (n.counterparty_name, n.counterparty_tax_id) == ("Proveedor SL", "B12345678")
        assert n.document_type == "invoice" and n.currency == "EUR"
        assert (n.base_amount, n.total_amount) == (D("100.00"), D("121.00"))
        assert n.tax_lines[0].rate == D("21") and n.tax_lines[0].amount == D("21.00")
        assert n.issue_date == date(2026, 3, 15)

    def test_income_invoice_counterparty_is_recipient(self):
        n = normalize(make_result(), client_tax_id="B12345678")
        assert n.flow == "in"
        assert n.counterparty_tax_id == "A87654321"

    def test_flow_is_not_taken_from_model(self):
        n = normalize(make_result(), client_tax_id=None)
        assert n.flow == "unknown" and n.counterparty_tax_id == "B12345678"

    def test_type_mapping(self):
        assert normalize(make_result(document_type="credit_note")).document_type == "corrected_invoice"
        assert normalize(make_result(document_type="delivery_note")).document_type == "delivery"
        assert normalize(make_result(document_type="receipt")).document_type == "receipt"
        assert normalize(make_result(document_type="quote")).document_type == "quote"
        n = normalize(make_result(document_type="other"))
        assert n.document_type is None and n.kind == "other"

    def test_missing_and_garbage_values(self):
        n = normalize(make_result(
            issue_date="mañana", base_amount=None, total_amount="n/a", currency=None,
            document_number="  ", iban="es91 2100 0418 4502 0005 1332",
        ))
        assert n.issue_date is None and n.base_amount is None and n.total_amount is None
        assert n.currency == "EUR" and n.document_number is None
        assert n.iban == "ES9121000418450200051332"

    def test_confidence_is_clamped_and_exposed_in_legacy_format(self):
        r = make_result()
        r.confidence.overall = 1.7
        r.confidence.date = -0.2
        n = normalize(r)
        assert n.confidence_global == 1.0 and n.confidence["date"] == 0.0
        assert n.legacy_confidence() == {"confianza_extraccion": 1.0, "fecha": 0.0, "total": 0.95}

    def test_withholding_stays_positive_and_lines_are_numbered(self):
        from documents.services.extraction.schemas import Line, TaxLine
        r = make_result(
            tax_lines=[TaxLine(kind="vat", rate="21", base="1000", amount="210"),
                       TaxLine(kind="withholding", rate="15", base="1000", amount="150")],
            lines=[Line(description="a", quantity="2", unit_price="500,00", tax_rate="21", amount="1.000,00")],
        )
        n = normalize(r)
        assert [t.kind for t in n.tax_lines] == ["vat", "withholding"]
        assert n.tax_lines[1].amount == D("150")
        assert n.lines[0].position == 1 and n.lines[0].amount == D("1000.00") and n.lines[0].unit_price == D("500.00")
