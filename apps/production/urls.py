from django.urls import path

from . import views

urlpatterns = [
    path("produccion/simulacion/", views.SimulacionView.as_view(), name="produccion_simulacion"),
]
