"""
Planificación de producción (HU 4.1 / RF10): verifica si hay material en el almacén antes de crear una orden.

Todo es una simulación de solo lectura: no reserva ni descuenta stock. La orden vuelve a verificar bajo
bloqueo de filas cuando se crea (`inventory.services.create_order`), porque el saldo puede cambiar entre la
vista previa y el guardado. El consumo sale de la ficha técnica (`references.fichas`).
"""
import re
from decimal import ROUND_FLOOR

from django.db import transaction
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory import services as inventory_services
from apps.inventory.services import fail
from apps.references import catalog as reference_catalog
from apps.references import fichas
from apps.references.models import Referencia, Variante

from . import catalog, resources, tracking
from .models import Lote, LoteTalla, OrdenProduccion


def get_reference(reference_id):
    """La referencia a planificar: debe existir y estar activa."""
    reference = Referencia.objects.filter(pk=reference_id, estado=reference_catalog.ACTIVE).first()
    if reference is None:
        fail("La referencia no existe o no está activa.", "referencia")
    return reference


def clean_lots(lots, total):
    """Valida cómo se divide el total en lotes y devuelve los tamaños como enteros (o None si no se pidió).
    Cada lote es un entero de al menos 1, hay como máximo `MAX_LOTS` y la suma debe ser exactamente el total.
    """
    if lots is None:
        return None
    if not isinstance(lots, list) or not lots:
        fail("Indica al menos un lote.", "lotes")
    if len(lots) > catalog.MAX_LOTS:
        fail(f"Se admiten máximo {catalog.MAX_LOTS} lotes.", "lotes")
    sizes = []
    for number, item in enumerate(lots, start=1):
        text = "" if isinstance(item, bool) else str(item).strip()
        if not re.fullmatch(r"\d+", text) or int(text) < 1:
            fail(f"El lote {number} debe ser un número entero de prendas mayor que cero.", "lotes")
        sizes.append(int(text))
    difference = total - sum(sizes)
    if difference:
        word = "faltan" if difference > 0 else "sobran"
        fail(f"Los lotes suman {sum(sizes)} y el total es {total}: {word} {abs(difference)}.", "lotes")
    return sizes


def producible(line):
    """Cuántas prendas completas alcanzan con el saldo de este material (ficha con merma incluida).
    Es coherente con `required_total`: para n prendas hay material si, y solo si, n ≤ saldo / consumo bruto
    (en unidades enteras cuenta solo la parte entera del saldo, porque el requerido se redondea hacia arriba).
    """
    stock = line.producto.stock_actual
    if line.producto.unidad in inventory_catalog.WHOLE_UNITS:
        stock = stock.to_integral_value(rounding=ROUND_FLOOR)
    return int((stock / fichas.gross_per_garment(line)).to_integral_value(rounding=ROUND_FLOOR))


def max_producible(lines):
    """El máximo de prendas que se pueden fabricar con el stock actual y el material que lo limita (cuello de
    botella; si hay empate, el primero por nombre). El máximo se topa en `MAX_GARMENTS`, como la simulación.
    """
    limiting = min(lines, key=producible)
    best = min(producible(limiting), reference_catalog.MAX_GARMENTS)
    product = limiting.producto
    return best, {
        "producto": product.id, "codigo": product.codigo, "nombre": product.nombre, "unidad": product.unidad,
        "disponible": product.stock_actual, "maximo": producible(limiting),
    }


def lot_coverage(lines, sizes):
    """Hasta qué lote alcanza el stock, de forma acumulada: los lotes de una orden comparten el mismo material,
    así que el lote k se cubre si el stock alcanza para los lotes 1..k juntos (no cada uno por separado).
    """
    coverage, accumulated = [], 0
    for number, size in enumerate(sizes, start=1):
        accumulated += size
        short = [
            line.producto.nombre for line in lines
            if fichas.required_total(line, accumulated) > line.producto.stock_actual
        ]
        coverage.append({
            "numero": number, "cantidad": size, "acumulado": accumulated, "cubierto": not short, "faltantes": short,
        })
    return coverage


def simulate(reference, garments, lots=None):
    """Simula producir `garments` prendas de la referencia, opcionalmente divididas en `lots` (lista de tamaños).

    Devuelve el cruce de la ficha con el saldo (requerido, disponible y falta por material), si es viable, el
    máximo producible con el stock actual, su cuello de botella y, si hay lotes, la cobertura acumulada de cada uno.
    """
    sizes = clean_lots(lots, garments)
    lines = fichas.ficha_lines(reference)
    if not lines:
        fail("La referencia no tiene ficha técnica.", "referencia")
    result = fichas.requirements_for(lines, garments)
    best, bottleneck = max_producible(lines)
    coverage = lot_coverage(lines, sizes) if sizes else None
    return {
        "referencia": {"id": reference.id, "codigo": reference.codigo, "nombre": reference.nombre},
        **result,
        "maximo_producible": best,
        "cuello_de_botella": bottleneck,
        "lotes": coverage,
        "lotes_cubiertos": sum(1 for lot in coverage if lot["cubierto"]) if coverage else None,
    }


# --- Órdenes de producción y lotes (HU 4.2 / RF11 y RF12) ----------------------------------------------

def _whole(value, message, field):
    """Entero positivo a partir de lo que llegue en el JSON (rechaza booleanos, decimales y texto)."""
    text = "" if isinstance(value, bool) else str(value).strip()
    if not re.fullmatch(r"\d+", text) or int(text) < 1:
        fail(message, field)
    return int(text)


def clean_sizes(sizes, number, quantity, variants):
    """Valida las tallas de un lote: variantes de la referencia, sin repetir, cantidades enteras mayores que
    cero y que sumen justo las prendas del lote. Devuelve `[(variante, cantidad)]` (vacío si no se indicaron).
    """
    if sizes in (None, []):
        return []
    if not isinstance(sizes, list):
        fail(f"Las tallas del lote {number} deben ser una lista.", "lotes")
    picked, total = {}, 0
    for item in sizes:
        if not isinstance(item, dict):
            fail(f"Cada talla del lote {number} necesita la variante y la cantidad.", "lotes")
        variant = variants.get(item.get("variante")) if isinstance(item.get("variante"), int) else None
        if variant is None or isinstance(item.get("variante"), bool):
            fail(f"Una talla del lote {number} no es una variante de la referencia.", "lotes")
        if variant.id in picked:
            fail(f"La talla {variant.talla} {variant.color} se repite en el lote {number}.", "lotes")
        amount = _whole(item.get("cantidad"), f"La cantidad de {variant.talla} {variant.color} en el lote {number} "
                                               "debe ser un entero mayor que cero.", "lotes")
        picked[variant.id] = (variant, amount)
        total += amount
    if total != quantity:
        word = "faltan" if quantity > total else "sobran"
        fail(f"Las tallas del lote {number} suman {total} y el lote es de {quantity}: {word} {abs(quantity - total)}.",
             "lotes")
    return list(picked.values())


def clean_order_lots(lots, total, reference):
    """Lotes de una orden con sus tallas: `[{cantidad, tallas: [(variante, cantidad)]}]`.
    Sin `lotes` se crea un único lote con todo el total. Cada elemento es `{cantidad, tallas?}`; los tamaños
    siguen las mismas reglas que la simulación (`clean_lots`).
    """
    if lots is None:
        return [{"cantidad": total, "tallas": []}]
    if not isinstance(lots, list) or not lots:
        fail("Indica al menos un lote.", "lotes")
    if not all(isinstance(item, dict) for item in lots):
        fail("Cada lote debe indicar su cantidad de prendas.", "lotes")
    sizes = clean_lots([item.get("cantidad") for item in lots], total)
    variants = {variant.id: variant for variant in Variante.objects.filter(referencia=reference)}
    return [
        {"cantidad": size, "tallas": clean_sizes(item.get("tallas"), number, size, variants)}
        for number, (item, size) in enumerate(zip(lots, sizes), start=1)
    ]


@transaction.atomic
def create_production_order(*, user, referencia_id, cantidad, producto_resultado_id, lotes=None, fecha_salida=None,
                            responsable="", observaciones=""):
    """Crea la orden de producción de `cantidad` prendas de una referencia, dividida en lotes con sus tallas.

    Todo ocurre en una sola transacción: la salida de inventario (que descuenta el material de la ficha y
    guarda el estado y el consecutivo OP) y, colgando de ella, la orden, sus lotes y sus tallas. Si algo falla,
    como falta de material, no queda nada ni se gasta el número.
    """
    garments = fichas.parse_garments(cantidad)
    reference = get_reference(referencia_id)
    ficha = fichas.ficha_lines(reference)
    if not ficha:
        fail("La referencia no tiene ficha técnica: defínela antes de crear la orden.", "referencia")
    parts = clean_order_lots(lotes, garments, reference)

    exit_order = inventory_services.create_order(
        user=user, tipo=inventory_catalog.ORDER_PRODUCTION, fecha_salida=fecha_salida or timezone.localdate(),
        responsable=responsable.strip() or user.get_full_name() or user.email, referencia_id=reference.id,
        producto_resultado_id=producto_resultado_id, cantidad_prendas=garments, observaciones=observaciones,
        lineas=[{"producto": line.producto_id, "cantidad": fichas.required_total(line, garments)} for line in ficha],
    )
    order = OrdenProduccion.objects.create(
        orden_salida=exit_order, codigo=exit_order.codigo, referencia=reference, cantidad=garments, creado_por=user,
    )
    created_lots = []
    for number, part in enumerate(parts, start=1):
        lot = Lote.objects.create(
            orden=order, numero=number, codigo=f"{order.codigo}-L{number:02d}", cantidad=part["cantidad"],
        )
        created_lots.append(lot)
        LoteTalla.objects.bulk_create([
            LoteTalla(lote=lot, variante=variant, talla=variant.talla, color=variant.color, cantidad=amount)
            for variant, amount in part["tallas"]
        ])
    tracking.create_stages(created_lots)  # cada lote nace con sus etapas pendientes (HU 4.3)
    return order


@transaction.atomic
def cancel_production_order(*, user, order_id, motivo):
    """Anula la orden de producción: devuelve el material al inventario (la salida pasa a ANULADA)."""
    order = OrdenProduccion.objects.filter(pk=order_id).first()
    if order is None:
        fail("La orden no existe.", "orden")
    inventory_services.cancel_order(user=user, order_id=order.orden_salida_id, motivo=motivo)
    resources.close_for_order(order)  # los operarios y máquinas quedan libres, con su historial
    return order
