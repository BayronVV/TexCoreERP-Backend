"""Rutas de `/api/calidad/`: catálogo de defectos, lotes por inspeccionar e inspecciones."""
from django.urls import path

from . import views

urlpatterns = [
    path("calidad/defectos/", views.DefectoListCreateView.as_view(), name="calidad_defectos"),
    path("calidad/defectos/<int:pk>/", views.DefectoDetailView.as_view(), name="calidad_defecto"),
    path("calidad/pendientes/", views.PendientesView.as_view(), name="calidad_pendientes"),
    path("calidad/inspecciones/", views.InspeccionListCreateView.as_view(), name="calidad_inspecciones"),
    path("calidad/inspecciones/<int:pk>/", views.InspeccionDetailView.as_view(), name="calidad_inspeccion"),
]
