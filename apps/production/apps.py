"""Configuración de la app `production` (producción y trazabilidad)."""
from django.apps import AppConfig


class ProductionConfig(AppConfig):
    """Registro de la app de producción."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production"
    label = "production"
