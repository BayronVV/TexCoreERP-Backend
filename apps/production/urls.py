from django.urls import path

from . import remisiones_views, views

urlpatterns = [
    path("produccion/simulacion/", views.SimulacionView.as_view(), name="produccion_simulacion"),
    path("produccion/ordenes/", views.OrdenProduccionListCreateView.as_view(), name="produccion_ordenes"),
    path("produccion/ordenes/<int:pk>/", views.OrdenProduccionDetailView.as_view(), name="produccion_orden"),
    path("produccion/ordenes/<int:pk>/anular/", views.OrdenProduccionAnularView.as_view(), name="produccion_orden_anular"),
    path("produccion/tarifas/", views.TarifasView.as_view(), name="produccion_tarifas"),
    path("produccion/ordenes/<int:pk>/costos/", views.OrdenProduccionCostosView.as_view(), name="produccion_orden_costos"),
    path("produccion/monitor/", views.MonitorView.as_view(), name="produccion_monitor"),
    path("produccion/lotes/<int:pk>/historial/", views.LoteHistorialView.as_view(), name="produccion_lote_historial"),
    path("produccion/lotes/<int:pk>/<str:accion>/", views.LoteAccionView.as_view(), name="produccion_lote_accion"),
    # Procesos Externos / Lavandería (TE-57 / TE-131)
    path("lavanderia/lotes-disponibles/", remisiones_views.LotesDisponiblesLavadoView.as_view(), name="lavanderia_lotes_disponibles"),
    path("lavanderia/proveedores/", remisiones_views.LavanderiaProveedoresView.as_view(), name="lavanderia_proveedores"),
    path("lavanderia/recetas/", remisiones_views.RecetasLavadoView.as_view(), name="lavanderia_recetas"),
    path("lavanderia/remisiones/", remisiones_views.RemisionLavanderiaListCreateView.as_view(), name="lavanderia_remisiones"),
]

