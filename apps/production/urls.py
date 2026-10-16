from django.urls import path

from . import views

urlpatterns = [
    path("produccion/simulacion/", views.SimulacionView.as_view(), name="produccion_simulacion"),
    path("produccion/ordenes/", views.OrdenProduccionListCreateView.as_view(), name="produccion_ordenes"),
    path("produccion/ordenes/<int:pk>/", views.OrdenProduccionDetailView.as_view(), name="produccion_orden"),
    path("produccion/ordenes/<int:pk>/anular/", views.OrdenProduccionAnularView.as_view(), name="produccion_orden_anular"),
]
