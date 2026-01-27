from django.contrib import admin
from django.contrib.admin.decorators import register
from documents.models import Document

# Register your models here.
@register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['file', 'original_name', 'status', 'provider_name', 'created_at']
    search_fields = ['original_name', 'status', 'provider_name', 'created_at', 'reviewed_at']