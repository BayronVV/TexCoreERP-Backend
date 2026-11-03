"""
Inventario de producto terminado (HU 6.2 / RF21).

- Solo se ingresa lo que una inspección aprobó como apto (HU 6.1) y una sola vez por inspección. El ingreso reparte las aptas
  por variante (talla y color) de la referencia del lote, y la suma debe ser exactamente las aptas. Lo planificado en el lote
  se guarda como dato de comparación, no como regla. Las marras no entran a este saldo.
- Todo es una sola transacción con la inspección bloqueada: el ingreso, el saldo de cada variante y su movimiento en el libro.
  Si algo falla no queda nada ni se gasta el consecutivo. El saldo nunca es negativo y solo cambia con un movimiento.
"""
import re
from collections import defaultdict

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.inventory import catalog as inventory_catalog
from apps.inventory.services import fail, next_code
from apps.production.models import LoteTalla
from apps.quality.models import Inspeccion
from apps.references import catalog as reference_catalog
from apps.references.models import Variante

from . import catalog
from .models import IngresoLinea, IngresoTerminado, MovimientoTerminado, StockTerminado


class AlreadyReceived(APIException):
    """409: la inspección ya fue ingresada (otra persona pudo hacerlo un momento antes)."""
    status_code = 409
    default_detail = "La inspección ya fue ingresada al inventario."
    default_code = "ya_ingresada"


# --- Pendientes ---------------------------------------------------------------------------------------------------

def pending_entries():
    """Inspecciones con aptas que todavía no se ingresaron, de órdenes no anuladas."""
    return (
        Inspeccion.objects.select_related("lote__orden__referencia")
        .filter(aptas__gte=1)
        .exclude(lote__orden__orden_salida__estado=inventory_catalog.STATUS_CANCELLED)
        .annotate(ya_ingresada=Exists(IngresoTerminado.objects.filter(inspeccion=OuterRef("pk"))))
        .filter(ya_ingresada=False)
        .order_by("id")
    )


def variants_of(reference_ids):
    """`{id de la referencia: [variantes]}` con una sola consulta."""
    grouped = defaultdict(list)
    for variant in Variante.objects.filter(referencia_id__in=list(reference_ids)).order_by("id"):
        grouped[variant.referencia_id].append(variant)
    return grouped


def planned_by_lot(lot_ids):
    """`{id del lote: {id de la variante: cantidad planificada}}` con una sola consulta."""
    grouped = defaultdict(dict)
    for row in LoteTalla.objects.filter(lote_id__in=list(lot_ids)):
        grouped[row.lote_id][row.variante_id] = row.cantidad
    return grouped


# --- Ingreso ------------------------------------------------------------------------------------------------------

def whole(value, message, field, minimum=1):
    """Entero a partir de lo que llegue en el JSON (rechaza booleanos, decimales y texto)."""
    text = "" if isinstance(value, bool) else str(value).strip()
    if not re.fullmatch(r"\d+", text) or int(text) < minimum:
        fail(message, field)
    return int(text)


def clean_lines(lines, reference_id):
    """Líneas del ingreso `[(variante, cantidad)]`: variantes de la referencia del lote, sin repetir y con enteros mayores que cero."""
    if not isinstance(lines, list) or not lines:
        fail("Indica cuántas prendas entran de cada talla.", "lineas")
    if len(lines) > catalog.MAX_ENTRY_LINES:
        fail(f"Se admiten máximo {catalog.MAX_ENTRY_LINES} variantes por ingreso.", "lineas")
    rows, seen = [], set()
    for number, item in enumerate(lines, start=1):
        if not isinstance(item, dict):
            fail(f"La fila {number} necesita la variante y la cantidad.", "lineas")
        variant_id = item.get("variante")
        if isinstance(variant_id, bool) or not isinstance(variant_id, int):
            fail(f"Elige la talla y el color de la fila {number}.", "lineas")
        if variant_id in seen:
            fail("Una talla y color no puede repetirse: suma sus cantidades en una sola fila.", "lineas")
        seen.add(variant_id)
        variant = Variante.objects.filter(pk=variant_id, referencia_id=reference_id).first()
        if variant is None:
            fail(f"La talla y color de la fila {number} no es de la referencia del lote.", "lineas")
        amount = whole(item.get("cantidad"), f"La cantidad de {variant.talla} {variant.color} debe ser un entero mayor que cero.", "lineas")
        rows.append((variant, amount))
    return rows


def lock_stock(variant_ids):
    """Saldos de las variantes, bloqueados en orden de id para que dos ingresos simultáneos no se bloqueen entre sí.
    Si una variante todavía no tiene fila de saldo, se crea con cantidad cero.
    """
    stocks = {}
    for variant_id in sorted(variant_ids):
        stock = StockTerminado.objects.select_for_update().filter(variante_id=variant_id).first()
        if stock is None:
            try:
                with transaction.atomic():
                    stock = StockTerminado.objects.create(variante_id=variant_id, cantidad=0)
            except IntegrityError:  # otro ingreso la creó un instante antes
                stock = StockTerminado.objects.select_for_update().get(variante_id=variant_id)
        stocks[variant_id] = stock
    return stocks


@transaction.atomic
def register_entry(*, user, inspeccion_id, lineas, ubicacion="", observaciones="", fecha=None):
    """Ingresa al inventario final las aptas de una inspección, repartidas por talla y color."""
    if isinstance(inspeccion_id, bool) or not isinstance(inspeccion_id, int):
        fail("Elige la inspección que vas a ingresar.", "inspeccion")
    inspection = (
        Inspeccion.objects.select_for_update().select_related("lote__orden__orden_salida", "lote__orden__referencia")
        .filter(pk=inspeccion_id).first()
    )
    if inspection is None:
        fail("La inspección no existe.", "inspeccion")
    lot = inspection.lote
    if lot.orden.orden_salida.estado == inventory_catalog.STATUS_CANCELLED:
        fail(f"La orden {lot.orden.codigo} está anulada: no se ingresan sus lotes.", "inspeccion")
    if inspection.aptas < 1:
        fail(f"La inspección {inspection.codigo} no tiene prendas aptas que ingresar.", "inspeccion")
    if IngresoTerminado.objects.filter(inspeccion=inspection).exists():
        raise AlreadyReceived({"inspeccion": [f"La inspección {inspection.codigo} ya fue ingresada al inventario."]})

    rows = clean_lines(lineas, lot.orden.referencia_id)
    total = sum(amount for _, amount in rows)
    if total != inspection.aptas:
        difference = inspection.aptas - total
        missing = abs(difference)
        word = ("falta" if missing == 1 else "faltan") if difference > 0 else ("sobra" if missing == 1 else "sobran")
        fail(f"Las tallas suman {total} y la inspección trae {inspection.aptas} aptas: {word} {missing}.", "lineas", aptas=inspection.aptas)

    planned = planned_by_lot([lot.pk])[lot.pk]
    entry = IngresoTerminado.objects.create(
        codigo=next_code(catalog.ENTRY_PREFIX), inspeccion=inspection, lote=lot, aptas=inspection.aptas,
        ubicacion=str(ubicacion or "").strip()[:80], observaciones=str(observaciones or "").strip()[:500], recibido_por=user,
        fecha=fecha or timezone.localdate(),
    )
    stocks = lock_stock([variant.id for variant, _ in rows])
    for variant, amount in sorted(rows, key=lambda row: row[0].id):
        stock = stocks[variant.id]
        before = stock.cantidad
        stock.cantidad = before + amount
        stock.save(update_fields=["cantidad", "updated_at"])
        MovimientoTerminado.objects.create(
            variante=variant, tipo=catalog.ENTRY_PRODUCTION, cantidad=amount, saldo_antes=before, saldo_despues=stock.cantidad,
            ingreso=entry, lote=lot, usuario=user, motivo=f"Ingreso {entry.codigo} del lote {lot.codigo}",
        )
        IngresoLinea.objects.create(
            ingreso=entry, variante=variant, talla=variant.talla, color=variant.color, cantidad=amount, planificada=planned.get(variant.id),
        )
    return entry


# --- Existencias en matriz ----------------------------------------------------------------------------------------

def size_key(size):
    """Orden de las tallas: las numéricas por valor y después las demás por nombre."""
    return (0, int(size), "") if str(size).isdigit() else (1, 0, str(size))


def stock_matrix(reference_id=None):
    """Existencias por referencia: filas por color y columnas por talla, con los totales.
    Incluye las variantes sin saldo (en cero) de las referencias activas y de las que aún tienen prendas.
    """
    stocks = {row.variante_id: row.cantidad for row in StockTerminado.objects.all()}
    variants = Variante.objects.select_related("referencia").filter(
        Q(referencia__estado=reference_catalog.ACTIVE) | Q(pk__in=[vid for vid, qty in stocks.items() if qty > 0])
    )
    if reference_id:
        variants = variants.filter(referencia_id=reference_id)
    grouped = defaultdict(list)
    for variant in variants.order_by("referencia__nombre", "id"):
        grouped[variant.referencia].append(variant)
    result = []
    for reference, items in grouped.items():
        sizes = sorted({variant.talla for variant in items}, key=size_key)
        colors = defaultdict(dict)
        for variant in items:
            colors[variant.color][variant.talla] = {"variante": variant.id, "cantidad": stocks.get(variant.id, 0)}
        rows = [
            {"color": color, "tallas": by_size, "total": sum(cell["cantidad"] for cell in by_size.values())}
            for color, by_size in sorted(colors.items())
        ]
        result.append({
            "referencia": reference.id, "codigo": reference.codigo, "nombre": reference.nombre, "tallas": sizes, "colores": rows,
            "total": sum(row["total"] for row in rows),
        })
    return result
