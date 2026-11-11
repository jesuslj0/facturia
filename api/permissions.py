# documents/permissions.py
from rest_framework.permissions import BasePermission
from .models import ApiKey

class HasApiKey(BasePermission):
    def has_permission(self, request, view):
        raw_key = request.META.get("HTTP_X_API_KEY")

        if not raw_key:
            return False

        try:
            prefix, secret = raw_key.split(".", 1)
        except ValueError:
            return False

        try:
            api_key = ApiKey.objects.get(prefix=prefix, is_active=True)
        except ApiKey.DoesNotExist:
            return False

        # Validación completa (hash + expiración)
        if not api_key.check_secret(secret):
            return False

        # Guardamos en request para usarlo después
        request.client = api_key.client
        request.api_key = api_key

        return True
