from django.urls import path

from . import views

urlpatterns = [
    path("envios/metadatos/", views.MetadatosEnvioView.as_view(), name="envios_metadatos"),
    path("envios/resumen/", views.ResumenView.as_view(), name="envios_resumen"),
    path("envios/pendientes/", views.PendientesView.as_view(), name="envios_pendientes"),
    path("envios/rastreo/estado/", views.RastreoEstadoView.as_view(), name="envios_rastreo_estado"),
    path("envios/guias/", views.GuiaListView.as_view(), name="envios_guias"),
    path("envios/guias/<int:pk>/", views.GuiaDetailView.as_view(), name="envios_guia"),
    path("envios/guias/<int:pk>/estado/", views.GuiaEstadoView.as_view(), name="envios_guia_estado"),
    path("envios/guias/<int:pk>/flete/", views.GuiaFleteView.as_view(), name="envios_guia_flete"),
    path("envios/guias/<int:pk>/devolucion/", views.GuiaDevolucionView.as_view(), name="envios_guia_devolucion"),
    path("envios/guias/<int:pk>/rastrear/", views.GuiaRastrearView.as_view(), name="envios_guia_rastrear"),
    path("envios/facturas/<int:pk>/guia/", views.FacturaGuiaView.as_view(), name="envios_factura_guia"),
    path("envios/relaciones/", views.RelacionListCreateView.as_view(), name="envios_relaciones"),
    path("envios/relaciones/<int:pk>/", views.RelacionDetailView.as_view(), name="envios_relacion"),
    path("envios/relaciones/<int:pk>/pdf/", views.RelacionPdfView.as_view(), name="envios_relacion_pdf"),
]
