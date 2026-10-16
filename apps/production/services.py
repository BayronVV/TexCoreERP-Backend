"""
Planificación de producción (HU 4.1 / RF10): verifica si hay material en el almacén antes de crear una orden.

Todo es una simulación de solo lectura: no reserva ni descuenta stock. La orden vuelve a verificar bajo
bloqueo de filas cuando se crea (`inventory.services.create_order`), porque el saldo puede cambiar entre la
vista previa y el guardado. El consumo sale de la ficha técnica (`references.fichas`).
"""
import re
from decimal import ROUND_FLOOR

from apps.inventory import catalog as inventory_catalog
from apps.inventory.services import fail
from apps.references import catalog as reference_catalog
from apps.references import fichas
from apps.references.models import Referencia

from . import catalog


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
