from django.contrib import admin
from django.contrib.admin.decorators import register
from api.models import ApiKey
# Register your models here.
@register(ApiKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'is_active')