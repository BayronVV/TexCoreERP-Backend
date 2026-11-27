"""
Factura POS interna y descuento de inventario (HU 7.1 / RF23).

- Una factura se emite en una sola transacción: valida el stock, calcula montos, crea la factura y sus líneas, descuenta cada saldo
  y escribe un movimiento SALIDA_VENTA en el libro. Si algo falla no queda nada, ni siquiera el consecutivo.
- No se factura sin stock en cada talla y color (MSG-ERR-19): si faltan varias se listan todas. Los saldos se bloquean en orden de id,
  así que dos vendedores que piden las últimas unidades no se bloquean entre sí: gana el primero.
- Los montos los calcula siempre el servidor, en pesos enteros y con una sola regla de redondeo (mitad hacia arriba): cada línea
  redondea su descuento y su IVA, y la factura es la suma de sus líneas.
- El descuento lo decide el vendedor, con un tope por tipo de cliente, y el precio con descuento nunca baja del costo de fábrica.
- Una factura no se edita ni se borra: se anula con motivo, las unidades vuelven al inventario por el libro y el número no se reutiliza.
"""
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.finished import catalog as finished_catalog
from apps.finished.models import MovimientoTerminado
from apps.finished.services import lock_stock, whole
from apps.inventory.services import fail, next_code
from apps.references.models import Variante

from . import catalog
from .models import Cliente, DetalleVenta, FacturaVenta, MovimientoCartera, PrecioReferencia, SaldoFinanciero


class AlreadyInvoiced(APIException):
    """409: ese formulario ya generó su factura (doble clic o reintento)."""
    status_code = 409
    default_detail = "Esta venta ya fue facturada."
    default_code = "ya_facturada"


class AlreadyCancelled(APIException):
    """409: la factura ya estaba anulada."""
    status_code = 409
    default_detail = "La factura ya está anulada."
    default_code = "ya_anulada"


def round_half_up(numerator, denominator):
    """Cociente entero redondeado con la mitad hacia arriba (números positivos)."""
    return (2 * numerator + denominator) // (2 * denominator)


def line_amounts(unit_price, quantity, discount_pct, iva_rate=catalog.IVA_RATE):
    """Montos de una línea en pesos enteros: subtotal, descuento, base, IVA y total."""
    subtotal = unit_price * quantity
    discount = round_half_up(subtotal * discount_pct, 100)
    base = subtotal - discount
    iva = round_half_up(base * iva_rate, 100)
    return {"subtotal": subtotal, "descuento": discount, "base": base, "iva": iva, "total": base + iva}


def unit_price_for(prices, client_type):
    """Precio de lista que corresponde al tipo de cliente."""
    return prices.precio_detal if catalog.PRICE_LIST[client_type] == "detal" else prices.precio_mayorista


def clean_token(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        fail("Falta el identificador único del formulario: recarga la página.", "token")


def clean_sale_lines(lines):
    """Líneas `[(variante, cantidad, descuento_pct)]`: variantes que existen, sin repetir, cantidad ≥ 1 y descuento de 0 a 100."""
    if not isinstance(lines, list) or not lines:
        fail("Agrega al menos una prenda a la venta.", "lineas")
    if len(lines) > catalog.MAX_INVOICE_LINES:
        fail(f"Se admiten máximo {catalog.MAX_INVOICE_LINES} variantes por factura.", "lineas")
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
        quantity = whole(item.get("cantidad"), f"La cantidad de la fila {number} debe ser un entero mayor que cero.", "lineas")
        discount = whole(item.get("descuento_pct", 0), f"El descuento de la fila {number} debe ser un entero entre 0 y 100.", "lineas", minimum=0)
        if discount > 100:
            fail(f"El descuento de la fila {number} debe ser un entero entre 0 y 100.", "lineas")
        rows.append((variant_id, quantity, discount))
    variants = {v.id: v for v in Variante.objects.select_related("referencia").filter(pk__in=seen)}
    if len(variants) != len(seen):
        fail("Alguna talla y color no existe.", "lineas")
    return [(variants[variant_id], quantity, discount) for variant_id, quantity, discount in rows]


def label(variant):
    return f"{variant.referencia.codigo} {variant.talla} {variant.color}"


def document_label(client):
    return f"{client.tipo_documento} {client.documento}" + (f"-{client.dv}" if client.dv else "")


def already_invoiced(invoice):
    return AlreadyInvoiced({"detail": [f"Esta venta ya se facturó como {invoice.numero}."], "factura": invoice.id, "numero": invoice.numero})


@transaction.atomic
def _issue(*, user, cliente_id, lineas, transportadora, numero_guia, observaciones, token, fecha=None):
    client = Cliente.objects.filter(pk=cliente_id, activo=True).first() if isinstance(cliente_id, int) and not isinstance(cliente_id, bool) else None
    if client is None:
        fail("Elige un cliente activo.", "cliente")
    if transportadora and transportadora not in catalog.CARRIER_NAMES:
        fail("Elige una transportadora de la lista.", "transportadora")
    rows = clean_sale_lines(lineas)

    prices = {p.referencia_id: p for p in PrecioReferencia.objects.filter(referencia_id__in={v.referencia_id for v, _, _ in rows})}
    unpriced = sorted({v.referencia.codigo for v, _, _ in rows if v.referencia_id not in prices})
    if unpriced:
        fail(f"Falta el precio de venta de: {', '.join(unpriced)}. Pídele al Gerente que lo registre.", "lineas")

    stocks = lock_stock([variant.id for variant, _, _ in rows])
    short = [
        {"variante": v.id, "nombre": label(v), "disponible": stocks[v.id].cantidad, "pedido": quantity}
        for v, quantity, _ in rows if stocks[v.id].cantidad < quantity
    ]
    if short:
        detail = "; ".join(f"{item['nombre']}: hay {item['disponible']} y pides {item['pedido']}" for item in short)
        fail(f"Stock insuficiente. {detail}.", "lineas", faltantes=short)

    cap = catalog.MAX_DISCOUNT[client.tipo]
    problems, computed = [], []
    for variant, quantity, discount in rows:
        price = prices[variant.referencia_id]
        unit = unit_price_for(price, client.tipo)
        if discount > cap:
            problems.append(f"{label(variant)}: el descuento máximo para un cliente {catalog.CLIENT_TYPE_NAMES[client.tipo].lower()} es {cap} %.")
        elif unit * (100 - discount) < price.costo_fabrica * 100:
            problems.append(f"{label(variant)}: con {discount} % el precio queda por debajo del costo de fábrica (${price.costo_fabrica:,}).".replace(",", "."))
        computed.append((variant, quantity, discount, unit, price.costo_fabrica, line_amounts(unit, quantity, discount)))
    if problems:
        fail(" ".join(problems), "lineas")

    totals = {key: sum(line[5][key] for line in computed) for key in ("subtotal", "descuento", "base", "iva", "total")}
    invoice = FacturaVenta.objects.create(
        numero=next_code(catalog.INVOICE_PREFIX), cliente=client, cliente_nombre=client.nombre, cliente_documento=document_label(client),
        cliente_tipo=client.tipo, cliente_ciudad=client.ciudad, cliente_direccion=client.direccion, cliente_telefono=client.telefono,
        vendedor=user, fecha=fecha or timezone.localdate(), transportadora=transportadora or "", numero_guia="",
        observaciones=str(observaciones or "").strip()[:500], subtotal=totals["subtotal"], descuento_total=totals["descuento"],
        base_gravable=totals["base"], iva_tarifa=catalog.IVA_RATE, iva_total=totals["iva"], total=totals["total"],
        valor_a_recaudar=totals["total"], token=token,
    )
    for variant, quantity, discount, unit, cost, amounts in sorted(computed, key=lambda row: row[0].id):
        stock = stocks[variant.id]
        before = stock.cantidad
        stock.cantidad = before - quantity
        stock.save(update_fields=["cantidad", "updated_at"])
        DetalleVenta.objects.create(
            factura=invoice, variante=variant, referencia_codigo=variant.referencia.codigo, referencia_nombre=variant.referencia.nombre,
            talla=variant.talla, color=variant.color, cantidad=quantity, precio_unitario=unit, descuento_pct=discount, costo_fabrica=cost,
            subtotal=amounts["subtotal"], descuento=amounts["descuento"], base=amounts["base"], iva=amounts["iva"], total=amounts["total"],
        )
        MovimientoTerminado.objects.create(
            variante=variant, tipo=finished_catalog.SALE_EXIT, cantidad=-quantity, saldo_antes=before, saldo_despues=stock.cantidad,
            factura=invoice, usuario=user, motivo=f"Venta {invoice.numero} a {client.nombre}",
        )
    # La guía se genera en la transportadora antes de facturar y se anota aquí (HU 7.2): nace junto con la factura, en la misma transacción.
    guide_number = "".join(str(numero_guia or "").split())
    if guide_number:
        if not transportadora:
            fail("Elige la transportadora de la guía.", "transportadora")
        from apps.shipping import services as shipping_services  # import local: shipping depende de sales

        shipping_services.assign_guide_to(invoice, transportadora, guide_number, user)
    return invoice


def issue_invoice(*, user, cliente, lineas, token, transportadora="", numero_guia="", observaciones="", fecha=None):
    """Emite la factura POS interna y descuenta el inventario. Un token repetido responde 409 con la factura ya creada."""
    token = clean_token(token)
    existing = FacturaVenta.objects.filter(token=token).first()
    if existing is not None:
        raise already_invoiced(existing)
    try:
        return _issue(
            user=user, cliente_id=cliente, lineas=lineas, transportadora=transportadora, numero_guia=numero_guia,
            observaciones=observaciones, token=token, fecha=fecha,
        )
    except IntegrityError:  # otro envío con el mismo token ganó la carrera
        existing = FacturaVenta.objects.filter(token=token).first()
        if existing is None:
            raise
        raise already_invoiced(existing)


@transaction.atomic
def cancel_invoice(*, user, factura_id, motivo):
    """Anula una factura emitida: las unidades vuelven al inventario por el libro y el número no se reutiliza."""
    reason = str(motivo or "").strip()
    if len(reason) < catalog.MIN_CANCEL_REASON:
        fail(f"Explica por qué se anula (mínimo {catalog.MIN_CANCEL_REASON} caracteres).", "motivo")
    if len(reason) > 255:
        fail("El motivo admite máximo 255 caracteres.", "motivo")
    invoice = FacturaVenta.objects.select_for_update().filter(pk=factura_id).first()
    if invoice is None:
        raise Http404("La factura no existe.")
    if invoice.estado == catalog.STATUS_CANCELLED:
        raise AlreadyCancelled({"detail": [f"La factura {invoice.numero} ya está anulada."]})
    if invoice.estado_cobro == catalog.COLLECT_PAID:
        fail("No se puede anular una factura que ya fue recaudada.", "estado_cobro")
    if invoice.estado_cobro == catalog.COLLECT_RETURNED:
        fail("La factura ya fue gestionada como devolución.", "estado_cobro")
    from apps.shipping import services as shipping_services  # import local: shipping depende de sales

    shipping_services.release_guide_for_cancellation(invoice, user)  # con guía despachada se rechaza; por despachar, se anula la guía
    lines = list(invoice.lineas.order_by("variante_id"))
    stocks = lock_stock([line.variante_id for line in lines])
    for line in lines:
        stock = stocks[line.variante_id]
        before = stock.cantidad
        stock.cantidad = before + line.cantidad
        stock.save(update_fields=["cantidad", "updated_at"])
        MovimientoTerminado.objects.create(
            variante_id=line.variante_id, tipo=finished_catalog.SALE_RETURN, cantidad=line.cantidad, saldo_antes=before,
            saldo_despues=stock.cantidad, factura=invoice, usuario=user, motivo=f"Anulación de {invoice.numero}: {reason}"[:255],
        )
    invoice.estado = catalog.STATUS_CANCELLED
    invoice.motivo_anulacion = reason
    invoice.anulada_por = user
    invoice.anulada_en = timezone.now()
    invoice.save(update_fields=["estado", "motivo_anulacion", "anulada_por", "anulada_en", "updated_at"])
    return invoice


def cash_box():
    """La única caja de la empresa, bloqueada para escribir. Si dos peticiones la crean a la vez, la restricción única deja una sola."""
    box = SaldoFinanciero.objects.select_for_update().filter(nombre=catalog.CASH_BOX).first()
    if box is not None:
        return box
    try:
        with transaction.atomic():
            SaldoFinanciero.objects.create(nombre=catalog.CASH_BOX, saldo_actual=0)
    except IntegrityError:
        pass  # otra petición la creó primero
    return SaldoFinanciero.objects.select_for_update().get(nombre=catalog.CASH_BOX)


def current_guide(invoice):
    """Guía vigente de la factura (HU 7.2), o None si no tiene."""
    from apps.shipping.models import Guia  # import tardío: shipping depende de sales

    return Guia.objects.filter(factura=invoice, vigente=True).first()


def _lock_pending_invoice(factura_id):
    invoice = FacturaVenta.objects.select_for_update().filter(pk=factura_id).first()
    if invoice is None:
        raise Http404("La factura no existe.")
    if invoice.estado == catalog.STATUS_CANCELLED:
        fail("No se puede conciliar una factura anulada.", "estado")
    if invoice.estado_cobro != catalog.COLLECT_PENDING:
        current_name = catalog.COLLECT_STATE_NAMES.get(invoice.estado_cobro, invoice.estado_cobro)
        fail(f"La factura ya fue gestionada como {current_name}.", "estado_cobro")
    return invoice


@transaction.atomic
def confirm_payment(*, user, factura_id, nota=""):
    """
    Confirma el recaudo contraentrega de una factura (HU 7.3 y 7.5):
    - Con guía: solo si la guía vigente está ENTREGADA (el dinero no llega de un paquete en tránsito o devuelto).
    - Sin guía (entrega en mano o recogida en bodega): solo con una nota que lo justifique.
    Suma el valor a recaudar a la caja y deja el movimiento de cartera con la nota. La factura no se modifica más allá de su estado de cobro.
    """
    from apps.shipping import catalog as shipping_catalog

    invoice = _lock_pending_invoice(factura_id)
    note = str(nota or "").strip()
    guide = current_guide(invoice)
    if guide is not None and guide.estado != shipping_catalog.DELIVERED:
        state = shipping_catalog.STATE_NAMES.get(guide.estado, guide.estado).lower()
        fail(f"La guía {guide.numero_guia} está {state}: solo se confirma el pago de una guía entregada.", "guia")
    if guide is None and len(note) < catalog.MIN_NO_GUIDE_NOTE:
        fail(f"La factura no tiene guía: explica en la nota cómo se entregó y cobró (mínimo {catalog.MIN_NO_GUIDE_NOTE} caracteres).", "nota")
    if len(note) > 255:
        fail("La nota admite máximo 255 caracteres.", "nota")

    box = cash_box()
    before = box.saldo_actual
    amount = invoice.valor_a_recaudar
    box.saldo_actual = before + amount
    box.save(update_fields=["saldo_actual", "updated_at"])

    invoice.estado_cobro = catalog.COLLECT_PAID
    invoice.fecha_cobro = timezone.now()
    invoice.cobrado_por = user
    invoice.save(update_fields=["estado_cobro", "fecha_cobro", "cobrado_por", "updated_at"])

    MovimientoCartera.objects.create(
        factura=invoice, tipo=catalog.FINANCIAL_LEDGER_RECAUDO, monto=amount, saldo_antes=before, saldo_despues=box.saldo_actual,
        usuario=user, observaciones=(note or f"Recaudo de {invoice.numero} confirmado (guía {guide.numero_guia} entregada)")[:255],
    )
    return invoice


@transaction.atomic
def register_return(*, user, factura_id, motivo):
    """
    Devolución contraentrega (HU 7.3 y 7.5). Único camino: la guía devuelta que llegó a bodega (`shipping.services.return_to_stock`).
    Reingresa las prendas al inventario de producto terminado una sola vez y marca la factura en DEVOLUCION; la caja no cambia.
    """
    invoice = _lock_pending_invoice(factura_id)
    reason = str(motivo or "").strip()
    if len(reason) < 5:
        fail("Indica el motivo de la devolución (mínimo 5 caracteres).", "motivo")
    reason = reason[:255]

    lines = list(invoice.lineas.order_by("variante_id"))
    stocks = lock_stock([line.variante_id for line in lines])
    for line in lines:
        stock = stocks[line.variante_id]
        s_before = stock.cantidad
        stock.cantidad = s_before + line.cantidad
        stock.save(update_fields=["cantidad", "updated_at"])
        MovimientoTerminado.objects.create(
            variante_id=line.variante_id, tipo=finished_catalog.SALE_RETURN, cantidad=line.cantidad, saldo_antes=s_before,
            saldo_despues=stock.cantidad, factura=invoice, usuario=user,
            motivo=f"Devolución contraentrega de {invoice.numero}: {reason}"[:255],
        )

    invoice.estado_cobro = catalog.COLLECT_RETURNED
    invoice.motivo_devolucion = reason
    invoice.fecha_cobro = timezone.now()
    invoice.cobrado_por = user
    invoice.save(update_fields=["estado_cobro", "motivo_devolucion", "fecha_cobro", "cobrado_por", "updated_at"])

    box = cash_box()
    MovimientoCartera.objects.create(
        factura=invoice, tipo=catalog.FINANCIAL_LEDGER_DEVOLUCION, monto=0, saldo_antes=box.saldo_actual,
        saldo_despues=box.saldo_actual, usuario=user, observaciones=f"Devolución: {reason}"[:255],
    )
    return invoice


def get_cartera_summary():
    """Calcula los totales de cartera y el saldo financiero actual de la empresa."""
    box = SaldoFinanciero.objects.filter(nombre=catalog.CASH_BOX).first()
    saldo_actual = box.saldo_actual if box else 0

    issued = FacturaVenta.objects.filter(estado=catalog.STATUS_ISSUED)
    por_cobrar = issued.filter(estado_cobro=catalog.COLLECT_PENDING)
    pagadas = issued.filter(estado_cobro=catalog.COLLECT_PAID)
    devoluciones = issued.filter(estado_cobro=catalog.COLLECT_RETURNED)

    return {
        "saldo_financiero": saldo_actual,
        "total_por_cobrar": por_cobrar.aggregate(s=Sum("valor_a_recaudar"))["s"] or 0,
        "conteo_por_cobrar": por_cobrar.count(),
        "total_recaudado": pagadas.aggregate(s=Sum("valor_a_recaudar"))["s"] or 0,
        "conteo_pagadas": pagadas.count(),
        "total_devoluciones": devoluciones.aggregate(s=Sum("valor_a_recaudar"))["s"] or 0,
        "conteo_devoluciones": devoluciones.count(),
    }


def get_sales_panel(today=None):
    """Cifras del panel de ventas calculadas en la base de datos (HU 7.5), no con una lista parcial de facturas."""
    today = today or timezone.localdate()
    issued = FacturaVenta.objects.filter(estado=catalog.STATUS_ISSUED)
    of_today = issued.filter(fecha=today)
    pending = issued.filter(estado_cobro=catalog.COLLECT_PENDING)
    return {
        "fecha": today,
        "facturas_hoy": of_today.count(),
        "vendido_hoy": of_today.aggregate(s=Sum("total"))["s"] or 0,
        "anuladas_hoy": FacturaVenta.objects.filter(estado=catalog.STATUS_CANCELLED, fecha=today).count(),
        "por_cobrar": pending.aggregate(s=Sum("valor_a_recaudar"))["s"] or 0,
        "facturas_por_cobrar": pending.count(),
    }
