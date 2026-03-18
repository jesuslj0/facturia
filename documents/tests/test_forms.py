from decimal import Decimal

import pytest

from documents.forms import DocumentRectificationForm


@pytest.mark.django_db
class TestDocumentRectificationForm:
    def test_form_currently_rejects_decimal_strings_with_comma(self, company):
        form = DocumentRectificationForm(
            data={
                "base_amount": "100,50",
                "tax_amount": "21,11",
                "tax_percentage": "21,00",
                "total_amount": "121,61",
                "issue_date": "2026-03-10",
                "document_number": "INV-1",
                "company": company.pk,
                "rectification_reason": "Dato mal OCR",
            }
        )

        assert form.is_valid() is False
        assert "base_amount" in form.errors

    def test_form_accepts_standard_decimal_strings(self, company):
        form = DocumentRectificationForm(
            data={
                "base_amount": "100.50",
                "tax_amount": "21.11",
                "tax_percentage": "21.00",
                "total_amount": "121.61",
                "issue_date": "2026-03-10",
                "document_number": "INV-1",
                "company": company.pk,
                "rectification_reason": "Dato mal OCR",
            }
        )

        assert form.is_valid() is True
        assert form.cleaned_data["base_amount"] == Decimal("100.50")
        assert form.cleaned_data["tax_amount"] == Decimal("21.11")

    def test_form_requires_rectification_reason(self):
        form = DocumentRectificationForm(
            data={
                "base_amount": "100.00",
                "tax_amount": "21.00",
                "tax_percentage": "21.00",
                "total_amount": "121.00",
                "issue_date": "2026-03-10",
                "document_number": "INV-1",
            }
        )

        assert form.is_valid() is False
        assert "rectification_reason" in form.errors
