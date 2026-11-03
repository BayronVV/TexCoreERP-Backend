"""Configuración de la app `finished` (producto terminado)."""
from django.apps import AppConfig


class FinishedConfig(AppConfig):
    """Registro de la app de producto terminado."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finished"
    label = "finished"
