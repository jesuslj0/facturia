from django.contrib import admin
from django.contrib.admin.decorators import register
from documents.models import Document, Company

# Register your models here.
@register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'document_type', 'status', 'total_amount', 'company_name', 'issue_date', 'created_at']
    search_fields = ['original_name', 'document_type']

    list_filter = ['status', 'document_type', 'issue_date']
    date_hierarchy = 'issue_date'
    
    def company_name(self, obj):
        return obj.company.name if obj.company else '-'
    
    def get_queryset(self, request):
        return Document.all_objects.all()


@register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'client', 'is_provider', 'is_customer', 'tax_id']
    list_filter = ['client', 'is_provider', 'is_customer']
    search_fields = ['name', 'tax_id', 'client__name']