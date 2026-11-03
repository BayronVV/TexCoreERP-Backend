"""
Ajuste manual del producto terminado (HU 6.3 / RF22).

La Secretaria digita el conteo real de la bodega y el sistema calcula la diferencia; el ajuste no cambia el saldo "a mano":
escribe movimientos de tipo AJUSTE en el libro, así que el saldo sigue siendo la suma del libro.

- Todo es una sola transacción: el comprobante, sus líneas, el saldo y el movimiento de cada variante. Si algo falla no queda nada.
- Control optimista: cada línea trae el saldo que vio la persona. Con los saldos ya bloqueados, si alguno cambió (por ejemplo
  por un ingreso o una venta en curso) se responde 409 y no se guarda nada.
- Solo se guardan las líneas con diferencia. Los faltantes y los sobrantes se suman por separado, nunca se netean.
- Motivo de un catálogo cerrado con su signo; observación siempre obligatoria; una línea de más de 20 unidades pide más.
- El comprobante es inalterable: un error se corrige con otro ajuste. El token del formulario evita ajustar dos veces.
"""
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.inventory.services import fail, next_code
from apps.references.models import Variante

from . import catalog
from .models import AjusteLinea, AjusteTerminado, MovimientoTerminado
from .services import lock_stock, whole


class StockChanged(APIException):
    """409: el saldo de alguna variante cambió desde que la persona abrió el formulario."""
    status_code = 409
    default_detail = "El stock cambió mientras contabas: recarga la matriz y vuelve a contar."
    default_code = "stock_cambio"


class AlreadyAdjusted(APIException):
    """409: ese formulario ya generó su comprobante (doble clic o reintento)."""
    status_code = 409
    default_detail = "Este ajuste ya fue registrado."
    default_code = "ya_ajustado"


def clean_token(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        fail("Falta el identificador único del formulario: recarga la página.", "token")


def clean_adjust_lines(lines):
    """Líneas `[(variante, esperado, contado)]` con enteros desde cero, variantes que existen y sin repetir."""
    if not isinstance(lines, list) or not lines:
        fail("Indica el conteo real de al menos una talla.", "lineas")
    if len(lines) > catalog.MAX_ADJUST_LINES:
        fail(f"Se admiten máximo {catalog.MAX_ADJUST_LINES} variantes por ajuste.", "lineas")
    rows, seen = [], set()
    for number, item in enumerate(lines, start=1):
        if not isinstance(item, dict):
            fail(f"La fila {number} necesita la variante, el saldo esperado y el conteo.", "lineas")
        variant_id = item.get("variante")
        if isinstance(variant_id, bool) or not isinstance(variant_id, int):
            fail(f"Elige la talla y el color de la fila {number}.", "lineas")
        if variant_id in seen:
            fail("Una talla y color no puede repetirse en el mismo ajuste.", "lineas")
        seen.add(variant_id)
        expected = whole(item.get("esperado"), f"El saldo esperado de la fila {number} debe ser un entero desde cero.", "lineas", minimum=0)
        counted = whole(item.get("contado"), f"El conteo de la fila {number} debe ser un entero desde cero.", "lineas", minimum=0)
        rows.append((variant_id, expected, counted))
    variants = {variant.id: variant for variant in Variante.objects.filter(pk__in=seen)}
    if len(variants) != len(seen):
        fail("Alguna talla y color no existe.", "lineas")
    return [(variants[variant_id], expected, counted) for variant_id, expected, counted in rows]


def label(variant):
    return f"{variant.talla} {variant.color}"


def already_adjusted(adjustment):
    return AlreadyAdjusted({"detail": [f"Este ajuste ya se registró como {adjustment.codigo}."], "ajuste": adjustment.id, "codigo": adjustment.codigo})


@transaction.atomic
def _adjust(*, user, motivo, observacion, lineas, token, fecha=None):
    if motivo not in catalog.ADJUST_REASON_NAMES:
        fail("Elige el motivo del ajuste.", "motivo")
    observation = str(observacion or "").strip()
    if len(observation) < catalog.MIN_OBSERVATION:
        fail(f"Explica el ajuste en la observación (mínimo {catalog.MIN_OBSERVATION} caracteres).", "observacion")
    if len(observation) > 500:
        fail("La observación admite máximo 500 caracteres.", "observacion")
    rows = clean_adjust_lines(lineas)

    stocks = lock_stock([variant.id for variant, _, _ in rows])
    changed = [label(variant) for variant, expected, _ in rows if stocks[variant.id].cantidad != expected]
    if changed:
        raise StockChanged({"detail": [f"El stock cambió en: {', '.join(changed)}. Recarga la matriz y vuelve a contar."], "variantes": changed})

    changes = [(variant, stocks[variant.id].cantidad, counted) for variant, _, counted in rows if counted != stocks[variant.id].cantidad]
    if not changes:
        fail("No hay diferencias que ajustar: el conteo coincide con el sistema.", "lineas")

    sign = catalog.ADJUST_REASON_SIGNS[motivo]
    reason_name = catalog.ADJUST_REASON_NAMES[motivo]
    if sign == "-" and any(counted > before for _, before, counted in changes):
        fail(f"«{reason_name}» solo puede restar prendas: si hay sobrantes usa «Sobrante o hallazgo» o «Error de conteo».", "motivo")
    if sign == "+" and any(counted < before for _, before, counted in changes):
        fail(f"«{reason_name}» solo puede sumar prendas: si hay faltantes elige otro motivo.", "motivo")
    large = [variant for variant, before, counted in changes if abs(counted - before) > catalog.LARGE_ADJUSTMENT]
    if large:
        names = ", ".join(label(variant) for variant in large)
        if motivo == catalog.OTHER:
            fail(f"Un ajuste de más de {catalog.LARGE_ADJUSTMENT} unidades ({names}) necesita un motivo válido: «Otro» no se acepta.", "motivo")
        if len(observation) < catalog.MIN_OBSERVATION_LARGE:
            fail(
                f"Un ajuste de más de {catalog.LARGE_ADJUSTMENT} unidades ({names}) pide una observación de al menos "
                f"{catalog.MIN_OBSERVATION_LARGE} caracteres.", "observacion",
            )

    missing = sum(before - counted for _, before, counted in changes if counted < before)
    surplus = sum(counted - before for _, before, counted in changes if counted > before)
    adjustment = AjusteTerminado.objects.create(
        codigo=next_code(catalog.ADJUST_PREFIX), motivo=motivo, observacion=observation, realizado_por=user,
        fecha=fecha or timezone.localdate(), token=token, unidades_faltantes=missing, unidades_sobrantes=surplus,
    )
    for variant, before, counted in sorted(changes, key=lambda row: row[0].id):
        stock = stocks[variant.id]
        stock.cantidad = counted
        stock.save(update_fields=["cantidad", "updated_at"])
        difference = counted - before
        AjusteLinea.objects.create(
            ajuste=adjustment, variante=variant, talla=variant.talla, color=variant.color, stock_antes=before, stock_contado=counted,
            diferencia=difference,
        )
        MovimientoTerminado.objects.create(
            variante=variant, tipo=catalog.ADJUSTMENT, cantidad=difference, saldo_antes=before, saldo_despues=counted,
            ajuste=adjustment, usuario=user, motivo=f"Ajuste {adjustment.codigo}: {reason_name}",
        )
    return adjustment


def adjust_stock(*, user, motivo, observacion, lineas, token, fecha=None):
    """Corrige el stock contra el conteo físico y devuelve el comprobante. Un token repetido responde 409 con el comprobante ya creado."""
    token = clean_token(token)
    existing = AjusteTerminado.objects.filter(token=token).first()
    if existing is not None:
        raise already_adjusted(existing)
    try:
        return _adjust(user=user, motivo=motivo, observacion=observacion, lineas=lineas, token=token, fecha=fecha)
    except IntegrityError:  # otro envío con el mismo token ganó la carrera
        existing = AjusteTerminado.objects.filter(token=token).first()
        if existing is None:
            raise
        raise already_adjusted(existing)
