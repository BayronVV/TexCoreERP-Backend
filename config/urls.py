"""Rutas raíz. Cada módulo de apps/ expone sus rutas bajo /api/."""
from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

urlpatterns = [
    path("api/", include("apps.core.urls")),
    path("api/", include("apps.users.urls")),
    path("api/", include("apps.inventory.urls")),
]

if settings.API_DOCS_ENABLED:
    # Públicas: describen la API pero no exponen datos (cada ruta sigue exigiendo su permiso).
    public = {"permission_classes": [AllowAny], "authentication_classes": []}
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(**public), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema", **public), name="swagger-ui"),
        path("api/redoc/", SpectacularRedocView.as_view(url_name="schema", **public), name="redoc"),
    ]
