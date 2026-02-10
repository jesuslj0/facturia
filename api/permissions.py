# documents/permissions.py
from rest_framework.permissions import BasePermission
from .models import ApiKey

class HasApiKey(BasePermission):
    def has_permission(self, request, view):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return False
        
        try: 
            api = ApiKey.objects.get(key=api_key, is_active=True)
            request.client = api.client
            return True
        except ApiKey.DoesNotExist:
            return False
