"""
Tests for clients app views and Client model edge cases.
"""
import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db

User = get_user_model()


class TestClientModel:
    def test_client_string_representation(self, client_entity):
        assert str(client_entity) == "ACME"

    def test_client_is_active_by_default(self, client_entity):
        assert client_entity.is_active is True

    def test_client_has_default_primary_color(self, client_entity):
        assert client_entity.primary_color == "#2563eb"


class TestCustomUserModel:
    def test_user_belongs_to_correct_client(self, user, client_entity):
        assert user.client == client_entity

    def test_has_any_role_false_when_no_roles_match(self, user):
        assert user.has_any_role("admin", "finance") is False

    def test_is_owner_false_without_owner_role(self, client_entity):
        plain_user = User.objects.create_user(
            username="plain-user",
            password="secret",
            client=client_entity,
        )
        assert plain_user.is_owner() is False

    def test_has_role_returns_false_for_missing_role(self, user):
        assert user.has_role("nonexistent") is False

    def test_user_with_multiple_roles(self, client_entity, role_owner, role_reviewer):
        u = User.objects.create_user(
            username="multi-role",
            password="secret",
            client=client_entity,
        )
        u.roles.add(role_owner, role_reviewer)

        assert u.has_role("owner") is True
        assert u.has_role("reviewer") is True
        assert u.has_any_role("finance", "reviewer") is True


class TestProfileAccount:
    url = "/clients/detail/"

    def test_page_shows_both_sections(self, auth_client):
        body = auth_client.get(self.url).content.decode()
        assert "Mi perfil" in body and "Mi empresa" in body and 'aria-current="page"' in body
        assert 'name="form_name" value="account"' in body and 'value="password"' in body
        assert 'value="company_info"' not in body                      # la ficha de empresa vive en su pestaña
        company = auth_client.get(self.url, {"tab": "empresa"}).content.decode()
        assert 'value="company_info"' in company and 'value="account"' not in company

    def test_update_own_data(self, auth_client, user):
        r = auth_client.post(self.url, {"form_name": "account", "first_name": "Ana", "last_name": "Ruiz", "email": "ana@x.com"})
        assert r.status_code == 302
        user.refresh_from_db()
        assert (user.first_name, user.last_name, user.email) == ("Ana", "Ruiz", "ana@x.com")

    def test_email_required_and_username_client_not_editable(self, auth_client, user, other_client_entity):
        r = auth_client.post(self.url, {"form_name": "account", "email": ""})
        assert r.status_code == 200 and "obligatorio" in r.content.decode()
        old_client, old_username = user.client_id, user.username
        auth_client.post(self.url, {"form_name": "account", "email": "a@b.com", "username": "hack", "client": other_client_entity.pk})
        user.refresh_from_db()
        assert (user.client_id, user.username) == (old_client, old_username)

    def test_account_post_does_not_touch_company(self, auth_client, client_entity):
        auth_client.post(self.url, {"form_name": "account", "email": "a@b.com", "name": "Hackeada"})
        client_entity.refresh_from_db()
        assert client_entity.name == "ACME"

    def test_change_password_keeps_session(self, auth_client, user):
        r = auth_client.post(self.url, {"form_name": "password", "old_password": "secret123",
                                        "new_password1": "N0ev4-clave-larga!", "new_password2": "N0ev4-clave-larga!"})
        assert r.status_code == 302
        user.refresh_from_db()
        assert user.check_password("N0ev4-clave-larga!")
        assert auth_client.get(self.url).status_code == 200      # sigue autenticado

    def test_wrong_old_password_rejected(self, auth_client, user):
        r = auth_client.post(self.url, {"form_name": "password", "old_password": "mala",
                                        "new_password1": "N0ev4-clave-larga!", "new_password2": "N0ev4-clave-larga!"})
        assert r.status_code == 200
        user.refresh_from_db()
        assert user.check_password("secret123")

    def test_company_form_still_default(self, auth_client, client_entity):
        r = auth_client.post(self.url, {"primary_color": "#112233"})
        assert r.status_code == 302
        client_entity.refresh_from_db()
        assert client_entity.primary_color == "#112233"

    def test_data_shown_read_only_first_and_edit_form_available(self, auth_client, user):
        body = auth_client.get(self.url).content.decode()
        assert "data-edit" in body and "data-start-editing" not in body
        assert user.username in body

    def test_invalid_submit_reopens_edit_mode(self, auth_client):
        body = auth_client.post(self.url, {"form_name": "account", "email": ""}).content.decode()
        assert "data-start-editing" in body

    def test_city_and_birth_date_saved_and_shown(self, auth_client, user):
        r = auth_client.post(self.url, {"form_name": "account", "email": "a@b.com", "city": "Sevilla", "birth_date": "1990-05-17"})
        assert r.status_code == 302
        user.refresh_from_db()
        assert user.city == "Sevilla" and str(user.birth_date) == "1990-05-17"
        body = auth_client.get(self.url).content.decode()
        assert "Sevilla" in body and "May. 17 de 1990" in body and "Alta en la empresa" in body

    @pytest.mark.parametrize("value", ["2999-01-01", "1800-01-01"])
    def test_invalid_birth_date_rejected(self, auth_client, value):
        r = auth_client.post(self.url, {"form_name": "account", "email": "a@b.com", "birth_date": value})
        assert r.status_code == 200 and 'data-start-editing="account"' in r.content.decode()

    def test_password_error_reopens_password_panel(self, auth_client):
        r = auth_client.post(self.url, {"form_name": "password", "old_password": "mala", "new_password1": "x", "new_password2": "y"})
        assert 'data-start-editing="password"' in r.content.decode()

    def test_password_button_next_to_edit(self, auth_client):
        body = auth_client.get(self.url).content.decode()
        assert 'data-edit="account"' in body and 'data-edit="password"' in body

    def test_pretty_date_format(self):
        from datetime import date, datetime
        from documents.templatetags.ui import pretty_date
        assert pretty_date(date(2024, 2, 5)) == "Feb. 05 de 2024"
        assert pretty_date(datetime(2024, 12, 25, 10, 0)) == "Dic. 25 de 2024"
        assert pretty_date(None) == ""


class TestCompanyInfo:
    url = "/clients/detail/"

    def test_company_info_shown_fixed_first(self, auth_client, client_entity):
        body = auth_client.get(self.url, {"tab": "empresa"}).content.decode()
        assert "Fecha de fundación" in body and "Empleados" in body and 'data-edit="company"' in body
        assert "data-start-editing" not in body

    def test_update_company_info(self, auth_client, client_entity):
        r = auth_client.post(self.url, {
            "form_name": "company_info", "founded_date": "2015-02-05", "employee_count": "12",
            "industry": "Consultoría", "city": "Sevilla", "website": "https://acme.example", "phone": "600111222",
        })
        assert r.status_code == 302
        client_entity.refresh_from_db()
        assert (client_entity.employee_count, client_entity.industry, client_entity.city) == (12, "Consultoría", "Sevilla")
        body = auth_client.get(self.url, {"tab": "empresa"}).content.decode()
        assert "Feb. 05 de 2015" in body and "https://acme.example" in body

    def test_all_optional_and_name_taxid_untouched(self, auth_client, client_entity):
        r = auth_client.post(self.url, {"form_name": "company_info", "name": "Hack", "tax_id": "X1"})
        assert r.status_code == 302
        client_entity.refresh_from_db()
        assert client_entity.name == "ACME" and client_entity.tax_id == "ES12345678"
        assert client_entity.founded_date is None and client_entity.employee_count is None

    @pytest.mark.parametrize("data", [{"founded_date": "2999-01-01"}, {"founded_date": "1700-01-01"},
                                      {"employee_count": "-3"}, {"website": "no-es-url"}])
    def test_invalid_values_reopen_panel(self, auth_client, data):
        r = auth_client.post(self.url, {"form_name": "company_info", **data})
        assert r.status_code == 200 and 'data-start-editing="company"' in r.content.decode()

    def test_users_table_marks_current_user(self, auth_client, user, other_user):
        body = auth_client.get(self.url, {"tab": "empresa"}).content.decode()
        assert body.count(">Tú<") == 1 and 'class="is-me"' in body

    def test_other_tenant_not_modified(self, auth_client, other_client_entity):
        auth_client.post(self.url, {"form_name": "company_info", "city": "Madrid"})
        other_client_entity.refresh_from_db()
        assert other_client_entity.city == ""


class TestAccountTabs:
    url = "/clients/detail/"

    def test_default_and_invalid_tab_fall_back_to_perfil(self, auth_client):
        assert auth_client.get(self.url).context["tab"] == "perfil"
        assert auth_client.get(self.url, {"tab": "otra"}).context["tab"] == "perfil"
        assert auth_client.get(self.url, {"tab": "empresa"}).context["tab"] == "empresa"

    def test_saving_redirects_to_the_right_tab(self, auth_client):
        r = auth_client.post(self.url, {"form_name": "account", "email": "a@b.com"})
        assert r.url.endswith("?tab=perfil")
        r = auth_client.post(self.url, {"form_name": "company_info", "city": "Cádiz"})
        assert r.url.endswith("?tab=empresa")

    def test_errors_stay_on_their_tab(self, auth_client):
        r = auth_client.post(self.url, {"form_name": "company_info", "founded_date": "2999-01-01"})
        assert r.context["tab"] == "empresa"
        r = auth_client.post(self.url, {"form_name": "account", "email": ""})
        assert r.context["tab"] == "perfil"

    def test_page_and_sidebar_named_cuenta(self, auth_client):
        body = auth_client.get(self.url).content.decode()
        assert "<h1><i class=\"fa-solid fa-user\"></i> Cuenta</h1>" in body and 'title="Cuenta"' in body and 'title="Perfil"' not in body
