from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Utilidades transversales: salud del sistema y modelos base."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
