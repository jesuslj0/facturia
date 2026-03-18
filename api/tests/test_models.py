from datetime import timedelta

import pytest
pytestmark = pytest.mark.django_db

from django.contrib.auth.hashers import make_password
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

    def test_create_key_generates_unique_prefix_and_returns_raw_key(self, client_entity, monkeypatch):
        prefixes = iter(["sk_test_collision", "sk_test_unique"])
        secrets_generated = iter(["secret-one", "secret-two"])

        ApiKey.objects.create(
            client=client_entity,
            name="Existing key",
            prefix="sk_test_collision",
            key_hash=make_password("existing-secret"),
            environment="test",
        )

        monkeypatch.setattr(ApiKey, "_generate_prefix", staticmethod(lambda environment: next(prefixes)))
        monkeypatch.setattr("api.models.secrets.token_urlsafe", lambda length: next(secrets_generated))

        api_key, raw_key = ApiKey.create_key(
            client=client_entity,
            name="Working helper",
            environment="test",
        )

        assert api_key.prefix == "sk_test_unique"
        assert raw_key == "sk_test_unique.secret-one"
        assert api_key.check_secret("secret-one") is True
