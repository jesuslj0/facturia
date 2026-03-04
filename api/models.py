from django.db import models
import secrets
from django.conf import settings
from clients.models import Client
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone

class ApiKey(models.Model):

    ENVIRONMENT_CHOICES = [
        ("live", "Live"),
        ("test", "Test"),
    ]

    name = models.CharField(max_length=100)

    # Parte visible para lookup rápido
    prefix = models.CharField(max_length=32, db_index=True)

    # Parte secreta hasheada
    key_hash = models.CharField(max_length=128)

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="api_keys"
    )

    environment = models.CharField(
        max_length=10,
        choices=ENVIRONMENT_CHOICES,
        default="live"
    )

    scopes = models.JSONField(default=list, blank=True)

    is_active = models.BooleanField(default=True)

    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["prefix", "is_active"]),
        ]

    @classmethod
    def create_key(cls, client, name, environment="live", scopes=None, expires_at=None):
        if scopes is None:
            scopes = []

        prefix = cls._generate_prefix(environment)
        secret = secrets.token_urlsafe(32)

        raw_key = f"{prefix}.{secret}"

        obj = cls.objects.create(
            name=name,
            client=client,
            prefix=prefix,
            key_hash=make_password(secret),
            environment=environment,
            scopes=scopes,
            expires_at=expires_at,
        )

        return obj, raw_key  # Mostrar SOLO una vez

    def check_secret(self, secret):
        if not self.is_active:
            return False

        if self.expires_at and self.expires_at < timezone.now():
            return False

        is_valid = check_password(secret, self.key_hash)

        if is_valid:
            self.last_used_at = timezone.now()
            self.save(update_fields=["last_used_at"])

        return is_valid

    @staticmethod
    def _generate_prefix(environment):
        random_part = secrets.token_hex(6)

        if environment == "live":
            return f"sk_live_{random_part}"
        else:
            return f"sk_test_{random_part}"

    def has_scope(self, scope):
        return scope in self.scopes