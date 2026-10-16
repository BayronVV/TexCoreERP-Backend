from django.urls import path

from . import views

urlpatterns = [
    path("referencias/metadatos/", views.MetadatosView.as_view(), name="referencias_metadatos"),
    path("referencias/", views.ReferenciaListCreateView.as_view(), name="referencias"),
    path("referencias/<int:pk>/", views.ReferenciaDetailView.as_view(), name="referencia"),
    path("referencias/<int:pk>/estado/", views.ReferenciaEstadoView.as_view(), name="referencia_estado"),
    path("referencias/<int:pk>/imagenes/", views.ReferenciaImagenesView.as_view(), name="referencia_imagenes"),
    path("referencias/imagenes/<int:pk>/archivo/", views.ImagenArchivoView.as_view(), name="referencia_imagen"),
    path(
        "referencias/imagenes/<int:pk>/principal/",
        views.ImagenPrincipalView.as_view(),
        name="referencia_imagen_principal",
    ),
]
