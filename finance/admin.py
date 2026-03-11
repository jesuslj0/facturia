from django.contrib import admin
from django.contrib.admin.decorators import register
from .models import MovementCategory, FinancialMovement

# Register your models here.
@register(MovementCategory)
class MovementCategoryAdmin(admin.ModelAdmin):
    list_display = ["client", "name", "type"]

@register(FinancialMovement)
class FinancialMovementAdmin(admin.ModelAdmin):
    list_display = ["client", "category", "description", "amount", "date", "created_at"]