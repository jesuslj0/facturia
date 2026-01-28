from django.contrib import admin
from django.contrib.admin.decorators import register
from clients.models import Client, ClientUser

@register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'tax_id', 'is_active')
    search_fields = ('name', 'tax_id')

@register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    list_display = ('user', 'client')
    search_fields = ('user', 'client')