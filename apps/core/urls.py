"""Rutas de salud del servidor y de la base de datos (`/api/health/`)."""
from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("health/db/", views.health_db, name="health-db"),
]
