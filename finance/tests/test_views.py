from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from finance.models import FinancialMovement, MovementCategory


@pytest.mark.django_db
class TestFinanceViews:
    def test_movement_list_requires_login(self, client):
        response = client.get(reverse("finance:movements"))

        assert response.status_code == 302

    def test_movement_list_is_scoped_to_user_client(self, auth_client, financial_movement, other_client_entity, other_user):
        foreign_category = MovementCategory.objects.create(client=other_client_entity, name="Foreign", type="income")
        FinancialMovement.objects.create(
            client=other_client_entity,
            movement_type="income",
            created_by=other_user,
            category=foreign_category,
            description="Other",
            amount=Decimal("10.00"),
            date="2026-03-10",
        )

        response = auth_client.get(reverse("finance:movements"))

        assert response.status_code == 200
        assert list(response.context["movements"]) == [financial_movement]

    def test_create_movement_sets_client_and_creator(self, auth_client, movement_category):
        response = auth_client.post(
            reverse("finance:new_movement"),
            data={
                "category": movement_category.pk,
                "amount": "99.99",
                "date": "2026-03-12",
                "description": "Nuevo cobro",
                "payment_method": "transfer",
                "is_recurrent": "",
                "is_active": "on",
                "is_reconciled": "",
            },
            follow=True,
        )

        movement = FinancialMovement.objects.get(description="Nuevo cobro")
        messages = [m.message for m in get_messages(response.wsgi_request)]
        assert movement.client == response.wsgi_request.user.client
        assert movement.created_by == response.wsgi_request.user
        assert any("creado correctamente" in message for message in messages)

    def test_update_movement_keeps_scoping_and_updates_record(self, auth_client, financial_movement, movement_category):
        response = auth_client.post(
            reverse("finance:edit_movement", kwargs={"pk": financial_movement.pk}),
            data={
                "category": movement_category.pk,
                "amount": "750.00",
                "date": "2026-03-10",
                "description": "Cobro actualizado",
                "payment_method": "bizum",
                "is_active": "on",
                "is_reconciled": "on",
            },
            follow=True,
        )

        financial_movement.refresh_from_db()
        messages = [m.message for m in get_messages(response.wsgi_request)]
        assert financial_movement.description == "Cobro actualizado"
        assert financial_movement.amount == Decimal("750.00")
        assert any("actualizado correctamente" in message for message in messages)

    def test_delete_movement_removes_record(self, auth_client, financial_movement):
        response = auth_client.post(reverse("finance:delete_movement", kwargs={"pk": financial_movement.pk}), follow=True)

        messages = [m.message for m in get_messages(response.wsgi_request)]
        assert FinancialMovement.objects.filter(pk=financial_movement.pk).exists() is False
        assert any("borrado correctamente" in message for message in messages)

    def test_category_views_create_update_delete(self, auth_client):
        create_response = auth_client.post(
            reverse("finance:new_category"),
            data={"name": "Servicios", "type": "expense", "color": "#123456", "icon": "fa-wrench"},
            follow=True,
        )
        category = MovementCategory.objects.get(name="Servicios")
        assert create_response.status_code == 200

        update_response = auth_client.post(
            reverse("finance:edit_category", kwargs={"pk": category.pk}),
            data={"name": "Servicios IT", "type": "expense", "color": "#654321", "icon": "fa-server"},
            follow=True,
        )
        category.refresh_from_db()
        assert category.name == "Servicios IT"
        assert update_response.status_code == 200

        delete_response = auth_client.post(reverse("finance:delete_category", kwargs={"pk": category.pk}), follow=True)
        assert delete_response.status_code == 200
        assert MovementCategory.objects.filter(pk=category.pk).exists() is False
