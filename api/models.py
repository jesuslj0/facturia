from django.db import models
import secrets
from django.conf import settings
from clients.models import Client

class ApiKey(models.Model):
    name = models.CharField(max_length=100)
    key = models.CharField(max_length=64, unique=True, db_index=True)
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def generate():
        return secrets.token_hex(32)
