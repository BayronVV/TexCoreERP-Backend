"""
Órdenes de compra y recepción de mercancía.

- Una orden nace en borrador (la crea y edita el Jefe de Producción), la aprueba el Gerente y se recibe contra ella en el
  almacén. Se puede cancelar mientras no tenga recepciones y, si lo pendiente ya no va a llegar, cerrar con un motivo.
- Recibir es un ingreso al almacén: cada fila pasa por `inventory.services.register_entry`, así que el stock, el costo
  promedio ponderado y el kardex salen de la misma regla que el ingreso suelto. Toda la recepción es una sola transacción:
  si una fila falla, no queda ninguna. Se bloquea la orden y los productos en orden de id, para que dos recepciones
  simultáneas no se bloqueen entre sí.
- Se puede recibir hasta un 5 % más de lo pendiente de cada línea (`catalog.OVERAGE_TOLERANCE`). Quien creó la orden no la recibe.
- Sin orden, una recepción suelta registra varios productos de un proveedor en un solo paso.
"""
from collections import defaultdict
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory import catalog as inventory_catalog
from apps.inventory import services as inventory_services
from apps.inventory.models import Producto, Proveedor
from apps.inventory.services import (
    check_date,
    fail,
    next_code,
    parse_cost,
    parse_quantity,
)

from . import catalog
from .models import LineaCompra, OrdenCompra, Recepcion, RecepcionLinea

CENTS = Decimal("0.01")


# --- Consultas ----------------------------------------------------------------------------------------------------

def received_by_line(line_ids):
    """`{id de la línea: cantidad recibida}` sumando las recepciones, con una sola consulta."""
    rows = RecepcionLinea.objects.filter(linea_compra_id__in=list(line_ids)).values("linea_compra_id").annotate(total=Sum("cantidad"))
    return {row["linea_compra_id"]: row["total"] for row in rows}


def pending_quantity(line, received):
    """Lo que falta por recibir de una línea (nunca negativo)."""
    return max(line.cantidad_pedida - received.get(line.id, Decimal(0)), Decimal(0))


def allowed_quantity(line, received):
    """Lo máximo que se puede recibir ahora de la línea: lo pendiente más la tolerancia de exceso."""
    return (pending_quantity(line, received) * (1 + catalog.OVERAGE_TOLERANCE)).quantize(CENTS, rounding=ROUND_DOWN)


# --- Validación ---------------------------------------------------------------------------------------------------

def _message(error):
    detail = error.detail
    first = next(iter(detail.values())) if isinstance(detail, dict) else detail
    first = first[0] if isinstance(first, list) else first
    return str(first)


def _line_error(label, number, error):
    """Vuelve a lanzar el error de una fila con su número, para que la pantalla diga cuál falló."""
    fail(f"{label} {number}: {_message(error)}", "lineas")


def _rows(value, label):
    if not isinstance(value, list) or not value:
        fail("Indica al menos un producto.", "lineas")
    if len(value) > catalog.MAX_LINES:
        fail(f"Se admiten máximo {catalog.MAX_LINES} filas.", "lineas")
    for number, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            fail(f"{label} {number}: datos inválidos.", "lineas")
    return value


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _supplier(supplier_id):
    supplier = Proveedor.objects.filter(pk=supplier_id).first() if _int(supplier_id) else None  # solo activos
    if supplier is None:
        fail("El proveedor no existe o está archivado.", "proveedor")
    return supplier


def clean_order_lines(rows):
    """Valida los materiales de la orden y devuelve `[(producto, cantidad, precio)]`. Solo materia prima e insumos, sin repetir."""
    rows = _rows(rows, "Línea")
    ids = [row.get("producto") for row in rows]
    if any(_int(product_id) is None for product_id in ids):
        fail("Cada línea debe indicar el producto.", "lineas")
    if len(set(ids)) != len(ids):
        fail("Un producto no puede repetirse en la orden: suma sus cantidades en una sola línea.", "lineas")
    products = {product.id: product for product in Producto.objects.filter(id__in=ids)}
    cleaned = []
    for number, row in enumerate(rows, start=1):
        product = products.get(row["producto"])
        if product is None:
            fail(f"Línea {number}: el producto no existe.", "lineas")
        if product.tipo not in inventory_catalog.PURCHASED_TYPES:
            fail(f"Línea {number}: {product.nombre} no se compra (solo materia prima e insumos).", "lineas")
        try:
            quantity = parse_quantity(row.get("cantidad"), product.unidad, field="lineas")
            price = parse_cost(row.get("precio_pactado"), field="lineas")
        except ValidationError as error:
            _line_error("Línea", number, error)
        cleaned.append((product, quantity, price))
    return cleaned


# --- Órdenes ------------------------------------------------------------------------------------------------------

def _check_dates(date, expected):
    check_date(date)
    if expected is not None and expected < date:
        fail("La fecha esperada no puede ser anterior a la fecha de la orden.", "fecha_esperada")


@transaction.atomic
def create_order(*, user, data):
    """Crea la orden de compra en borrador con código OC-0001."""
    supplier = _supplier(data.get("proveedor"))
    date = data.get("fecha") or timezone.localdate()
    _check_dates(date, data.get("fecha_esperada"))
    lines = clean_order_lines(data.get("lineas"))
    order = OrdenCompra.objects.create(
        codigo=next_code(catalog.ORDER_PREFIX), proveedor=supplier, fecha=date, fecha_esperada=data.get("fecha_esperada"),
        condiciones_pago=data.get("condiciones_pago", "").strip(), notas=data.get("notas", "").strip(),
        estado=catalog.DRAFT, creado_por=user,
    )
    LineaCompra.objects.bulk_create(
        [LineaCompra(orden=order, producto=product, cantidad_pedida=quantity, precio_pactado=price) for product, quantity, price in lines]
    )
    return order


def _locked_order(order_id):
    order = OrdenCompra.objects.select_for_update().filter(pk=order_id).first()
    if order is None:
        fail("La orden de compra no existe.", "orden")
    return order


@transaction.atomic
def update_order(*, order_id, data):
    """Edita una orden en borrador. Si se envían `lineas`, reemplazan a las anteriores. Una orden aprobada ya no se edita."""
    order = _locked_order(order_id)
    if order.estado != catalog.DRAFT:
        fail(f"La orden {order.codigo} está {catalog.ORDER_STATE_NAMES[order.estado].lower()}: solo se edita en borrador.", "orden")
    if "proveedor" in data:
        order.proveedor = _supplier(data["proveedor"])
    date = data.get("fecha") or order.fecha
    expected = data.get("fecha_esperada", order.fecha_esperada)
    _check_dates(date, expected)
    order.fecha, order.fecha_esperada = date, expected
    for field in ("condiciones_pago", "notas"):
        if field in data:
            setattr(order, field, data[field].strip())
    lines = clean_order_lines(data["lineas"]) if "lineas" in data else None
    order.save()
    if lines is not None:
        order.lineas.all().delete()  # borrado lógico: el historial de la orden conserva lo que había
        LineaCompra.objects.bulk_create(
            [LineaCompra(orden=order, producto=product, cantidad_pedida=quantity, precio_pactado=price) for product, quantity, price in lines]
        )
    return order


@transaction.atomic
def approve_order(*, user, order_id):
    """El Gerente aprueba la orden: pasa de borrador a aprobada y desde ese momento se puede recibir."""
    order = _locked_order(order_id)
    if order.estado != catalog.DRAFT:
        fail(f"La orden {order.codigo} está {catalog.ORDER_STATE_NAMES[order.estado].lower()}: solo se aprueba un borrador.", "orden")
    if not order.lineas.exists():
        fail("La orden no tiene líneas.", "orden")
    order.estado, order.aprobado_por, order.aprobada_at = catalog.APPROVED, user, timezone.now()
    order.save(update_fields=["estado", "aprobado_por", "aprobada_at", "updated_at"])
    return order


def _reason(motivo):
    text = (motivo or "").strip()
    if not text:
        fail("Indica el motivo.", "motivo")
    return text[:255]


@transaction.atomic
def cancel_order(*, order_id, motivo):
    """Cancela una orden en borrador o aprobada que todavía no tiene recepciones."""
    order = _locked_order(order_id)
    if order.estado not in {catalog.DRAFT, catalog.APPROVED}:
        hint = " Si lo pendiente ya no llegará, ciérrala con un motivo." if order.estado == catalog.PARTIAL else ""
        fail(f"La orden {order.codigo} está {catalog.ORDER_STATE_NAMES[order.estado].lower()}: no se puede cancelar.{hint}", "orden")
    order.estado, order.motivo_cierre, order.cerrada_at = catalog.CANCELLED, _reason(motivo), timezone.now()
    order.save(update_fields=["estado", "motivo_cierre", "cerrada_at", "updated_at"])
    return order


@transaction.atomic
def close_order(*, order_id, motivo):
    """Cierra a mano una orden con recepciones parciales cuando lo pendiente ya no va a llegar."""
    order = _locked_order(order_id)
    if order.estado != catalog.PARTIAL:
        fail(f"Solo se cierra una orden con recepciones parciales; la {order.codigo} está {catalog.ORDER_STATE_NAMES[order.estado].lower()}.", "orden")
    order.estado, order.motivo_cierre, order.cerrada_at = catalog.CLOSED, _reason(motivo), timezone.now()
    order.save(update_fields=["estado", "motivo_cierre", "cerrada_at", "updated_at"])
    return order


# --- Recepción de mercancía ---------------------------------------------------------------------------------------

def _order_for_receipt(order_id, user):
    order = _locked_order(order_id) if _int(order_id) else fail("La orden de compra no existe.", "orden")
    if order.estado not in catalog.RECEIVABLE_STATES:
        fail(
            f"La orden {order.codigo} está {catalog.ORDER_STATE_NAMES[order.estado].lower()}: "
            "solo se recibe contra una orden aprobada o con recepciones parciales.", "orden",
        )
    if order.creado_por_id == user.id:
        fail("Quien creó la orden no puede registrar su recepción.", "orden")
    return order


def _prepare_receipt_rows(rows, order):
    """Valida las filas antes de escribir nada y devuelve `[(número, fila, línea de la orden, producto, cantidad)]`."""
    rows = _rows(rows, "Fila")
    lines = {line.id: line for line in order.lineas.select_related("producto")} if order else {}
    received = received_by_line(lines) if order else {}
    product_ids = []
    for number, row in enumerate(rows, start=1):
        if order:
            line = lines.get(row.get("linea"))
            if line is None:
                fail(f"Fila {number}: indica una línea de la orden {order.codigo}.", "lineas")
            product_ids.append(line.producto_id)
        else:
            if row.get("linea") is not None:
                fail(f"Fila {number}: una recepción sin orden no lleva línea.", "lineas")
            if _int(row.get("producto")) is None:
                fail(f"Fila {number}: indica el producto.", "lineas")
            product_ids.append(row["producto"])
    products = inventory_services.lock_products(sorted(set(product_ids)))  # en orden de id: sin bloqueos cruzados
    asked = defaultdict(Decimal)
    prepared = []
    for number, (row, product_id) in enumerate(zip(rows, product_ids, strict=True), start=1):
        product = products[product_id]
        if product.tipo not in inventory_catalog.PURCHASED_TYPES:
            fail(f"Fila {number}: {product.nombre} no se compra (solo materia prima e insumos).", "lineas")
        try:
            quantity = parse_quantity(row.get("cantidad"), product.unidad, field="lineas")
        except ValidationError as error:
            _line_error("Fila", number, error)
        line = lines.get(row.get("linea")) if order else None
        if line is not None:
            asked[line.id] += quantity
            allowed = allowed_quantity(line, received)
            if asked[line.id] > allowed:
                pending = pending_quantity(line, received)
                fail(
                    f"Fila {number}: de {product.nombre} faltan {inventory_services.format_quantity(pending, product.unidad)} "
                    f"y se puede recibir hasta {inventory_services.format_quantity(allowed, product.unidad)} "
                    f"(incluye el {int(catalog.OVERAGE_TOLERANCE * 100)} % de tolerancia).", "lineas",
                )
        prepared.append((number, row, line, product, quantity))
    return prepared


@transaction.atomic
def receive_goods(*, user, data):
    """Registra una recepción de mercancía (con orden de compra o suelta) y devuelve la recepción con sus filas.

    Cada fila lleva cantidad, lote y, si se conoce, el costo real por unidad; el costo alimenta el promedio ponderado.
    """
    documento = (data.get("documento") or "").strip()
    if not documento:
        fail("Indica el número de la remisión o la factura del proveedor.", "documento")
    order = _order_for_receipt(data["orden"], user) if data.get("orden") is not None else None
    supplier = order.proveedor if order else _supplier(data.get("proveedor"))
    date = data.get("fecha") or timezone.localdate()
    check_date(date)
    if order and date < order.fecha:
        fail("La recepción no puede ser anterior a la fecha de la orden.", "fecha")
    prepared = _prepare_receipt_rows(data.get("lineas"), order)

    receipt = Recepcion.objects.create(
        codigo=next_code(catalog.RECEIPT_PREFIX), orden=order, proveedor=supplier, documento=documento[:40], fecha=date,
        observaciones=(data.get("observaciones") or "").strip(), recibido_por=user,
    )
    note = f"Recepción {receipt.codigo} · documento {receipt.documento}"
    for number, row, line, product, quantity in sorted(prepared, key=lambda item: (item[3].id, item[0])):
        try:
            movement = inventory_services.register_entry(
                user=user, producto_id=product.id, cantidad=quantity, fecha=date, proveedor_id=supplier.id,
                orden_compra=order.codigo if order else "", lote=str(row.get("lote") or ""), observaciones=note,
                costo_unitario=row.get("costo_unitario"),
            )
        except ValidationError as error:
            _line_error("Fila", number, error)
        RecepcionLinea.objects.create(
            recepcion=receipt, linea_compra=line, producto=product, movimiento=movement, cantidad=quantity,
            lote=movement.lote, costo_unitario=movement.costo_unitario,
        )
    if order:
        received = received_by_line(line.id for line in order.lineas.all())
        complete = all(line.cantidad_pedida <= received.get(line.id, Decimal(0)) for line in order.lineas.all())
        order.estado = catalog.RECEIVED if complete else catalog.PARTIAL
        order.save(update_fields=["estado", "updated_at"])
    return receipt
