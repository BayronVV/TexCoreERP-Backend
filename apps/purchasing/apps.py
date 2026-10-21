"""Configuración de la app `purchasing` (compras)."""
from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    """Registro de la app de compras."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchasing"
    label = "purchasing"
