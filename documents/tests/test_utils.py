"""
Tests for documents/utils.py — pure utility functions that have no existing coverage:
- parse_decimal
- round_decimal
- normalize_tax
- build_pdf_context (light check)
- export_to_csv / export_to_excel response headers
"""
from decimal import Decimal, InvalidOperation

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from documents.utils import (
    parse_decimal,
    round_decimal,
    normalize_tax,
    build_pdf_context,
    export_to_csv,
    export_to_excel,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# parse_decimal
# ---------------------------------------------------------------------------

class TestParseDecimal:
    def test_parses_plain_integer_string(self):
        assert parse_decimal("100") == Decimal("100")

    def test_parses_dot_decimal(self):
        assert parse_decimal("100.50") == Decimal("100.50")

    def test_parses_comma_decimal(self):
        assert parse_decimal("100,50") == Decimal("100.50")

    def test_parses_spanish_thousand_separator(self):
        # "1.234,56" → 1234.56
        assert parse_decimal("1.234,56") == Decimal("1234.56")

    def test_returns_none_for_empty_string(self):
        assert parse_decimal("") is None

    def test_returns_none_for_none(self):
        assert parse_decimal(None) is None

    def test_parses_decimal_object_directly(self):
        result = parse_decimal(Decimal("42.00"))
        assert result == Decimal("42.00")

    def test_raises_for_non_numeric_string(self):
        with pytest.raises((InvalidOperation, Exception)):
            parse_decimal("abc")


# ---------------------------------------------------------------------------
# round_decimal
# ---------------------------------------------------------------------------

class TestRoundDecimal:
    def test_rounds_to_two_places_by_default(self):
        assert round_decimal(Decimal("1.555"), 2) == Decimal("1.56")

    def test_rounds_to_four_places(self):
        assert round_decimal(Decimal("0.95001"), 4) == Decimal("0.9500")

    def test_returns_none_for_none_input(self):
        assert round_decimal(None) is None

    def test_accepts_float_input(self):
        result = round_decimal(0.95, 2)
        assert result == Decimal("0.95")


# ---------------------------------------------------------------------------
# normalize_tax
# ---------------------------------------------------------------------------

class TestNormalizeTax:
    def test_returns_all_four_values_when_all_provided(self):
        result = normalize_tax(100, 21, 21, 121)
        assert result["base"] == Decimal("100.00")
        assert result["tax_amount"] == Decimal("21.00")
        assert result["tax_percentage"] == Decimal("21.00")
        assert result["total"] == Decimal("121.00")

    def test_infers_tax_amount_from_base_and_percentage(self):
        result = normalize_tax(100, 0, 21, 121)
        assert result["tax_amount"] == Decimal("21.00")

    def test_infers_tax_percentage_from_base_and_tax_amount(self):
        result = normalize_tax(100, 21, 0, 121)
        assert result["tax_percentage"] == Decimal("21.00")

    def test_infers_total_from_base_and_tax(self):
        result = normalize_tax(100, 21, 21, 0)
        assert result["total"] == Decimal("121.00")

    def test_all_none_returns_none_values(self):
        result = normalize_tax(None, None, None, None)
        assert result["base"] is None
        assert result["tax_amount"] is None

    def test_does_not_overwrite_existing_total(self):
        result = normalize_tax(100, 21, 21, 200)
        # total already provided — should NOT be overwritten
        assert result["total"] == Decimal("200.00")


# ---------------------------------------------------------------------------
# export_to_csv
# ---------------------------------------------------------------------------

class TestExportToCsv:
    def test_csv_response_has_correct_content_type(self, approved_document):
        from documents.models import Document
        qs = Document.all_objects.filter(pk=approved_document.pk)
        response = export_to_csv(qs)

        assert response["Content-Type"] == "text/csv"
        assert "documentos.csv" in response["Content-Disposition"]

    def test_csv_contains_header_row(self, approved_document):
        from documents.models import Document
        qs = Document.all_objects.filter(pk=approved_document.pk)
        response = export_to_csv(qs)
        content = response.content.decode("utf-8")

        assert "Número documento" in content
        assert "Total" in content

    def test_csv_contains_document_data(self, approved_document):
        from documents.models import Document
        qs = Document.all_objects.filter(pk=approved_document.pk)
        response = export_to_csv(qs)
        content = response.content.decode("utf-8")

        assert approved_document.document_number in content
        assert str(approved_document.total_amount) in content


# ---------------------------------------------------------------------------
# export_to_excel
# ---------------------------------------------------------------------------

class TestExportToExcel:
    def test_excel_response_has_correct_content_type(self, approved_document):
        from documents.models import Document
        qs = Document.all_objects.filter(pk=approved_document.pk)
        response = export_to_excel(qs)

        assert "spreadsheetml" in response["Content-Type"]
        assert "documentos.xlsx" in response["Content-Disposition"]

    def test_excel_response_content_is_not_empty(self, approved_document):
        from documents.models import Document
        qs = Document.all_objects.filter(pk=approved_document.pk)
        response = export_to_excel(qs)
        assert len(response.content) > 0


# ---------------------------------------------------------------------------
# build_pdf_context
# ---------------------------------------------------------------------------

class TestBuildPdfContext:
    def test_context_contains_expected_keys(self, approved_document, rf, user):
        from documents.models import Document
        request = rf.get("/export/")
        request.user = user
        qs = Document.all_objects.filter(pk=approved_document.pk)

        context = build_pdf_context(qs, request)

        assert "invoices" in context
        assert "client" in context
        assert "date" in context
        assert "totals" in context

    def test_totals_aggregate_matches_document(self, approved_document, rf, user):
        from documents.models import Document
        request = rf.get("/export/")
        request.user = user
        qs = Document.all_objects.filter(pk=approved_document.pk)

        context = build_pdf_context(qs, request)

        assert context["totals"]["count"] == 1
        assert context["totals"]["total"] == approved_document.total_amount
