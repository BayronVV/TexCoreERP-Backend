"""Configuración de la app `references` (referencias de jean y fichas técnicas)."""
from django.apps import AppConfig


class ReferencesConfig(AppConfig):
    """Registro de la app de referencias de jean y fichas técnicas."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.references"
    label = "references"
