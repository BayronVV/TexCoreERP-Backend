from django.urls import path

from . import views

urlpatterns = [
    path("inventario/alertas/", views.AlertListView.as_view(), name="inventario_alertas"),
    path("inventario/productos/", views.ProductoListCreateView.as_view(), name="inventario_productos"),
    path("inventario/productos/<int:pk>/", views.ProductoDetailView.as_view(), name="inventario_producto"),
    path("inventario/movimientos/", views.MovimientoListView.as_view(), name="inventario_movimientos"),
    path("inventario/ingresos/", views.IngresoCreateView.as_view(), name="inventario_ingresos"),
    path(
        "inventario/movimientos/<int:pk>/evidencias/",
        views.MovimientoEvidenciaView.as_view(),
        name="inventario_movimiento_evidencias",
    ),
    path("inventario/ordenes/", views.OrdenListCreateView.as_view(), name="inventario_ordenes"),
    path("inventario/ordenes/<int:pk>/", views.OrdenDetailView.as_view(), name="inventario_orden"),
    path("inventario/ordenes/<int:pk>/anular/", views.OrdenAnularView.as_view(), name="inventario_orden_anular"),
    path(
        "inventario/ordenes/<int:pk>/evidencias/",
        views.OrdenEvidenciaView.as_view(),
        name="inventario_orden_evidencias",
    ),
    path("inventario/evidencias/<int:pk>/archivo/", views.EvidenciaArchivoView.as_view(), name="inventario_evidencia"),
]
