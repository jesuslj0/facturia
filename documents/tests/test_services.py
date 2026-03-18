from datetime import date
from decimal import Decimal

import pytest

from documents.services.documents_service import DocumentService
from documents.services.metrics_service import MetricsService


@pytest.mark.django_db
class TestDocumentService:
    def test_approve_reject_archive_unarchive_delegate_to_model(self, document, user):
        DocumentService.approve(document, user=user)
        document.refresh_from_db()
        assert document.status == "approved"

        DocumentService.archive(document, user=user)
        document.refresh_from_db()
        assert document.is_archived is True

        DocumentService.unarchive(document, user=user)
        document.refresh_from_db()
        assert document.is_archived is False

    def test_reject_sets_reason(self, document, user):
        DocumentService.reject(document, user=user, reason="Duplicado")
        document.refresh_from_db()

        assert document.status == "rejected"
        assert document.rejection_reason == "Duplicado"

    def test_update_from_form_updates_numeric_fields_and_review_metadata(self, document, user):
        DocumentService.update_from_form(
            document=document,
            user=user,
            data={
                "document_number": "INV-999",
                "issue_date": date(2026, 3, 15),
                "base_amount": "1.234,56",
                "tax_percentage": "21",
                "tax_amount": "259,26",
                "total_amount": "1.493,82",
                "flow": "out",
            },
        )
        document.refresh_from_db()

        assert document.document_number == "INV-999"
        assert document.base_amount == Decimal("1234.56")
        assert document.tax_amount == Decimal("259.26")
        assert document.total_amount == Decimal("1493.82")
        assert document.flow == "out"
        assert document.review_level == "manual"
        assert document.reviewed_by == user

    def test_update_from_form_raises_for_invalid_amounts(self, document, user):
        with pytest.raises(ValueError, match="Importe inválido"):
            DocumentService.update_from_form(document=document, user=user, data={"base_amount": "abc"})

    def test_rectify_returns_new_version(self, approved_document, user):
        rectified = DocumentService.rectify(
            document=approved_document,
            user=user,
            reason="Ajuste IVA",
            form_data={"tax_amount": Decimal("40.00"), "total_amount": Decimal("140.00")},
        )

        assert rectified.pk != approved_document.pk
        assert rectified.version == 2
        assert rectified.rectification_reason == "Ajuste IVA"


@pytest.mark.django_db
class TestMetricsService:
    def test_get_user_metrics_aggregates_documents_and_financial_movements(
        self,
        user,
        approved_document,
        document,
        financial_movement,
        expense_category,
    ):
        approved_document.flow = "in"
        approved_document.base_amount = Decimal("100.00")
        approved_document.tax_amount = Decimal("21.00")
        approved_document.total_amount = Decimal("121.00")
        approved_document.review_level = "auto"
        approved_document.is_auto_approved = True
        approved_document.save()

        document.status = "rejected"
        document.review_level = "required"
        document.save()

        from finance.models import FinancialMovement
        FinancialMovement.objects.create(
            client=user.client,
            movement_type="expense",
            created_by=user,
            category=expense_category,
            description="Compra",
            amount=Decimal("100.00"),
            payment_method="cash",
            is_active=True,
            date=date(2026, 3, 11),
        )

        metrics = MetricsService.get_user_metrics(user=user, start=date(2026, 3, 1), end=date(2026, 3, 31))

        assert metrics["documents"]["total"] == 2
        assert metrics["documents"]["approved"] == 1
        assert metrics["documents"]["rejected"] == 1
        assert metrics["financials"]["documents"]["income"] == 100.0
        assert metrics["financials"]["movements"]["income"] == 500.0
        assert metrics["financials"]["movements"]["expense"] == 100.0
        assert metrics["status_distribution"]["auto_approved"] == 1

    def test_get_historical_metrics_handles_empty_dataset(self, user):
        metrics = MetricsService.get_historical_metrics(user)

        assert metrics == {
            "total": 0,
            "approved": 0,
            "rejected": 0,
            "pending": 0,
            "approval_rate": 0,
            "first_document_date": None,
        }
