"""Endpoints analíticos del tablero de reportes gerenciales."""
from django.db import DatabaseError
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales import catalog as sales_catalog

from . import catalog, services, trazabilidad
from .serializers import MetadatosReporteSerializer, ReporteGerencialSerializer, ReporteRefrescoSerializer

VIEW_PERMISSIONS = {"GET": catalog.REPORTS_VIEW}
REFRESH_PERMISSIONS = {"POST": catalog.REPORTS_MANAGE}  # refrescar es una operación de gestión, no de consulta


@extend_schema(tags=["reportes"])
class ReporteMetadatosView(APIView):
    """Catálogos para los filtros avanzados del tablero gerencial (tipos de jean, referencias, estados de orden y cobro)."""
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(summary="Opciones disponibles para filtros de reportes", responses={200: MetadatosReporteSerializer})
    def get(self, request):
        return Response(MetadatosReporteSerializer(services.get_filter_metadata()).data)


@extend_schema(tags=["reportes"])
class ReporteGerencialView(APIView):
    """
    Endpoint analítico principal que consulta las vistas SQL materializadas y agrupa, suma y formatea
    los indicadores de producción, calidad y ventas según los filtros solicitados por gerencia.
    """
    required_permissions = VIEW_PERMISSIONS

    @extend_schema(
        summary="Consultar tablero analítico gerencial con filtros avanzados",
        description="Consolida producción, calidad, ventas y devoluciones por vendedor según los filtros. "
                    "`kpis.saldo_financiero_empresa` llega en `null` si el usuario no tiene `ventas.conciliar`.",
        parameters=[
            OpenApiParameter("desde", str, description="Fecha inicial (AAAA-MM-DD)"),
            OpenApiParameter("hasta", str, description="Fecha final (AAAA-MM-DD)"),
            OpenApiParameter("tipo_jean", str, description="Silueta / ajuste del jean (SKINNY, SLIM, RECTO, MOM, etc.)"),
            OpenApiParameter("referencia", int, description="ID de la referencia específica"),
            OpenApiParameter("estado_orden", str, description="Estado de la orden de producción (EN_PROCESO, COMPLETADA, ANULADA)"),
            OpenApiParameter("estado_cobro", str, description="Estado de cartera en ventas (POR_COBRAR, PAGADO, DEVOLUCION)"),
            OpenApiParameter("tipo_cliente", str, description="Tipo de cliente (DETAL, MAYORISTA, DISTRIBUIDOR)"),
            OpenApiParameter("vendedor", int, description="ID del vendedor de la factura"),
            OpenApiParameter("transportadora", str, description="Transportadora (INTERRAPIDISIMO, ENVIA, OTRA)"),
        ],
        responses={
            200: ReporteGerencialSerializer,
            400: OpenApiResponse(description="Filtros con fecha o identificador inválido"),
            403: OpenApiResponse(description="El rol no tiene permiso para ver reportes"),
        },
    )
    def get(self, request):
        data = services.build_management_report(request.query_params)
        if not request.user.has_permission_code(sales_catalog.SALES_RECONCILE):
            data["kpis"]["saldo_financiero_empresa"] = None
        return Response(ReporteGerencialSerializer(data).data)


@extend_schema(tags=["reportes"])
class ReporteRefrescarVistasView(APIView):
    """Fuerza la actualización de las vistas SQL materializadas en PostgreSQL (`REFRESH MATERIALIZED VIEW CONCURRENTLY`)."""
    required_permissions = REFRESH_PERMISSIONS

    @extend_schema(
        summary="Refrescar las vistas SQL materializadas de reportes",
        description="En PostgreSQL refresca las vistas materializadas del tablero; en SQLite no hace nada "
                    "(`refreshed` es falso) porque allí son vistas normales.",
        request=None,
        responses={
            200: ReporteRefrescoSerializer,
            403: OpenApiResponse(description="El rol no tiene permiso para ver reportes"),
            503: ReporteRefrescoSerializer,
        },
    )
    def post(self, request):
        """Refresca las vistas materializadas y devuelve si hubo refresco."""
        try:
            refreshed = services.refresh_materialized_views(raise_on_error=True)
        except DatabaseError:
            return Response(
                {"refreshed": False, "detail": "No fue posible actualizar las vistas analíticas en este momento."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"refreshed": refreshed, "detail": "Vistas analíticas actualizadas correctamente."})



TRACE_PERMISSIONS = {"GET": catalog.TRACE_VIEW_ANY}  # cualquiera de los permisos de consulta involucrados (HU 7.6)
TRACE_NOTE = (
    "Solo lectura. Cada bloque llega como `{\"acceso\": false}`, sin datos, si el usuario no tiene el permiso de "
    "consulta de su módulo. Basta con uno de estos permisos para abrirla: " + ", ".join(f"`{c}`" for c in catalog.TRACE_VIEW_ANY) + "."
)


@extend_schema(tags=["trazabilidad"])
class TrazabilidadBuscarView(APIView):
    """Búsqueda única por código exacto: orden (OP), lote, factura (FV), inspección, ingreso, relación (RD) o guía."""
    required_permissions = TRACE_PERMISSIONS

    @extend_schema(
        summary="Buscar un código para abrir su trazabilidad",
        description="Devuelve `tipo` (`lote`, `factura`, `orden`, `relacion` o `null` si no existe) y `codigo`; una orden "
                    "o una relación traen `opciones` para elegir el lote o la factura. " + TRACE_NOTE,
        parameters=[OpenApiParameter("codigo", str, required=True, description="Código exacto (no distingue mayúsculas)")],
        responses={200: OpenApiResponse(description="Resultado de la búsqueda")},
    )
    def get(self, request):
        return Response(trazabilidad.search(request.query_params.get("codigo", "")))


@extend_schema(tags=["trazabilidad"])
class TrazabilidadLoteView(APIView):
    """Recorrido de un lote: referencia, orden y materiales, etapas, lavandería, calidad, ingreso y conciliación."""
    required_permissions = TRACE_PERMISSIONS

    @extend_schema(
        summary="Trazabilidad de un lote",
        description=TRACE_NOTE + " Los materiales traen las compras previas a la salida (no la compra exacta).",
        responses={200: OpenApiResponse(description="Bloques del recorrido"), 404: OpenApiResponse(description="El lote no existe")},
    )
    def get(self, request, codigo):
        return Response(trazabilidad.lot_trace(request.user, codigo))


@extend_schema(tags=["trazabilidad"])
class TrazabilidadFacturaView(APIView):
    """Recorrido de una factura: venta, existencias y lotes de origen, guías con su historial y cobro."""
    required_permissions = TRACE_PERMISSIONS

    @extend_schema(
        summary="Trazabilidad de una factura",
        description=TRACE_NOTE + " Los lotes de origen son los que ingresaron cada talla y color hasta la fecha de la "
                    "factura: el stock se lleva por talla y color, no por lote.",
        responses={200: OpenApiResponse(description="Bloques del recorrido"), 404: OpenApiResponse(description="La factura no existe")},
    )
    def get(self, request, numero):
        return Response(trazabilidad.invoice_trace(request.user, numero))
