from django.contrib import admin
from .models import WhatsAppAccount,WhatsAppCampaign

@admin.register(WhatsAppAccount)
class WhatsAppAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'number', 'country_code', 'is_default')
    search_fields = ('name', 'number', 'user__username')
    list_filter = ('is_default',)

@admin.register(WhatsAppCampaign)
class WhatsAppCampaignAdmin(admin.ModelAdmin):
    list_display = (
           'id', 'name', 'user', 'whatsapp_group', 'deduplicate', 
           'safe_mode', 'unsafe_mode'
    )
    list_filter = ('deduplicate', 'safe_mode', 'unsafe_mode')
    search_fields = ('name', 'user__username', 'numbers')
       
    readonly_fields = ()  