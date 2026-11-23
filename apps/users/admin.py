"""Registro de los modelos de seguridad en el administrador de Django."""
from django.contrib import admin

from .models import AccessLog, AuditRecord


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


@admin.register(AuditRecord)
class AuditRecordAdmin(admin.ModelAdmin):
    """La auditoría solo se consulta: no se agrega, edita ni borra desde el administrador."""

    list_display = ("created_at", "user_email", "action", "entity", "entity_id", "result")
    list_filter = ("result", "action")
    search_fields = ("user_email", "entity_id")
    readonly_fields = [field.name for field in AuditRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
