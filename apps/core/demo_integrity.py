"""Comprobación de coherencia de los datos de demostración (TE-183).

Revisa que la base cuente una sola historia que se pueda seguir por todos los módulos:

- **Libros:** en inventario, producto terminado y cartera cada movimiento cuadra (saldo después = saldo antes ± cantidad), cada
  movimiento parte del saldo en que quedó el anterior y el saldo guardado es el del último movimiento. Se incluyen los registros con
  borrado lógico para no esconder ningún movimiento. Las cantidades se comparan exactas (`Decimal` o enteros).
- **Huérfanos:** ningún registro activo cuelga de un padre borrado (lote sin orden, inspección sin lote, ingreso sin inspección,
  factura sin cliente, línea sin factura, guía sin factura) y ningún movimiento de producto terminado queda sin documento.
- **Inventario = Producto Terminado (HU 6.5):** cada referencia activa tiene su producto terminado enlazado en Inventario y lo que
  Inventario muestra de él es la suma de sus existencias por talla y color.
- **Trazabilidad (HU 7.6):** al menos un lote se recorre completo, de la orden al ingreso, y al menos una factura llega a un lote de
  origen.
"""
from collections import defaultdict
from decimal import Decimal


class _FullAccess:
    """Lector con todos los permisos de consulta, solo para recorrer la trazabilidad desde la comprobación."""

    @staticmethod
    def has_permission_code(code):
        return True


def _chain(rows, label, before, after, delta):
    """Revisa un libro ordenado: cada fila cuadra y parte del saldo de la anterior. Devuelve (problemas, saldo final)."""
    problems, previous = [], None
    for row in rows:
        if getattr(row, after) != getattr(row, before) + delta(row):
            problems.append(f"{label}: el movimiento {row.pk} no cuadra ({getattr(row, before)} → {getattr(row, after)}).")
        if previous is not None and getattr(row, before) != previous:
            problems.append(f"{label}: el movimiento {row.pk} parte de {getattr(row, before)} y el anterior dejó {previous}.")
        previous = getattr(row, after)
    return problems, previous


def inventory_ledger():
    from apps.inventory import catalog
    from apps.inventory.models import Movimiento, Producto

    by_product = defaultdict(list)
    for row in Movimiento.all_objects.order_by("id"):
        by_product[row.producto_id].append(row)
    problems = []
    for product in Producto.all_objects.order_by("id"):
        rows = by_product.get(product.id, [])
        found, last = _chain(
            rows, f"Inventario {product.codigo}", "stock_antes", "stock_despues",
            lambda row: row.cantidad if row.tipo == catalog.ENTRY else -row.cantidad,
        )
        problems += found
        expected = last if last is not None else Decimal("0")
        if product.stock_actual != expected:
            problems.append(f"Inventario {product.codigo}: el saldo guardado es {product.stock_actual} y el libro dice {expected}.")
    return problems


def finished_ledger():
    from apps.finished.models import MovimientoTerminado, StockTerminado

    by_variant = defaultdict(list)
    for row in MovimientoTerminado.all_objects.order_by("id"):
        by_variant[row.variante_id].append(row)
    stock = {row.variante_id: row.cantidad for row in StockTerminado.all_objects.all()}
    problems = []
    for variant_id in sorted(set(by_variant) | set(stock)):
        found, last = _chain(
            by_variant.get(variant_id, []), f"Producto terminado (variante {variant_id})", "saldo_antes", "saldo_despues",
            lambda row: row.cantidad,
        )
        problems += found
        if stock.get(variant_id, 0) != (last or 0):
            problems.append(
                f"Producto terminado (variante {variant_id}): el saldo guardado es {stock.get(variant_id, 0)} y el libro dice {last or 0}."
            )
    return problems


def receivables_ledger():
    from apps.sales.models import MovimientoCartera, SaldoFinanciero

    rows = list(MovimientoCartera.all_objects.order_by("id"))
    problems, last = _chain(rows, "Cartera", "saldo_antes", "saldo_despues", lambda row: row.monto)
    if rows and rows[0].saldo_antes != 0:
        problems.append(f"Cartera: el primer movimiento parte de {rows[0].saldo_antes}, no de cero.")
    box = SaldoFinanciero.objects.filter(nombre="Caja General").first()
    if box is not None and box.saldo_actual != (last or 0):
        problems.append(f"Cartera: el saldo financiero es {box.saldo_actual} y el libro dice {last or 0}.")
    return problems


def inventory_matches_finished():
    from apps.finished.models import StockTerminado
    from apps.inventory.models import Producto
    from apps.references import catalog as reference_catalog
    from apps.references.models import Referencia

    totals = defaultdict(int)
    for row in StockTerminado.objects.filter(variante__deleted_at__isnull=True).values("variante__referencia_id", "cantidad"):
        totals[row["variante__referencia_id"]] += row["cantidad"]
    problems = []
    for reference in Referencia.objects.filter(estado=reference_catalog.ACTIVE).order_by("codigo"):
        linked = list(Producto.objects.filter(referencia=reference))
        if len(linked) != 1:
            problems.append(f"Referencia {reference.codigo}: tiene {len(linked)} productos terminados enlazados en Inventario (debe ser 1).")
            continue
        shown = linked[0].stock_efectivo
        if shown != totals.get(reference.id, 0):
            problems.append(f"Referencia {reference.codigo}: Inventario muestra {shown} y Producto Terminado suma {totals.get(reference.id, 0)}.")
    return problems


def orphans():
    from apps.finished.models import IngresoTerminado, MovimientoTerminado
    from apps.production.models import Lote
    from apps.quality.models import Inspeccion
    from apps.sales.models import DetalleVenta, FacturaVenta
    from apps.shipping.models import Guia

    checks = [
        ("Lote", Lote.objects.filter(orden__deleted_at__isnull=False)),
        ("Inspección", Inspeccion.objects.filter(lote__deleted_at__isnull=False)),
        ("Ingreso de producto terminado", IngresoTerminado.objects.filter(inspeccion__deleted_at__isnull=False)),
        ("Factura", FacturaVenta.objects.filter(cliente__deleted_at__isnull=False)),
        ("Línea de factura", DetalleVenta.objects.filter(factura__deleted_at__isnull=False)),
        ("Guía", Guia.objects.filter(factura__deleted_at__isnull=False)),
        ("Movimiento de producto terminado sin documento",
         MovimientoTerminado.objects.filter(ingreso__isnull=True, ajuste__isnull=True, factura__isnull=True)),
    ]
    return [f"{label}: {queryset.count()} registro(s) huérfano(s)." for label, queryset in checks if queryset.exists()]


def traceability():
    from apps.finished.models import IngresoTerminado
    from apps.production.models import Lote
    from apps.reports import trazabilidad
    from apps.sales.models import FacturaVenta

    reader = _FullAccess()
    problems = []
    lots = Lote.objects.filter(id__in=IngresoTerminado.objects.values("lote_id")).order_by("id")
    complete_lot = any(
        all(row.get("cantidad") is not None and not row.get("sin_justificar") for row in trazabilidad.lot_trace(reader, lot.codigo)["conciliacion"])
        for lot in lots
    )
    if not complete_lot:
        problems.append("Trazabilidad: ningún lote se recorre completo de la orden al ingreso a producto terminado.")
    invoice_to_lot = any(
        any(line["lotes"] for line in trazabilidad.invoice_trace(reader, invoice.numero)["existencias"]["lotes_de_origen"])
        for invoice in FacturaVenta.objects.order_by("id")
    )
    if not invoice_to_lot:
        problems.append("Trazabilidad: ninguna factura llega a un lote de origen.")
    return problems


CHECKS = [
    ("Libro de inventario", inventory_ledger),
    ("Libro de producto terminado", finished_ledger),
    ("Libro de cartera", receivables_ledger),
    ("Inventario = Producto Terminado por referencia", inventory_matches_finished),
    ("Registros huérfanos", orphans),
    ("Trazabilidad de punta a punta", traceability),
]


def run_checks():
    """Corre todas las comprobaciones. Devuelve una lista de `(nombre, problemas)`; una lista de problemas vacía es que pasó."""
    return [(name, check()) for name, check in CHECKS]
