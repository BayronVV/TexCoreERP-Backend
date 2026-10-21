"""Configuración de la app `inventory` (inventario de materias primas)."""
from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """Registro de la app de inventario."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
    label = "inventory"
