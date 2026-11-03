"""Rutas de `/api/terminado/`: ingresos, ajustes, inspecciones por ingresar, existencias y movimientos."""
from django.urls import path

from . import views

urlpatterns = [
    path("terminado/pendientes/", views.PendientesView.as_view(), name="terminado_pendientes"),
    path("terminado/ingresos/", views.IngresoListCreateView.as_view(), name="terminado_ingresos"),
    path("terminado/ingresos/<int:pk>/", views.IngresoDetailView.as_view(), name="terminado_ingreso"),
    path("terminado/ajustes/", views.AjusteListCreateView.as_view(), name="terminado_ajustes"),
    path("terminado/ajustes/<int:pk>/", views.AjusteDetailView.as_view(), name="terminado_ajuste"),
    path("terminado/metadatos/", views.AjusteMetadatosView.as_view(), name="terminado_metadatos"),
    path("terminado/existencias/", views.ExistenciasView.as_view(), name="terminado_existencias"),
    path("terminado/movimientos/", views.MovimientoListView.as_view(), name="terminado_movimientos"),
]
