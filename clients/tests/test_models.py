import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from clients.models import Role


@pytest.mark.django_db
class TestClientModels:
    def test_custom_user_requires_client(self):
        user = get_user_model()(username="missing-client")

        with pytest.raises(ObjectDoesNotExist):
            user.clean()

    def test_user_role_helpers(self, client_entity, role_owner, role_reviewer):
        user = get_user_model().objects.create_user(
            username="reviewer",
            password="secret123",
            client=client_entity,
        )
        user.roles.add(role_owner, role_reviewer)

        assert user.has_role("owner") is True
        assert user.has_any_role("reviewer", "finance") is True
        assert user.is_owner() is True

    def test_role_string_representation(self, role_owner):
        assert str(role_owner) == "ACME - Owner"

    def test_assigning_role_from_other_client_raises_validation_error(self, client_entity, other_client_entity):
        user = get_user_model().objects.create_user(
            username="scoped-user",
            password="secret123",
            client=client_entity,
        )
        foreign_role = Role.objects.create(client=other_client_entity, name="Foreign", code="foreign")

        with pytest.raises(ValidationError, match="does not belong to the same client"):
            user.roles.add(foreign_role)
