"""
Ficha técnica de consumo por unidad (HU 3.2): validación, guardado y cálculo de consumo contra el
stock. Cada función que escribe es una transacción: o se guarda todo o no se guarda nada.
"""
import os
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django.db import transaction

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Producto
from apps.inventory.services import detect_type, fail

from . import catalog
from .models import FichaLinea, FichaTecnica, Referencia
from .services import clean_text

CENT = Decimal("0.01")


def _decimal(value, places, label):
    """Convierte a Decimal exigiendo como máximo `places` decimales (no redondea en silencio)."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(f"{label} debe ser un número.", "lineas")
    if not number.is_finite() or number != number.quantize(Decimal(1).scaleb(-places)):
        fail(f"{label} admite como máximo {places} decimales.", "lineas")
    return number


def clean_lines(raw):
    """Valida las líneas de una ficha y las devuelve como `(producto, cantidad, merma, observaciones)`.
    Cada material debe existir y ser materia prima o insumo; no se repiten; la cantidad es positiva
    (entera si la unidad no admite decimales) y la merma va de 0 a `MAX_WASTE` %, solo en unidades
    que admiten decimales.
    """
    if not raw:
        fail("Agrega al menos un material a la ficha técnica.", "lineas")
    if len(raw) > catalog.MAX_FICHA_LINES:
        fail(f"Una ficha admite máximo {catalog.MAX_FICHA_LINES} materiales.", "lineas")
    ids = [item["producto"] for item in raw]
    if len(set(ids)) != len(ids):
        fail("Un material aparece dos veces en la ficha.", "lineas")
    products = {p.id: p for p in Producto.objects.filter(pk__in=ids)}
    result = []
    for item in raw:
        product = products.get(item["producto"])
        if product is None:
            fail("Uno de los materiales no existe o fue archivado.", "lineas")
        if product.tipo not in inventory_catalog.PURCHASED_TYPES:
            fail(f"{product.nombre} no es materia prima ni insumo: la ficha solo lleva materiales.", "lineas")
        whole = product.unidad in inventory_catalog.WHOLE_UNITS
        quantity = _decimal(item["cantidad"], 3, f"La cantidad de {product.nombre}")
        if quantity <= 0 or quantity > catalog.MAX_CONSUMPTION:
            fail(f"La cantidad de {product.nombre} debe ser mayor que 0 y de máximo {catalog.MAX_CONSUMPTION}.", "lineas")
        if whole and quantity != quantity.to_integral_value():
            fail(f"{product.nombre} se cuenta en {product.unidad}: la cantidad por prenda debe ser entera.", "lineas")
        waste = _decimal(item.get("merma", 0), 2, f"La merma de {product.nombre}")
        if waste < 0 or waste > catalog.MAX_WASTE:
            fail(f"La merma de {product.nombre} va de 0 a {catalog.MAX_WASTE} %.", "lineas")
        if waste and whole:
            fail(f"{product.nombre} se cuenta en piezas enteras: no lleva merma.", "lineas")
        result.append((product, quantity, waste, clean_text(item.get("observaciones"))[:120]))
    return result


@transaction.atomic
def save_ficha(*, user, reference, data, lines):
    """Crea o reemplaza la ficha técnica de la referencia. `lines` es la ficha completa: se crean los
    materiales nuevos, se actualizan los que cambian y se archivan los que ya no están.
    """
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    wanted = clean_lines(lines)
    wash = data.get("lavado", "")
    if wash and wash not in dict(catalog.WASHES):
        fail("Tipo de lavado no válido.", "lavado")
    ficha = reference.fichas.first() or FichaTecnica(referencia=reference)
    ficha.lavado = wash
    ficha.notas = clean_text(data.get("notas"))
    ficha.actualizado_por = user
    ficha.save()
    current = {line.producto_id: line for line in ficha.lineas.all()}
    keep = {product.id for product, *_ in wanted}
    for product_id, line in current.items():
        if product_id not in keep:
            line.delete()
    for product, quantity, waste, notes in wanted:
        line = current.get(product.id)
        if line is None:
            FichaLinea.objects.create(ficha=ficha, producto=product, cantidad=quantity, merma=waste, observaciones=notes)
        elif (line.cantidad, line.merma, line.observaciones) != (quantity, waste, notes):
            line.cantidad, line.merma, line.observaciones = quantity, waste, notes
            line.save()
    return ficha


@transaction.atomic
def delete_ficha(reference):
    """Archiva la ficha con sus materiales. No se hace si la referencia tiene órdenes en proceso."""
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    ficha = reference.fichas.first()
    if ficha is None:
        fail("La referencia no tiene ficha técnica.", "detail")
    if reference.ordenes.filter(estado=inventory_catalog.STATUS_OPEN).exists():
        fail("La referencia tiene órdenes en proceso; ciérralas o anúlalas antes de quitar su ficha.", "detail")
    ficha.lineas.all().delete()
    ficha.delete()


def ficha_lines(reference):
    """Materiales de la ficha con su producto, en una sola consulta (sin traer la imagen del producto)."""
    return list(
        FichaLinea.objects.filter(ficha__referencia=reference, ficha__deleted_at__isnull=True)
        .select_related("producto").defer("producto__imagen").order_by("producto__nombre", "id")
    )


def gross_per_garment(line):
    """Consumo por prenda con la merma aplicada una sola vez: cantidad × (1 + merma/100)."""
    return line.cantidad * (Decimal(1) + line.merma / Decimal(100))


def required_total(line, garments):
    """Cantidad total que pide la ficha para `garments` prendas. Se redondea una sola vez, al final y
    hacia arriba: a entero si la unidad no admite decimales y a 2 decimales (los del inventario) si sí.
    """
    total = gross_per_garment(line) * garments
    if line.producto.unidad in inventory_catalog.WHOLE_UNITS:
        return total.to_integral_value(rounding=ROUND_CEILING)
    return total.quantize(CENT, rounding=ROUND_CEILING)


def parse_garments(value):
    """Cantidad de prendas: entero entre 1 y `MAX_GARMENTS`."""
    try:
        garments = int(str(value).strip())
    except (TypeError, ValueError):
        fail("La cantidad de prendas debe ser un número entero.", "cantidad")
    if garments < 1 or garments > catalog.MAX_GARMENTS:
        fail(f"La cantidad de prendas va de 1 a {catalog.MAX_GARMENTS}.", "cantidad")
    return garments


def compute_requirements(reference, garments):
    """Cruza la ficha con el saldo de almacén (TE-109): cuánto se necesita para `garments` prendas,
    cuánto hay y cuánto falta de cada material, con una sola consulta. Es una simulación: no bloquea ni
    reserva stock, y la orden vuelve a verificarlo al crearse.
    """
    lines = ficha_lines(reference)
    if not lines:
        fail("La referencia no tiene ficha técnica.", "referencia")
    return requirements_for(lines, garments)


def requirements_for(lines, garments):
    """El cruce de `compute_requirements` sobre líneas de ficha ya cargadas (para no repetir la consulta)."""
    rows = []
    for line in lines:
        product = line.producto
        required = required_total(line, garments)
        missing = max(required - product.stock_actual, Decimal(0))
        rows.append({
            "producto": product.id, "codigo": product.codigo, "nombre": product.nombre, "unidad": product.unidad,
            "por_prenda": line.cantidad, "merma": line.merma, "requerido": required,
            "disponible": product.stock_actual, "falta": missing, "suficiente": missing == 0,
            "observaciones": line.observaciones,
        })
    return {
        "cantidad": garments,
        "viable": all(row["suficiente"] for row in rows),
        "lineas": rows,
        "faltantes": [row for row in rows if not row["suficiente"]],
    }


# --- PDF de la ficha técnica extensa ----------------------------------------------------

@transaction.atomic
def set_document(reference, upload):
    """Adjunta (o reemplaza) el PDF de la ficha técnica extensa: máx. `DOCUMENT_MAX_BYTES`, detectado por
    contenido. Exige que la ficha ya exista; sube `documento_version` para invalidar cachés.
    """
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    ficha = reference.fichas.first()
    if ficha is None:
        fail("Guarda primero la ficha con sus materiales; después puedes adjuntar el PDF.", "documento")
    if upload is None:
        fail("Adjunta un archivo PDF.", "documento")
    if upload.size > catalog.DOCUMENT_MAX_BYTES:
        fail(f"El PDF pesa más de {catalog.DOCUMENT_MAX_BYTES // (1024 * 1024)} MB.", "documento")
    data = upload.read()
    content_type, _ = detect_type(data[:16])
    if content_type != "application/pdf":
        fail("Solo se aceptan archivos PDF.", "documento")
    ficha.documento = data
    ficha.documento_nombre = os.path.basename(upload.name or "ficha-tecnica.pdf")[:120]
    ficha.documento_tamano = len(data)
    ficha.documento_version += 1
    ficha.save(update_fields=["documento", "documento_nombre", "documento_tamano", "documento_version", "updated_at"])
    return ficha


@transaction.atomic
def clear_document(reference):
    """Quita el PDF de la ficha."""
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    ficha = reference.fichas.first()
    if ficha is None or not ficha.tiene_documento:
        fail("La ficha no tiene un PDF adjunto.", "documento")
    ficha.documento, ficha.documento_nombre, ficha.documento_tamano = None, "", 0
    ficha.documento_version += 1
    ficha.save(update_fields=["documento", "documento_nombre", "documento_tamano", "documento_version", "updated_at"])
    return ficha
