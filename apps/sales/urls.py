"""Rutas de `/api/ventas/`: clientes, precios, facturas (con PDF y anulación) y metadatos."""
from django.urls import path

from . import views

urlpatterns = [
    path("ventas/metadatos/", views.MetadatosVentaView.as_view(), name="ventas_metadatos"),
    path("ventas/clientes/", views.ClienteListCreateView.as_view(), name="ventas_clientes"),
    path("ventas/clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="ventas_cliente"),
    path("ventas/precios/", views.PrecioListView.as_view(), name="ventas_precios"),
    path("ventas/precios/<int:referencia>/", views.PrecioDetailView.as_view(), name="ventas_precio"),
    path("ventas/facturas/", views.FacturaListCreateView.as_view(), name="ventas_facturas"),
    path("ventas/facturas/<int:pk>/", views.FacturaDetailView.as_view(), name="ventas_factura"),
    path("ventas/facturas/<int:pk>/pdf/", views.FacturaPdfView.as_view(), name="ventas_factura_pdf"),
    path("ventas/facturas/<int:pk>/anular/", views.FacturaAnularView.as_view(), name="ventas_factura_anular"),
    path("ventas/facturas/<int:pk>/conciliar/", views.FacturaConciliarView.as_view(), name="ventas_factura_conciliar"),
    path("ventas/cartera/resumen/", views.CarteraResumenView.as_view(), name="ventas_cartera_resumen"),
]
