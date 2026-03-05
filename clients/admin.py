from django.contrib import admin
from django.contrib.admin.decorators import register
from clients.models import Client, CustomUser, Role
from django.contrib.auth.admin import UserAdmin

@register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'tax_id', 'is_active')
    search_fields = ('name', 'tax_id')

@register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'client')
    search_fields = ('client', 'username', 'first_name', 'last_name', 'email')

    fieldsets = UserAdmin.fieldsets + (
        ('Client & Role', {'fields': ('client', 'role', 'roles')}),
    )

admin.site.register(Role)
