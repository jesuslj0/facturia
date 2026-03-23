"""
Extended finance tests covering:
- FinancialMovement CRUD scoping + multi-tenancy
- FinancialMovement model edge cases (payment icons, missing category)
- Finance filters (get_filtered_movements with each filter param)
- MovementCategory uniqueness per client
- Dashboard view finance aggregates
- Finance views isolation: user from client A cannot touch client B movements
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from finance.models import FinancialMovement, MovementCategory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# FinancialMovement model — edge cases
# ---------------------------------------------------------------------------

class TestFinancialMovementModel:
    def test_movement_type_overridden_by_category_on_save(
        self, client_entity, user, expense_category
    ):
        movement = FinancialMovement.objects.create(
            client=client_entity,
            movement_type="income",   # intentionally wrong
            created_by=user,
            category=expense_category,
            description="Override test",
            amount=Decimal("10.00"),
            payment_method="cash",
            date=date(2026, 3, 10),
        )
        assert movement.movement_type == "expense"

    def test_receipt_name_populated_from_file(self, client_entity, user, movement_category):
        receipt = SimpleUploadedFile("recibo.pdf", b"r", content_type="application/pdf")
        movement = FinancialMovement.objects.create(
            client=client_entity,
            movement_type="income",
            created_by=user,
            category=movement_category,
            description="With receipt",
            amount=Decimal("20.00"),
            receipt=receipt,
            date=date(2026, 3, 11),
        )
        assert movement.receipt_name == "recibo.pdf"
        assert movement.has_receipt is True

    def test_has_receipt_false_when_no_file(self, financial_movement):
        assert financial_movement.has_receipt is False

    def test_has_payment_method_false_when_null(self, client_entity, user, movement_category):
        movement = FinancialMovement.objects.create(
            client=client_entity,
            movement_type="income",
            created_by=user,
            category=movement_category,
            description="No method",
            amount=Decimal("5.00"),
            payment_method=None,
            date=date(2026, 3, 12),
        )
        assert movement.has_payment_method is False

    def test_payment_icon_all_methods(self, client_entity, user, movement_category):
        expected = {
            "cash": "fa-money-bill-wave",
            "transfer": "fa-building-columns",
            "check": "fa-file-invoice-dollar",
            "credit_card": "fa-credit-card",
            "debit_card": "fa-credit-card",
            "bizum": "fa-mobile-screen",
        }
        for method, icon in expected.items():
            m = FinancialMovement(
                client=client_entity,
                category=movement_category,
                movement_type="income",
                amount=Decimal("1.00"),
                payment_method=method,
                date=date(2026, 3, 10),
            )
            assert m.payment_icon() == icon, f"Wrong icon for method {method}"

    def test_payment_icon_returns_none_for_unknown_method(self, financial_movement):
        financial_movement.payment_method = "crypto"
        assert financial_movement.payment_icon() is None

    def test_str_representation(self, financial_movement):
        expected = f"{financial_movement.category.name} - {financial_movement.amount} ({financial_movement.date})"
        assert str(financial_movement) == expected


# ---------------------------------------------------------------------------
# MovementCategory model
# ---------------------------------------------------------------------------

class TestMovementCategoryModel:
    def test_category_unique_per_client_name_type(self, client_entity, movement_category):
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            MovementCategory.objects.create(
                client=client_entity,
                name=movement_category.name,
                type=movement_category.type,
            )

    def test_same_name_allowed_for_different_clients(
        self, client_entity, other_client_entity
    ):
        MovementCategory.objects.create(
            client=client_entity, name="Shared", type="income"
        )
        cat2 = MovementCategory.objects.create(
            client=other_client_entity, name="Shared", type="income"
        )
        assert cat2.pk is not None


# ---------------------------------------------------------------------------
# Finance views — multi-tenancy: client B cannot touch client A movement
# ---------------------------------------------------------------------------

class TestFinanceViewsMultiTenancy:
    def test_edit_other_client_movement_returns_404(
        self, auth_client, other_client_entity, other_user, movement_category
    ):
        foreign_category = MovementCategory.objects.create(
            client=other_client_entity, name="Foreign Cat", type="income"
        )
        foreign_movement = FinancialMovement.objects.create(
            client=other_client_entity,
            movement_type="income",
            created_by=other_user,
            category=foreign_category,
            description="Foreign",
            amount=Decimal("99.00"),
            date=date(2026, 3, 10),
        )

        response = auth_client.post(
            reverse("finance:edit_movement", kwargs={"pk": foreign_movement.pk}),
            data={
                "category": movement_category.pk,
                "amount": "200.00",
                "date": "2026-03-10",
                "description": "Hijacked",
                "is_active": "on",
            },
        )
        assert response.status_code == 404
        foreign_movement.refresh_from_db()
        assert foreign_movement.description == "Foreign"

    def test_delete_other_client_movement_returns_404(
        self, auth_client, other_client_entity, other_user
    ):
        foreign_category = MovementCategory.objects.create(
            client=other_client_entity, name="ForeignDel", type="expense"
        )
        foreign_movement = FinancialMovement.objects.create(
            client=other_client_entity,
            movement_type="expense",
            created_by=other_user,
            category=foreign_category,
            description="ToDelete",
            amount=Decimal("50.00"),
            date=date(2026, 3, 10),
        )

        response = auth_client.post(
            reverse("finance:delete_movement", kwargs={"pk": foreign_movement.pk})
        )
        assert response.status_code == 404
        assert FinancialMovement.objects.filter(pk=foreign_movement.pk).exists()


# ---------------------------------------------------------------------------
# Finance views — category list scoping
# ---------------------------------------------------------------------------

class TestCategoryListView:
    def test_category_list_shows_only_own_client_categories(
        self, auth_client, movement_category, other_client_entity
    ):
        MovementCategory.objects.create(
            client=other_client_entity, name="Foreign Category", type="income"
        )

        response = auth_client.get(reverse("finance:categories"))
        assert response.status_code == 200
        object_list = list(response.context["object_list"])
        assert movement_category in object_list
        assert all(c.client == movement_category.client for c in object_list)

    def test_category_list_requires_login(self, client):
        response = client.get(reverse("finance:categories"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Finance filters — get_filtered_movements
# ---------------------------------------------------------------------------

class TestGetFilteredMovements:
    """Test the movement filter function by going through the list view URL."""

    def test_filter_by_query_matches_description(
        self, auth_client, financial_movement
    ):
        response = auth_client.get(
            reverse("finance:movements"), {"q": "Cobro factura"}
        )
        assert response.status_code == 200
        assert financial_movement in list(response.context["movements"])

    def test_filter_by_query_no_match_returns_empty(
        self, auth_client, financial_movement
    ):
        response = auth_client.get(
            reverse("finance:movements"), {"q": "zzznoexiste"}
        )
        assert financial_movement not in list(response.context["movements"])

    def test_filter_by_date_range_includes_matching(
        self, auth_client, financial_movement
    ):
        response = auth_client.get(
            reverse("finance:movements"),
            {"start": "2026-03-01", "end": "2026-03-31"},
        )
        assert financial_movement in list(response.context["movements"])

    def test_filter_by_date_range_excludes_outside(
        self, auth_client, financial_movement
    ):
        response = auth_client.get(
            reverse("finance:movements"),
            {"start": "2026-04-01", "end": "2026-04-30"},
        )
        assert financial_movement not in list(response.context["movements"])

    def test_filter_by_payment_method(self, auth_client, financial_movement):
        response = auth_client.get(
            reverse("finance:movements"), {"method": "transfer"}
        )
        assert financial_movement in list(response.context["movements"])

        response_bad = auth_client.get(
            reverse("finance:movements"), {"method": "cash"}
        )
        assert financial_movement not in list(response_bad.context["movements"])

    def test_filter_by_category(self, auth_client, financial_movement, movement_category):
        response = auth_client.get(
            reverse("finance:movements"),
            {"category": str(movement_category.pk)},
        )
        assert financial_movement in list(response.context["movements"])

    def test_filter_is_reconciled(self, auth_client, financial_movement):
        # movement is not reconciled — should not appear
        response_yes = auth_client.get(
            reverse("finance:movements"), {"is_reconciled": "1"}
        )
        assert financial_movement not in list(response_yes.context["movements"])

    def test_filter_min_amount(self, auth_client, financial_movement):
        response_pass = auth_client.get(
            reverse("finance:movements"), {"min_amount": "400"}
        )
        assert financial_movement in list(response_pass.context["movements"])

        response_fail = auth_client.get(
            reverse("finance:movements"), {"min_amount": "600"}
        )
        assert financial_movement not in list(response_fail.context["movements"])

    def test_filter_max_amount(self, auth_client, financial_movement):
        response_pass = auth_client.get(
            reverse("finance:movements"), {"max_amount": "600"}
        )
        assert financial_movement in list(response_pass.context["movements"])

        response_fail = auth_client.get(
            reverse("finance:movements"), {"max_amount": "100"}
        )
        assert financial_movement not in list(response_fail.context["movements"])


# ---------------------------------------------------------------------------
# Finance views — form validation
# ---------------------------------------------------------------------------

class TestFinanceViewFormValidation:
    def test_create_movement_with_invalid_amount_shows_form_errors(
        self, auth_client, movement_category
    ):
        response = auth_client.post(
            reverse("finance:new_movement"),
            data={
                "category": movement_category.pk,
                "amount": "not-a-number",
                "date": "2026-03-12",
                "description": "Invalid amount",
                "is_active": "on",
            },
        )
        # Should re-render form (200) with errors
        assert response.status_code == 200
        assert response.context["form"].errors

    def test_create_movement_with_missing_date_shows_form_errors(
        self, auth_client, movement_category
    ):
        response = auth_client.post(
            reverse("finance:new_movement"),
            data={
                "category": movement_category.pk,
                "amount": "100.00",
                "date": "",
                "description": "No date",
                "is_active": "on",
            },
        )
        assert response.status_code == 200
        assert "date" in response.context["form"].errors

    def test_update_movement_with_category_from_other_client_rejected(
        self, auth_client, financial_movement, other_client_entity
    ):
        foreign_cat = MovementCategory.objects.create(
            client=other_client_entity, name="ForeignCat2", type="income"
        )
        response = auth_client.post(
            reverse("finance:edit_movement", kwargs={"pk": financial_movement.pk}),
            data={
                "category": foreign_cat.pk,  # foreign category
                "amount": "99.00",
                "date": "2026-03-10",
                "description": "Update with foreign cat",
                "is_active": "on",
            },
        )
        # Form should fail validation (category not in queryset)
        assert response.status_code == 200
        assert response.context["form"].errors


# ---------------------------------------------------------------------------
# Dashboard view — finance aggregates shown in context
# ---------------------------------------------------------------------------

class TestDashboardView:
    def test_dashboard_requires_login(self, client):
        response = client.get(reverse("dashboard"))
        assert response.status_code == 302

    def test_dashboard_shows_finance_balance(
        self, auth_client, financial_movement
    ):
        response = auth_client.get(reverse("dashboard"))
        assert response.status_code == 200
        # Context should have finance keys
        assert "finance_income_total" in response.context
        assert "finance_expense_total" in response.context
        assert "finance_balance" in response.context

    def test_dashboard_counts_pending_documents(self, auth_client, document):
        response = auth_client.get(reverse("dashboard"))
        assert response.status_code == 200
        assert response.context["pending_count"] >= 1
