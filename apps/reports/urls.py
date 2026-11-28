"""Rutas del módulo de reportes gerenciales bajo /api/reportes/ y de la trazabilidad bajo /api/trazabilidad/."""
from django.urls import path

from .views import (
    ReporteGerencialView,
    ReporteMetadatosView,
    ReporteRefrescarVistasView,
    TrazabilidadBuscarView,
    TrazabilidadFacturaView,
    TrazabilidadLoteView,
)

urlpatterns = [
    path("reportes/metadatos/", ReporteMetadatosView.as_view(), name="reportes-metadatos"),
    path("reportes/gerencial/", ReporteGerencialView.as_view(), name="reportes-gerencial"),
    path("reportes/refrescar/", ReporteRefrescarVistasView.as_view(), name="reportes-refrescar"),
    path("trazabilidad/buscar/", TrazabilidadBuscarView.as_view(), name="trazabilidad-buscar"),
    path("trazabilidad/lotes/<str:codigo>/", TrazabilidadLoteView.as_view(), name="trazabilidad-lote"),
    path("trazabilidad/facturas/<str:numero>/", TrazabilidadFacturaView.as_view(), name="trazabilidad-factura"),
]
