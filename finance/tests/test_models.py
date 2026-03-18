from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from finance.models import FinancialMovement


@pytest.mark.django_db
class TestFinanceModels:
    def test_movement_category_string_representation(self, movement_category):
        assert str(movement_category) == "ACME - Ventas"

    def test_financial_movement_save_uses_category_type_and_receipt_name(self, client_entity, user, expense_category):
        movement = FinancialMovement.objects.create(
            client=client_entity,
            movement_type="income",
            created_by=user,
            category=expense_category,
            description="Compra material",
            amount=Decimal("50.00"),
            receipt=SimpleUploadedFile("ticket.pdf", b"pdf", content_type="application/pdf"),
            payment_method="cash",
            date="2026-03-10",
        )

        assert movement.movement_type == "expense"
        assert movement.receipt_name == "ticket.pdf"
        assert movement.has_receipt is True
        assert movement.has_payment_method is True
        assert movement.payment_icon() == "fa-money-bill-wave"
