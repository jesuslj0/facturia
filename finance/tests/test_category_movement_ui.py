"""Categorías y formulario de movimiento: listado agrupado, formulario con vista previa y borrado seguro."""
from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from finance.forms import MovementCategoryForm
from finance.models import FinancialMovement, MovementCategory

pytestmark = pytest.mark.django_db


def cat(client, name, kind="expense", **kw):
    return MovementCategory.objects.create(client=client, name=name, type=kind, **kw)


def mov(client, category, amount="10"):
    return FinancialMovement.objects.create(client=client, category=category, movement_type=category.type,
                                            amount=D(amount), date=date(2026, 3, 1))


class TestCategoryList:
    url = "/finance/categories" if False else None

    def get(self, auth_client):
        return auth_client.get(reverse("finance:categories"))

    def test_groups_and_counts(self, auth_client, user):
        c = user.client
        a = cat(c, "Alquiler", color="#f97316", icon="fa-solid fa-building")
        mov(c, a); mov(c, a)
        cat(c, "Ventas", "income")
        r = self.get(auth_client)
        groups = {g["key"]: g for g in r.context["groups"]}
        assert [g["key"] for g in r.context["groups"]] == ["expense", "income"]      # inversión/préstamos ocultos si están vacíos
        assert groups["expense"]["movements"] == 2 and groups["expense"]["items"][0].movement_count == 2
        body = r.content.decode()
        assert "2 movimientos" in body and "Alquiler" in body and "--color:#f97316" in body
        assert f"?category={a.pk}" in body and body.count("cat-add") >= 2

    def test_optional_groups_appear_when_used(self, auth_client, user):
        cat(user.client, "Ahorro", "investment")
        cat(user.client, "Crédito", "loan")
        keys = [g["key"] for g in self.get(auth_client).context["groups"]]
        assert keys == ["expense", "income", "investment", "loan"]

    def test_empty_group_links_to_prefilled_form(self, auth_client):
        assert "?type=expense" in self.get(auth_client).content.decode()

    def test_no_n_plus_one_for_counts(self, auth_client, user, django_assert_max_num_queries):
        for i in range(8):
            mov(user.client, cat(user.client, f"c{i}"))
        with django_assert_max_num_queries(12):
            self.get(auth_client)

    def test_other_tenant_hidden(self, auth_client, other_user):
        cat(other_user.client, "Secreta")
        assert "Secreta" not in self.get(auth_client).content.decode()


class TestCategoryForm:
    def test_type_prefilled_from_querystring(self, auth_client):
        r = auth_client.get(reverse("finance:new_category"), {"type": "income"})
        assert r.context["form"].initial["type"] == "income"
        assert 'value="income" checked' in r.content.decode().replace("  ", " ") or "checked" in r.content.decode()
        r = auth_client.get(reverse("finance:new_category"), {"type": "hack"})
        assert "type" not in r.context["form"].initial

    def test_renders_preview_color_and_icon_picker(self, auth_client):
        body = auth_client.get(reverse("finance:new_category")).content.decode()
        for needle in ('id="cat-preview"', 'type="color"', 'id="icon-grid"', 'class="seg-radio"', "category-form.js"):
            assert needle in body

    @pytest.mark.parametrize("data,field", [({"color": "rojo"}, "color"), ({"color": "#12345"}, "color"),
                                            ({"icon": "<script>"}, "icon"), ({"icon": "fa-solid fa-tag; x"}, "icon")])
    def test_invalid_color_or_icon(self, data, field):
        form = MovementCategoryForm({"name": "X", "type": "expense", "color": "#112233", "icon": "fa-tag", **data})
        assert not form.is_valid() and field in form.errors

    def test_normalises_icon_and_accepts_blank_color(self):
        form = MovementCategoryForm({"name": "X", "type": "expense", "color": "", "icon": "  FA-Solid   fa-Tag "})
        assert form.is_valid() and form.cleaned_data["icon"] == "fa-solid fa-tag"

    def test_default_color_for_new_only(self, client_entity):
        assert MovementCategoryForm().initial["color"] == "#3b82f6"
        existing = cat(client_entity, "Con color", color="#010203")
        assert MovementCategoryForm(instance=existing).initial.get("color") != "#3b82f6"


class TestCategoryDelete:
    def test_confirmation_shows_movement_count(self, auth_client, user):
        c = cat(user.client, "Vacía")
        body = auth_client.get(reverse("finance:delete_category", kwargs={"pk": c.pk})).content.decode()
        assert "Confirmar borrado" in body and "Movimientos asociados" in body

    def test_category_with_movements_cannot_be_deleted(self, auth_client, user):
        c = cat(user.client, "Usada")
        mov(user.client, c)
        url = reverse("finance:delete_category", kwargs={"pk": c.pk})
        assert "Confirmar borrado" not in auth_client.get(url).content.decode()
        r = auth_client.post(url, follow=True)                      # antes: 500 por ProtectedError
        assert r.status_code == 200 and MovementCategory.objects.filter(pk=c.pk).exists()
        assert any("No se puede borrar" in m.message for m in r.context["messages"])

    def test_other_tenant_category_not_deletable(self, auth_client, other_user):
        c = cat(other_user.client, "Ajena")
        assert auth_client.post(reverse("finance:delete_category", kwargs={"pk": c.pk})).status_code == 404


class TestMovementForm:
    def test_sections_switches_and_receipt_drop(self, auth_client, user):
        cat(user.client, "Ventas", "income")
        body = auth_client.get(reverse("finance:new_movement")).content.decode()
        for needle in ("Datos principales", "Detalle", "Justificante", 'class="switch"', 'id="receipt-drop"',
                       'id="type-pill"', "movement-form.js", "Ventas (Ingreso)"):
            assert needle in body
        assert body.count('class="switch"') == 3

    def test_prefilled_category_from_querystring(self, auth_client, user):
        c = cat(user.client, "Marketing")
        r = auth_client.get(reverse("finance:new_movement"), {"category": c.pk})
        assert r.context["form"].initial["category"] == c

    def test_edit_shows_current_receipt_preview(self, auth_client, user):
        from django.core.files.uploadedfile import SimpleUploadedFile
        c = cat(user.client, "Viajes")
        m = mov(user.client, c)
        m.receipt = SimpleUploadedFile("r.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        m.save()
        body = auth_client.get(reverse("finance:edit_movement", kwargs={"pk": m.pk})).content.decode()
        assert 'id="receipt-preview"' in body and "Sustituir el recibo" in body

    def test_validation_errors_are_rendered(self, auth_client, user):
        r = auth_client.post(reverse("finance:new_movement"), {"amount": ""})
        assert r.status_code == 200 and 'class="fld-errors"' in r.content.decode()

    def test_movement_delete_page_shows_details(self, auth_client, user):
        m = mov(user.client, cat(user.client, "Gas"), "12.50")
        body = auth_client.get(reverse("finance:delete_movement", kwargs={"pk": m.pk})).content.decode()
        assert "12,50 €" in body and "Gas" in body


class TestSelectPlaceholder:
    def test_blank_option_is_spanish_everywhere(self, auth_client, user):
        from documents.forms import DocumentRectificationForm
        body = auth_client.get(reverse("finance:new_movement")).content.decode()
        assert "Selecciona una opción" in body and "Select an option" not in body
        assert DocumentRectificationForm().fields["company"].empty_label == "Selecciona una opción"
