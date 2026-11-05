"""Configuración de la app `sales` (ventas y facturación)."""
from django.apps import AppConfig


class SalesConfig(AppConfig):
    """Registro de la app de ventas: clientes, precios y factura POS interna."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    label = "sales"
