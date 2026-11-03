"""Vistas de producto terminado: ingresos, inspecciones por ingresar, existencias en matriz y libro de movimientos."""
from django.db.models import Prefetch, Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.views import apply_filters, limited

from . import catalog, services
from .models import IngresoLinea, IngresoTerminado, MovimientoTerminado
from .serializers import ExistenciasReferenciaSerializer, IngresoTerminadoInputSerializer, IngresoSerializer, MovimientoTerminadoSerializer, PendienteIngresoSerializer

LIMIT_PARAM = OpenApiParameter("limit", int, description="Máximo de registros (por defecto 100)")
READ_PERMISSIONS = {"GET": catalog.FINISHED_VIEW}
ENTRIES_PERMISSIONS = {"GET": catalog.FINISHED_VIEW, "POST": catalog.FINISHED_MANAGE}


def entry_queryset():
    return IngresoTerminado.objects.select_related("inspeccion", "lote__orden__referencia", "recibido_por").prefetch_related(
        Prefetch("lineas", queryset=IngresoLinea.objects.order_by("id"))
    )


@extend_schema(tags=["producto-terminado"])
class PendientesView(APIView):
    """Inspecciones con aptas que todavía no se ingresaron al inventario final."""
    required_permissions = READ_PERMISSIONS

    @extend_schema(
        summary="Listar las inspecciones por ingresar", parameters=[LIMIT_PARAM], responses={200: PendienteIngresoSerializer(many=True)},
        description="Cada una trae las variantes (talla y color) de su referencia y lo planificado en el lote, para repartir las aptas.",
    )
    def get(self, request):
        inspections = list(limited(services.pending_entries(), request))
        variants = services.variants_of({item.lote.orden.referencia_id for item in inspections})
        planned = services.planned_by_lot({item.lote_id for item in inspections})
        rows = []
        for item in inspections:
            lot = item.lote
            rows.append({
                "inspeccion": item.id, "inspeccion_codigo": item.codigo, "lote": lot.id, "lote_codigo": lot.codigo,
                "orden_codigo": lot.orden.codigo, "referencia": lot.orden.referencia_id, "referencia_nombre": lot.orden.referencia.nombre,
                "fecha": item.fecha, "aptas": item.aptas, "marras": item.marras,
                "variantes": [{"id": v.id, "talla": v.talla, "color": v.color} for v in variants[lot.orden.referencia_id]],
                "planificado": [{"variante": vid, "cantidad": qty} for vid, qty in planned[lot.id].items()],
            })
        return Response(PendienteIngresoSerializer(rows, many=True).data)


@extend_schema(tags=["producto-terminado"])
class IngresoListCreateView(APIView):
    """Lista los ingresos y registra uno nuevo (RF21)."""
    required_permissions = ENTRIES_PERMISSIONS

    @extend_schema(
        summary="Listar los ingresos (filtros: referencia, lote, desde, hasta, q, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("referencia", int, description="Id de la referencia"),
            OpenApiParameter("lote", int, description="Id del lote"),
            OpenApiParameter("desde", str, description="Fecha mínima (AAAA-MM-DD)"), OpenApiParameter("hasta", str, description="Fecha máxima"),
            OpenApiParameter("q", str, description="Código del ingreso, de la inspección o del lote"),
        ],
        responses={200: IngresoSerializer(many=True)},
    )
    def get(self, request):
        entries = apply_filters(
            entry_queryset(), request.query_params,
            [("referencia", "lote__orden__referencia_id"), ("lote", "lote_id"), ("desde", "fecha__gte"), ("hasta", "fecha__lte")],
        )
        q = request.query_params.get("q", "").strip()
        if q:
            entries = entries.filter(Q(codigo__icontains=q) | Q(inspeccion__codigo__icontains=q) | Q(lote__codigo__icontains=q))
        return Response(IngresoSerializer(limited(entries, request), many=True).data)

    @extend_schema(
        summary="Ingresar las aptas de una inspección", request=IngresoTerminadoInputSerializer, responses={201: IngresoSerializer},
        description="Reparte las aptas por talla y color; la suma debe ser exactamente las aptas de la inspección. Una inspección se "
                    "ingresa una sola vez: si ya se ingresó, responde 409. Suma al saldo de cada variante y deja su movimiento en el libro.",
    )
    def post(self, request):
        data = IngresoTerminadoInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        entry = services.register_entry(
            user=request.user, inspeccion_id=values["inspeccion"], lineas=values["lineas"], ubicacion=values.get("ubicacion", ""),
            observaciones=values.get("observaciones", ""), fecha=values.get("fecha"),
        )
        return Response(IngresoSerializer(entry_queryset().get(pk=entry.pk)).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["producto-terminado"])
class IngresoDetailView(APIView):
    """Consulta un ingreso. No tiene PATCH ni DELETE: el registro es inalterable."""
    required_permissions = READ_PERMISSIONS

    @extend_schema(summary="Consultar un ingreso", responses={200: IngresoSerializer})
    def get(self, request, pk):
        entry = entry_queryset().filter(pk=pk).first()
        if entry is None:
            raise Http404("El ingreso no existe.")
        return Response(IngresoSerializer(entry).data)


@extend_schema(tags=["producto-terminado"])
class ExistenciasView(APIView):
    """Existencias de primera calidad en matriz: por referencia, filas por color y columnas por talla."""
    required_permissions = READ_PERMISSIONS

    @extend_schema(
        summary="Existencias por referencia, color y talla", parameters=[OpenApiParameter("referencia", int, description="Id de la referencia")],
        responses={200: ExistenciasReferenciaSerializer(many=True)},
        description="Incluye las variantes sin saldo (en cero) de las referencias activas. Las marras no se cuentan aquí.",
    )
    def get(self, request):
        reference = request.query_params.get("referencia")
        if reference and not reference.isdigit():
            return Response({"referencia": ["Valor inválido."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(services.stock_matrix(int(reference) if reference else None))


@extend_schema(tags=["producto-terminado"])
class MovimientoListView(APIView):
    """Libro de movimientos del producto terminado: de solo lectura."""
    required_permissions = READ_PERMISSIONS

    @extend_schema(
        summary="Listar los movimientos (filtros: referencia, variante, tipo, desde, hasta, limit)",
        parameters=[
            LIMIT_PARAM, OpenApiParameter("referencia", int, description="Id de la referencia"),
            OpenApiParameter("variante", int, description="Id de la variante (talla y color)"),
            OpenApiParameter("tipo", str, description="ENTRADA_PRODUCCION, AJUSTE o SALIDA_VENTA"),
            OpenApiParameter("desde", str, description="Fecha mínima (AAAA-MM-DD)"), OpenApiParameter("hasta", str, description="Fecha máxima"),
        ],
        responses={200: MovimientoTerminadoSerializer(many=True)},
    )
    def get(self, request):
        movements = MovimientoTerminado.objects.select_related("variante__referencia", "ingreso", "lote", "usuario")
        movements = apply_filters(
            movements, request.query_params,
            [("referencia", "variante__referencia_id"), ("variante", "variante_id"), ("tipo", "tipo"),
             ("desde", "created_at__date__gte"), ("hasta", "created_at__date__lte")],
        )
        return Response(MovimientoTerminadoSerializer(limited(movements, request), many=True).data)
