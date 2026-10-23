"""Registro de los modelos de seguridad en el administrador de Django."""
from django.contrib import admin

from .models import AccessLog


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "email", "ip")
    list_filter = ("event",)
    search_fields = ("email", "ip")
    readonly_fields = [field.name for field in AccessLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
