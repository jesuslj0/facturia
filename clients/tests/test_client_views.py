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
