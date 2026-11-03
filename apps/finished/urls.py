"""Rutas de `/api/terminado/`: ingresos, inspecciones por ingresar, existencias y movimientos."""
from django.urls import path

from . import views

urlpatterns = [
    path("terminado/pendientes/", views.PendientesView.as_view(), name="terminado_pendientes"),
    path("terminado/ingresos/", views.IngresoListCreateView.as_view(), name="terminado_ingresos"),
    path("terminado/ingresos/<int:pk>/", views.IngresoDetailView.as_view(), name="terminado_ingreso"),
    path("terminado/existencias/", views.ExistenciasView.as_view(), name="terminado_existencias"),
    path("terminado/movimientos/", views.MovimientoListView.as_view(), name="terminado_movimientos"),
]
