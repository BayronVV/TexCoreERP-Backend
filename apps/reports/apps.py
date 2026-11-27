from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save

REPORT_SOURCE_MODELS = (
    "production.OrdenProduccion",
    "inventory.OrdenSalida",
    "production.Lote",
    "quality.Inspeccion",
    "sales.FacturaVenta",
    "sales.DetalleVenta",
    "shipping.Guia",
    "references.Variante",
    "references.Referencia",
)


def _on_report_source_change(sender, **kwargs):
    from .services import schedule_views_refresh

    schedule_views_refresh()


class ReportsConfig(AppConfig):
    """Configuración del módulo de reportes gerenciales y conexión de señales de refresco."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    verbose_name = "Reportes Gerenciales"

    def ready(self):
        for model_label in REPORT_SOURCE_MODELS:
            post_save.connect(
                _on_report_source_change,
                sender=model_label,
                weak=False,
                dispatch_uid=f"reports.save.{model_label}",
            )
            post_delete.connect(
                _on_report_source_change,
                sender=model_label,
                weak=False,
                dispatch_uid=f"reports.delete.{model_label}",
            )

