import pytest

from finance.forms import FinancialMovementForm


@pytest.mark.django_db
class TestFinancialMovementForm:
    def test_form_limits_categories_to_client(self, client_entity, other_client_entity, movement_category):
        from finance.models import MovementCategory

        foreign_category = MovementCategory.objects.create(client=other_client_entity, name="Foreign", type="income")
        form = FinancialMovementForm(client=client_entity)

        assert list(form.fields["category"].queryset) == [movement_category]
        assert foreign_category not in form.fields["category"].queryset

    def test_form_without_client_has_empty_category_queryset(self):
        form = FinancialMovementForm()

        assert form.fields["category"].queryset.count() == 0
