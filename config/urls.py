"""Rutas raíz. Cada módulo de apps/ expone sus rutas bajo /api/."""
from django.urls import include, path

urlpatterns = [
    path("api/", include("apps.core.urls")),
]
