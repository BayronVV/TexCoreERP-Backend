"""Rutas del módulo de reportes gerenciales bajo /api/reportes/."""
from django.urls import path

from .views import ReporteGerencialView, ReporteMetadatosView, ReporteRefrescarVistasView

urlpatterns = [
    path("reportes/metadatos/", ReporteMetadatosView.as_view(), name="reportes-metadatos"),
    path("reportes/gerencial/", ReporteGerencialView.as_view(), name="reportes-gerencial"),
    path("reportes/refrescar/", ReporteRefrescarVistasView.as_view(), name="reportes-refrescar"),
]

