"""Configuración de la app `quality` (control de calidad)."""
from django.apps import AppConfig


class QualityConfig(AppConfig):
    """Registro de la app de control de calidad."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.quality"
    label = "quality"
