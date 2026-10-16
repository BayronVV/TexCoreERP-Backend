from django.urls import path

from . import views

urlpatterns = [
    path("produccion/simulacion/", views.SimulacionView.as_view(), name="produccion_simulacion"),
    path("produccion/ordenes/", views.OrdenProduccionListCreateView.as_view(), name="produccion_ordenes"),
    path("produccion/ordenes/<int:pk>/", views.OrdenProduccionDetailView.as_view(), name="produccion_orden"),
    path("produccion/ordenes/<int:pk>/anular/", views.OrdenProduccionAnularView.as_view(), name="produccion_orden_anular"),
    path("produccion/monitor/", views.MonitorView.as_view(), name="produccion_monitor"),
    path("produccion/lotes/<int:pk>/historial/", views.LoteHistorialView.as_view(), name="produccion_lote_historial"),
    path("produccion/lotes/<int:pk>/<str:accion>/", views.LoteAccionView.as_view(), name="produccion_lote_accion"),
]
