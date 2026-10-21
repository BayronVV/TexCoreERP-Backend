"""Rutas de `/api/compras/`: órdenes de compra, recepciones y metadatos."""
from django.urls import path

from . import views

urlpatterns = [
    path("compras/metadatos/", views.ComprasMetadatosView.as_view(), name="compras_metadatos"),
    path("compras/ordenes/", views.OrdenCompraListCreateView.as_view(), name="compras_ordenes"),
    path("compras/ordenes/<int:pk>/", views.OrdenCompraDetailView.as_view(), name="compras_orden"),
    path("compras/ordenes/<int:pk>/aprobar/", views.OrdenCompraAprobarView.as_view(), name="compras_orden_aprobar"),
    path("compras/ordenes/<int:pk>/cancelar/", views.OrdenCompraCancelarView.as_view(), name="compras_orden_cancelar"),
    path("compras/ordenes/<int:pk>/cerrar/", views.OrdenCompraCerrarView.as_view(), name="compras_orden_cerrar"),
    path("compras/recepciones/", views.RecepcionListCreateView.as_view(), name="compras_recepciones"),
]
