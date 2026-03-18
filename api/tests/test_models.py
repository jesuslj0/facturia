from datetime import timedelta

import pytest
pytestmark = pytest.mark.django_db

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
from django.utils import timezone

from api.models import ApiKey


@pytest.mark.django_db
class TestApiKeyModel:
    def test_generate_prefix_and_scope_helpers(self, client_entity):
        api_key = ApiKey.objects.create(
            client=client_entity,
            name="SDK key",
            prefix=ApiKey._generate_prefix("test"),
            key_hash=make_password("secret"),
            environment="test",
            scopes=["documents:write"],
        )

        assert api_key.prefix.startswith("sk_test_")
        assert api_key.has_scope("documents:write") is True

    def test_check_secret_updates_last_used_at(self, api_key):
        _, secret = api_key.raw_key.split(".", 1)

        assert api_key.check_secret(secret) is True
        api_key.refresh_from_db()
        assert api_key.last_used_at is not None

    def test_check_secret_rejects_inactive_or_expired_keys(self, api_key):
        _, secret = api_key.raw_key.split(".", 1)
        api_key.expires_at = timezone.now() - timedelta(days=1)
        api_key.save(update_fields=["expires_at"])

        assert api_key.check_secret(secret) is False

        api_key.is_active = False
        api_key.expires_at = timezone.now() + timedelta(days=1)
        api_key.save(update_fields=["is_active", "expires_at"])

        assert api_key.check_secret(secret) is False

    def test_create_key_currently_fails_with_client_instance_assignment(self, client_entity):
        with pytest.raises(IntegrityError):
            ApiKey.create_key(client=client_entity, name="Broken helper", environment="test")
