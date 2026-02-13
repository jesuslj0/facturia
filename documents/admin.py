from django.contrib import admin
from django.contrib.admin.decorators import register
from documents.models import Document, Company

# Register your models here.
@register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['file', 'original_name', 'document_type', 'status', 'total_amount', 'company_name', 'created_at']
    search_fields = ['original_name', 'status', 'document_type', 'created_at', 'reviewed_at', 'total_amount']
    
    def company_name(self, obj):
        return obj.company.name if obj.company else '-'


@register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'client', 'type', 'tax_id']
    list_filter = ['client', 'type']
    search_fields = ['name', 'tax_id', 'client__name']