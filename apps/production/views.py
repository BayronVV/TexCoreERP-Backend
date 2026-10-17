from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.services import fail
from apps.inventory.views import apply_filters, limited
from apps.references import fichas

from . import catalog, costing, monitor, services, tracking
from .models import EventoEtapa, Lote, OrdenProduccion, TarifaManoObra
from .serializers import (
    AccionLoteSerializer,
    AnulacionProduccionSerializer,
    EventoEtapaSerializer,
    LoteSerializer,
    MonitorSerializer,
    OrdenCostosRespuestaSerializer,
    OrdenProduccionInputSerializer,
    OrdenProduccionSerializer,
    SimulacionInputSerializer,
    SimulacionSalidaSerializer,
    TarifaManoObraInputSerializer,
    TarifaManoObraSerializer,
)


@extend_schema(
    tags=["produccion"], summary="Simular la producción de una referencia contra el stock (HU 4.1, TE-110)",
    request=SimulacionInputSerializer, responses=SimulacionSalidaSerializer,
    description="Verifica si hay material para fabricar N prendas antes de crear una orden. Devuelve `viable`, por material lo "
                "requerido, lo disponible y lo que falta, el **máximo producible** con el stock actual y su **cuello de "
                "botella**. Si se envían `lotes`, indica hasta qué lote alcanza el stock (acumulado, porque comparten el "
                "mismo material). Es solo lectura: no reserva ni descuenta stock, y la orden vuelve a verificarlo al crearse. "
                "La referencia debe estar activa y tener ficha técnica.",
)
class SimulacionView(APIView):
    # Es un POST porque lleva una lista de lotes, pero solo calcula: no escribe nada, así que basta con poder ver.
    required_permissions = {"POST": catalog.PRODUCTION_VIEW}

    def post(self, request):
        data = SimulacionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        garments = fichas.parse_garments(data.validated_data["cantidad"])
        reference = services.get_reference(data.validated_data["referencia"])
        result = services.simulate(reference, garments, data.validated_data.get("lotes"))
        return Response(SimulacionSalidaSerializer(result).data)


ORDERS_READ_WRITE = {"GET": catalog.PRODUCTION_VIEW, "POST": catalog.PRODUCTION_MANAGE}


def order_queryset():
    return OrdenProduccion.objects.select_related(
        "orden_salida__producto_resultado", "referencia", "creado_por"
    ).prefetch_related("lotes__tallas", "lotes__etapas__responsable", "orden_salida__lineas__producto")


@extend_schema(tags=["produccion"])
class OrdenProduccionListCreateView(generics.ListAPIView):
    required_permissions = ORDERS_READ_WRITE
    serializer_class = OrdenProduccionSerializer
    pagination_class = None

    @extend_schema(summary="Listar las órdenes de producción (filtros: estado, referencia, limit)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = apply_filters(
            order_queryset(), self.request.query_params,
            (("estado", "orden_salida__estado"), ("referencia", "referencia_id")),
        )
        return limited(queryset, self.request)

    @extend_schema(
        summary="Crear una orden de producción con sus lotes y tallas (HU 4.2, TE-114)",
        request=OrdenProduccionInputSerializer, responses={201: OrdenProduccionSerializer},
        description="Crea la orden y la divide en lotes (`OP-0001-L01`...), con tallas opcionales por lote. En una sola "
                    "transacción descuenta del almacén el material que pide la ficha técnica de la referencia (con merma) y "
                    "registra la salida en el kardex; si falta material responde 400 con `faltantes` y no queda nada. Sin "
                    "`lotes` se crea un único lote. No exige `inventario.gestionar`: las cantidades salen de la ficha.",
    )
    def post(self, request):
        data = OrdenProduccionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        order = services.create_production_order(
            user=request.user, referencia_id=values.pop("referencia"), cantidad=values.pop("cantidad"),
            producto_resultado_id=values.pop("producto_resultado"), **values,
        )
        return Response(OrdenProduccionSerializer(order_queryset().get(pk=order.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["produccion"], summary="Consultar una orden de producción con sus lotes y tallas")
class OrdenProduccionDetailView(generics.RetrieveAPIView):
    required_permissions = catalog.PRODUCTION_VIEW
    serializer_class = OrdenProduccionSerializer

    def get_queryset(self):
        return order_queryset()


@extend_schema(
    tags=["produccion"], summary="Anular una orden de producción en proceso",
    description="Devuelve al almacén el material descontado. Exige el motivo.",
    request=AnulacionProduccionSerializer, responses={200: OrdenProduccionSerializer},
)
class OrdenProduccionAnularView(APIView):
    required_permissions = catalog.PRODUCTION_MANAGE

    def post(self, request, pk):
        data = AnulacionProduccionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.cancel_production_order(user=request.user, order_id=pk, motivo=data.validated_data["motivo"])
        return Response(OrdenProduccionSerializer(order_queryset().get(pk=pk)).data)


def lot_queryset():
    return Lote.objects.select_related("orden__orden_salida").prefetch_related("tallas", "etapas__responsable")


@extend_schema(
    tags=["produccion"], summary="Controlar el tiempo de un lote: iniciar, pausar, reanudar o completar (HU 4.3, TE-118)",
    request=AccionLoteSerializer, responses={200: LoteSerializer},
    description="Los botones Play, Pausa y Stop de cada lote. `iniciar` arranca la siguiente etapa (corte, confección, "
                "terminación); `pausar` y `reanudar` cierran y abren un intervalo "
                "de tiempo; `completar` termina la etapa en curso. El tiempo neto de cada etapa no cuenta las pausas. Una "
                "etapa solo empieza cuando la anterior terminó y una orden anulada no admite acciones.",
)
class LoteAccionView(APIView):
    required_permissions = catalog.PRODUCTION_MANAGE

    def post(self, request, pk, accion):
        data = AccionLoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        tracking.act_on_lot(user=request.user, lot_id=pk, action=accion, note=data.validated_data["nota"])
        return Response(LoteSerializer(lot_queryset().get(pk=pk)).data)


@extend_schema(
    tags=["produccion"], summary="Historial de tiempos de un lote (trazabilidad)",
    responses={200: EventoEtapaSerializer(many=True)},
    description="Cada inicio, pausa, reanudación y fin de las etapas del lote, con quién lo hizo y cuándo. Solo se agregan "
                "registros, nunca se editan.",
)
class LoteHistorialView(generics.ListAPIView):
    required_permissions = catalog.PRODUCTION_VIEW
    serializer_class = EventoEtapaSerializer
    pagination_class = None

    def get_queryset(self):
        return EventoEtapa.objects.filter(etapa_lote__lote_id=self.kwargs["pk"]).select_related(
            "etapa_lote", "usuario"
        ).order_by("momento", "id")


def _query_int(request, name, default=None, minimum=1, maximum=None):
    """Entero opcional de la query string; un valor mal formado responde 400 en lugar de fallar."""
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default
    if not raw.isdigit() or int(raw) < minimum or (maximum is not None and int(raw) > maximum):
        limits = f" entre {minimum} y {maximum}" if maximum is not None else ""
        fail(f"`{name}` debe ser un número entero{limits}.", name)
    return int(raw)


def _query_bool(request, name):
    """Booleano opcional de la query string (`1`/`true` o `0`/`false`); cualquier otra cosa responde 400."""
    raw = request.query_params.get(name)
    if raw in (None, "", "0", "false"):
        return False
    if raw not in ("1", "true"):
        fail(f"`{name}` debe ser 1 o 0.", name)
    return True


@extend_schema(
    tags=["produccion"], summary="Monitor de estado: los lotes agrupados por columna (HU 4.5, TE-126)",
    responses={200: MonitorSerializer},
    description="Los lotes en producción en cuatro columnas: Planeada, En proceso, En pausa y Terminada, cada una con su total "
                "y, como máximo, `limite` tarjetas (por defecto 50, hasta 200). Los más antiguos en su columna van primero; en "
                "Terminada, los más recientes, y solo los de los últimos `terminadas_dias` días (7 por defecto, hasta 90). Los "
                "lotes de órdenes anuladas no aparecen salvo con `canceladas=1`, que añade una columna aparte, sin acciones. "
                "Filtros: `orden` y `referencia` (ids); los totales respetan el filtro. Cada tarjeta trae `alerta` (ATENCION desde "
                "2 h detenido, CRITICA desde 8 h) y la respuesta resume las alertas de todos los lotes activos. El estado de cada "
                "lote se calcula a partir de sus etapas.",
)
class MonitorView(APIView):
    required_permissions = catalog.PRODUCTION_VIEW

    def get(self, request):
        board = monitor.build_board(
            limit=_query_int(request, "limite", monitor.DEFAULT_LIMIT, 1, monitor.MAX_LIMIT),
            order_id=_query_int(request, "orden"),
            reference_id=_query_int(request, "referencia"),
            done_days=_query_int(request, "terminadas_dias", monitor.DEFAULT_DONE_DAYS, 1, monitor.MAX_DONE_DAYS),
            include_cancelled=_query_bool(request, "canceladas"),
        )
        return Response(MonitorSerializer(board, context={"now": board["generado_at"]}).data)


# --- Tarifas de mano de obra y costos de producción (HU 4.6, TE-129 / TE-130) ---

TARIFAS_PERMISSIONS = {"GET": catalog.PRODUCTION_VIEW, "POST": catalog.PRODUCTION_MANAGE}


@extend_schema(tags=["produccion"])
class TarifasView(APIView):
    required_permissions = TARIFAS_PERMISSIONS

    @extend_schema(
        summary="Listar el historial de tarifas de mano de obra por minuto (HU 4.6, TE-129)",
        responses={200: TarifaManoObraSerializer(many=True)},
        description="Devuelve el historial de tarifas vigentes por etapa (corte, confección, terminación). Las tarifas nunca "
                    "se modifican ni borran: para actualizar un precio se crea una nueva vigencia con `POST`.",
    )
    def get(self, request):
        tarifas = TarifaManoObra.objects.filter(deleted_at__isnull=True).order_by("etapa", "-vigente_desde", "-id")
        return Response(TarifaManoObraSerializer(tarifas, many=True).data)

    @extend_schema(
        summary="Registrar una nueva vigencia de tarifa de mano de obra (HU 4.6, TE-129)",
        request=TarifaManoObraInputSerializer,
        responses={201: TarifaManoObraSerializer},
        description="Agrega una tarifa por minuto para una etapa productiva a partir de una fecha de vigencia (por defecto hoy). "
                    "Se utiliza para costear las etapas que finalicen en esa vigencia o sigan en curso.",
    )
    def post(self, request):
        data = TarifaManoObraInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        vigente_desde = data.validated_data.get("vigente_desde") or timezone.localdate()
        tarifa = TarifaManoObra.objects.create(
            etapa=data.validated_data["etapa"],
            costo_minuto=data.validated_data["costo_minuto"],
            vigente_desde=vigente_desde,
            creado_por=request.user,
        )
        return Response(TarifaManoObraSerializer(tarifa).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["produccion"],
    summary="Costos y liquidación financiera de una orden de producción (HU 4.6, TE-130)",
    responses={200: OrdenCostosRespuestaSerializer},
    description="Calcula los costos reales de la orden: materiales consumidos (según costo de compra/promedio de cada línea) "
                    "y mano de obra de cada etapa de cada lote (tiempo neto invertido × tarifa por minuto vigente). Prorratea "
                    "materiales a los lotes en proporción a sus prendas. Informa si el costeo está `completo` o es parcial con "
                    "`advertencias` si faltan tarifas o costos de material. Una orden anulada devuelve costos en cero.",
)
class OrdenProduccionCostosView(APIView):
    required_permissions = catalog.PRODUCTION_VIEW

    def get(self, request, pk):
        try:
            order = OrdenProduccion.objects.select_related(
                "referencia", "orden_salida"
            ).prefetch_related(
                "orden_salida__lineas__producto",
                "lotes__etapas",
            ).get(pk=pk, deleted_at__isnull=True)
        except OrdenProduccion.DoesNotExist:
            raise Http404("La orden de producción no existe.")

        result = costing.calculate_order_costs(order)
        return Response(result)

