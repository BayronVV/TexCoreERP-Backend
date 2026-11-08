"""Configuración de la app `shipping` (guías de envío y despachos)."""
from django.apps import AppConfig


class ShippingConfig(AppConfig):
    """Registro de la app de envíos: guías, relaciones de despacho y rastreo con Track123."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shipping"
    label = "shipping"
