"""Rutas de `/api/produccion/`: simulación, órdenes, lotes, monitor, tarifas, costos, operarios y máquinas."""
from django.urls import path

from . import views

urlpatterns = [
    path("produccion/simulacion/", views.SimulacionView.as_view(), name="produccion_simulacion"),
    path("produccion/ordenes/", views.OrdenProduccionListCreateView.as_view(), name="produccion_ordenes"),
    path("produccion/ordenes/<int:pk>/", views.OrdenProduccionDetailView.as_view(), name="produccion_orden"),
    path("produccion/ordenes/<int:pk>/anular/", views.OrdenProduccionAnularView.as_view(), name="produccion_orden_anular"),
    path("produccion/tarifas/", views.TarifasView.as_view(), name="produccion_tarifas"),
    path("produccion/ordenes/<int:pk>/costos/", views.OrdenProduccionCostosView.as_view(), name="produccion_orden_costos"),
    path("produccion/monitor/", views.MonitorView.as_view(), name="produccion_monitor"),
    path("produccion/operarios/", views.OperarioListCreateView.as_view(), name="produccion_operarios"),
    path("produccion/operarios/<int:pk>/", views.OperarioDetailView.as_view(), name="produccion_operario"),
    path("produccion/maquinas/", views.MaquinaListCreateView.as_view(), name="produccion_maquinas"),
    path("produccion/maquinas/<int:pk>/", views.MaquinaDetailView.as_view(), name="produccion_maquina"),
    path("produccion/lotes/<int:pk>/historial/", views.LoteHistorialView.as_view(), name="produccion_lote_historial"),
    # Estas tres van antes de `<accion>` (iniciar, pausar...), que aceptaría cualquier texto.
    path("produccion/lotes/<int:pk>/asignar/", views.LoteAsignarView.as_view(), name="produccion_lote_asignar"),
    path("produccion/lotes/<int:pk>/desvincular/", views.LoteDesvincularView.as_view(), name="produccion_lote_desvincular"),
    path("produccion/lotes/<int:pk>/asignaciones/", views.LoteAsignacionesView.as_view(), name="produccion_lote_asignaciones"),
    path("produccion/lotes/<int:pk>/<str:accion>/", views.LoteAccionView.as_view(), name="produccion_lote_accion"),
]

