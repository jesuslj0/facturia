from django.contrib import admin
from django.contrib.admin.decorators import register
from api.models import ApiKey
from django.contrib import messages

@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "environment", "is_active", "created_at")
    readonly_fields = ("created_at", "last_used_at", "prefix")

    fields = (
        "name",
        "client",
        "environment",
        "scopes",
        "expires_at",
        "is_active",
        "prefix",
        "created_at",
        "last_used_at",
    )

    def save_model(self, request, obj, form, change):
        # Solo generar key al crear un nuevo objeto
        if not change:
            api_key_obj, raw_key = ApiKey.create_key(
                client=obj.client,
                name=obj.name,
                environment=obj.environment,
                scopes=obj.scopes,
                expires_at=obj.expires_at,
            )

            messages.success(
                request,
                f"API Key creada correctamente. Guarda esta clave ahora: {raw_key}"
            )
            return
        else:
            # Edición normal: solo permite cambiar campos como name, is_active, etc.
            super().save_model(request, obj, form, change)