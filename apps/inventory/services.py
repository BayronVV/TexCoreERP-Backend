"""
Reglas de negocio del inventario. Cada función es una transacción: o se guarda
todo (saldo, kardex, orden) o no se guarda nada.

Los productos se bloquean siempre en orden de id para que dos órdenes que tocan
los mismos productos no se queden esperándose una a la otra.
"""
import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import catalog
from .models import Consecutivo, Evidencia, Movimiento, OrdenLinea, OrdenSalida, Producto, Proveedor

MAX_QUANTITY = Decimal("9999999999.99")


def fail(message, field="detail", **extra):
    raise ValidationError({field: [message], **extra})


def next_code(prefix):
    """PREFIJO-0001, PREFIJO-0002... Debe llamarse dentro de una transacción."""
    counter, _ = Consecutivo.objects.select_for_update().get_or_create(clave=prefix)
    counter.ultimo += 1
    counter.save(update_fields=["ultimo"])
    return f"{prefix}-{counter.ultimo:04d}"


def parse_quantity(value, unit, field="cantidad"):
    try:
        quantity = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        fail("La cantidad debe ser un número.", field)
    if not quantity.is_finite() or quantity <= 0:
        fail("La cantidad debe ser mayor que cero.", field)
    if quantity > MAX_QUANTITY:
        fail("La cantidad es demasiado grande.", field)
    if unit in catalog.WHOLE_UNITS and quantity != quantity.to_integral_value():
        fail("Esta unidad no admite decimales.", field)
    return quantity


def format_quantity(quantity, unit):
    return f"{quantity.normalize():f} {unit}"


def check_date(value, field="fecha"):
    if value > timezone.localdate():
        fail("La fecha no puede ser futura.", field)


def lock_products(ids):
    products = {p.id: p for p in Producto.objects.select_for_update().filter(id__in=ids).order_by("id")}
    missing = set(ids) - set(products)
    if missing:
        fail("Uno de los productos no existe.", "lineas")
    return products


def _apply_movement(product, kind, reason, quantity, **fields):
    """Cambia el saldo del producto (ya bloqueado) y deja la fila del kardex."""
    before = product.stock_actual
    after = before + quantity if kind == catalog.ENTRY else before - quantity
    if after < 0:
        fail(
            f"Stock insuficiente de {product.nombre}: hay {format_quantity(before, product.unidad)}.",
            "cantidad",
        )
    product.stock_actual = after
    product.save(update_fields=["stock_actual", "updated_at"])
    return Movimiento.objects.create(
        producto=product, tipo=kind, motivo=reason, cantidad=quantity,
        stock_antes=before, stock_despues=after, **fields,
    )


# --- Catálogo de productos (HU 2.2) -------------------------------------------

PERCENTAGE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def check_composition(text, required):
    """Las composiciones se escriben como "98% algodón / 2% elastano": los porcentajes suman 100."""
    text = text.strip()
    if not text:
        if required:
            fail("La composición textil es obligatoria (ej. 100% algodón).", "composicion")
        return ""
    percentages = [Decimal(p.replace(",", ".")) for p in PERCENTAGE.findall(text)]
    if required and not percentages:
        fail("Indica la composición con porcentajes (ej. 80% algodón, 20% nylon).", "composicion")
    if percentages and sum(percentages) != 100:
        fail(f"Los porcentajes de la composición suman {sum(percentages).normalize():f}%, deben sumar 100%.", "composicion")
    return text


def clean_product_fields(*, categoria, unidad, ancho_util, composicion, color):
    """Reglas del catálogo que dependen de la categoría. Devuelve los datos ya normalizados."""
    if categoria not in catalog.CATEGORIES:
        fail("Elige la categoría del producto.", "categoria")
    rules = catalog.CATEGORIES[categoria]
    if unidad not in rules["units"]:
        allowed = ", ".join(rules["units"])
        fail(f"La unidad «{unidad}» no es compatible con {rules['label'].lower()}. Usa: {allowed}.", "unidad")

    if categoria in catalog.WIDTH_REQUIRED:
        if ancho_util is None:
            fail("El ancho útil del rollo es obligatorio para las telas (en metros).", "ancho_util")
        if not (0 < ancho_util <= catalog.MAX_FABRIC_WIDTH):
            fail(f"El ancho útil debe estar entre 0 y {catalog.MAX_FABRIC_WIDTH} metros.", "ancho_util")
    else:
        ancho_util = None  # solo las telas tienen ancho útil

    return {
        "tipo": rules["tipo"],
        "ancho_util": ancho_util,
        "composicion": check_composition(composicion, categoria in catalog.COMPOSITION_REQUIRED),
        "color": color.strip(),
    }


def _same_name_exists(nombre, categoria, exclude_id=None):
    # Se compara en Python: "iexact" de SQLite solo ignora mayúsculas ASCII (ñ, í, é...).
    queryset = Producto.objects.filter(categoria=categoria)
    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)
    wanted = nombre.casefold()
    return any(existing.casefold() == wanted for existing in queryset.values_list("nombre", flat=True))


@transaction.atomic
def create_product(*, nombre, categoria, unidad, stock_minimo=0, descripcion="", ancho_util=None,
                   color="", composicion=""):
    name = nombre.strip()
    if _same_name_exists(name, categoria):
        fail("Ya existe un producto con ese nombre en esta categoría.", "nombre")
    cleaned = clean_product_fields(
        categoria=categoria, unidad=unidad, ancho_util=ancho_util, composicion=composicion, color=color
    )
    return Producto.objects.create(
        codigo=next_code(catalog.CATEGORIES[categoria]["prefix"]), nombre=name, categoria=categoria,
        unidad=unidad, stock_minimo=stock_minimo, descripcion=descripcion.strip(), **cleaned,
    )


@transaction.atomic
def update_product(product, **data):
    """Edita un producto del catálogo. El stock no se toca: solo cambia con movimientos."""
    product = Producto.objects.select_for_update().get(pk=product.pk)
    values = {
        "nombre": data.get("nombre", product.nombre).strip(),
        "categoria": data.get("categoria", product.categoria),
        "unidad": data.get("unidad", product.unidad),
        "ancho_util": data.get("ancho_util", product.ancho_util),
        "composicion": data.get("composicion", product.composicion),
        "color": data.get("color", product.color),
    }
    structural = values["categoria"] != product.categoria or values["unidad"] != product.unidad
    if structural and (product.stock_actual != 0 or Movimiento.objects.filter(producto=product).exists()):
        fail("La categoría y la unidad no se pueden cambiar cuando el producto ya tiene movimientos.", "categoria")
    if _same_name_exists(values["nombre"], values["categoria"], exclude_id=product.pk):
        fail("Ya existe un producto con ese nombre en esta categoría.", "nombre")

    cleaned = clean_product_fields(
        categoria=values["categoria"], unidad=values["unidad"], ancho_util=values["ancho_util"],
        composicion=values["composicion"], color=values["color"],
    )
    product.nombre, product.categoria, product.unidad = values["nombre"], values["categoria"], values["unidad"]
    product.tipo, product.ancho_util = cleaned["tipo"], cleaned["ancho_util"]
    product.composicion, product.color = cleaned["composicion"], cleaned["color"]
    if "stock_minimo" in data:
        product.stock_minimo = data["stock_minimo"]
    if "descripcion" in data:
        product.descripcion = data["descripcion"].strip()
    product.save()
    return product


def archive_product(product):
    if product.stock_actual > 0:
        fail("No se puede eliminar un producto con existencias.")
    if OrdenSalida.objects.filter(estado=catalog.STATUS_OPEN, producto_resultado=product).exists():
        fail("Hay una orden en proceso que produce este producto.")
    product.delete()


IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@transaction.atomic
def set_product_image(product, upload):
    if upload is None:
        fail("Adjunta una imagen.", "imagen")
    if upload.size > catalog.IMAGE_MAX_BYTES:
        fail(f"La imagen pesa más de {catalog.IMAGE_MAX_BYTES // (1024 * 1024)} MB.", "imagen")
    data = upload.read()
    content_type, _ = detect_type(data[:16])
    if content_type not in IMAGE_TYPES:
        fail("Solo se aceptan imágenes JPG, PNG o WEBP.", "imagen")
    product = Producto.objects.select_for_update().get(pk=product.pk)
    product.imagen, product.imagen_tipo = data, content_type
    product.imagen_version += 1
    product.save(update_fields=["imagen", "imagen_tipo", "imagen_version", "updated_at"])
    return product


@transaction.atomic
def clear_product_image(product):
    product = Producto.objects.select_for_update().get(pk=product.pk)
    product.imagen, product.imagen_tipo = None, ""
    product.imagen_version += 1
    product.save(update_fields=["imagen", "imagen_tipo", "imagen_version", "updated_at"])
    return product


# --- Proveedores (HU 2.1) --------------------------------------------------------

NIT = re.compile(r"^(\d{6,10})(?:-(\d))?$")


def normalize_nit(raw):
    """Acepta "890.900.001-4", "890900001-4" o "890900001". Devuelve (número, dígito de verificación)."""
    text = re.sub(r"[.\s]", "", str(raw or ""))
    match = NIT.match(text)
    if not match:
        fail("El NIT no es válido. Escríbelo como 890.900.001-4 (6 a 10 dígitos y, si lo tiene, el dígito de verificación).", "nit")
    return match.group(1), match.group(2) or ""


def check_supplier_nit_free(nit, exclude_id=None):
    queryset = Proveedor.objects.filter(nit=nit)
    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)
    if queryset.exists():
        fail("Ya existe un proveedor activo con ese NIT.", "nit")


def check_phone(value):
    value = value.strip()
    if value and not (7 <= len(re.sub(r"\D", "", value)) <= 15 and re.fullmatch(r"[\d\s()+-]+", value)):
        fail("El teléfono no es válido (solo números, espacios, + y -).", "telefono")
    return value


@transaction.atomic
def save_supplier(instance=None, **data):
    """Crea o actualiza un proveedor validando NIT (estructura y duplicado) y teléfono."""
    raw_nit = data.pop("nit", None)
    if raw_nit is not None:
        nit, dv = normalize_nit(raw_nit)
        check_supplier_nit_free(nit, exclude_id=instance.pk if instance else None)
        data["nit"], data["nit_dv"] = nit, dv
    if "telefono" in data:
        data["telefono"] = check_phone(data["telefono"])
    for field in ("razon_social", "contacto", "ciudad", "direccion"):
        if field in data:
            data[field] = data[field].strip()
    try:
        if instance is None:
            return Proveedor.objects.create(**data)
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save()
        return instance
    except IntegrityError:  # dos personas guardando el mismo NIT a la vez
        fail("Ya existe un proveedor activo con ese NIT.", "nit")


@transaction.atomic
def restore_supplier(supplier):
    check_supplier_nit_free(supplier.nit, exclude_id=supplier.pk)
    supplier.restore()
    return supplier


# --- Ingresos ------------------------------------------------------------------

@transaction.atomic
def register_entry(*, user, producto_id, cantidad, fecha, proveedor_id=None, orden_compra="", lote="",
                   orden_id=None, observaciones=""):
    check_date(fecha)
    product = lock_products([producto_id])[producto_id]
    quantity = parse_quantity(cantidad, product.unidad)

    if product.tipo in catalog.PURCHASED_TYPES:
        if not proveedor_id:
            fail("Selecciona el proveedor.", "proveedor")
        supplier = Proveedor.objects.filter(pk=proveedor_id).first()  # solo activos
        if supplier is None:
            fail("El proveedor no existe o está archivado.", "proveedor")
        if not lote.strip():
            fail("El lote es obligatorio para materia prima e insumos.", "lote")
        if orden_id:
            fail("Las compras no se asocian a una orden de salida.", "orden")
        return _apply_movement(
            product, catalog.ENTRY, catalog.REASON_PURCHASE, quantity,
            fecha=fecha, proveedor=supplier, proveedor_nombre=supplier.razon_social,
            orden_compra=orden_compra.strip(),
            lote=lote.strip(), observaciones=observaciones.strip(), registrado_por=user,
        )

    # Pantalón genérico o terminado: solo entra cerrando la orden que lo fabricó.
    if not orden_id:
        fail("Selecciona la orden de la que viene este producto.", "orden")
    try:
        order = OrdenSalida.objects.select_for_update().get(pk=orden_id)
    except OrdenSalida.DoesNotExist:
        fail("La orden no existe.", "orden")
    if order.estado != catalog.STATUS_OPEN:
        fail(f"La orden {order.codigo} ya no está en proceso.", "orden")
    if order.producto_resultado_id != product.id:
        fail(f"La orden {order.codigo} produce {order.producto_resultado.nombre}, no este producto.", "producto")
    if order.tipo == catalog.ORDER_LAUNDRY and quantity > order.cantidad_prendas:
        fail(
            f"No pueden volver más prendas de las enviadas ({format_quantity(order.cantidad_prendas, product.unidad)}).",
            "cantidad",
        )
    if fecha < order.fecha_salida:
        fail("El ingreso no puede ser anterior a la salida de la orden.", "fecha")

    movement = _apply_movement(
        product, catalog.ENTRY, catalog.REASON_ORDER_RETURN, quantity,
        fecha=fecha, lote=order.ficha_tecnica, orden=order,
        observaciones=observaciones.strip(), registrado_por=user,
    )
    order.estado = catalog.STATUS_DONE
    order.completada_at = timezone.now()
    order.save(update_fields=["estado", "completada_at", "updated_at"])
    return movement


# --- Órdenes de salida ---------------------------------------------------------

@transaction.atomic
def create_order(*, user, tipo, fecha_salida, responsable, ficha_tecnica, producto_resultado_id, lineas,
                 destino="", cantidad_prendas=None, observaciones=""):
    rules = catalog.ORDER_RULES[tipo]
    check_date(fecha_salida, "fecha_salida")

    ids = [line["producto"] for line in lineas]
    if len(ids) != len(set(ids)):
        fail("Un producto aparece dos veces en la orden.", "lineas")
    products = lock_products(ids + [producto_resultado_id])

    result = products[producto_resultado_id]
    if result.tipo != rules["output_type"]:
        label = dict(catalog.PRODUCT_TYPES)[rules["output_type"]].lower()
        fail(f"El resultado de una orden de este tipo debe ser un {label}.", "producto_resultado")

    quantities, shortages, planned = {}, [], None
    for line in lineas:
        product = products[line["producto"]]
        if product.tipo not in rules["input_types"]:
            fail(f"{product.nombre} no puede salir en una orden de {dict(catalog.ORDER_TYPES)[tipo].lower()}.", "lineas")
        quantity = parse_quantity(line["cantidad"], product.unidad, "lineas")
        quantities[product.id] = quantity
        if product.tipo == catalog.GENERIC_PANTS:
            planned = quantity
        if quantity > product.stock_actual:
            shortages.append({
                "producto": product.id,
                "nombre": product.nombre,
                "disponible": str(product.stock_actual),
                "solicitado": str(quantity),
                "unidad": product.unidad,
            })
    if shortages:
        names = ", ".join(s["nombre"] for s in shortages)
        fail(f"Stock insuficiente: {names}.", faltantes=shortages)

    if tipo == catalog.ORDER_LAUNDRY:
        generic = [p for p in (products[i] for i in ids) if p.tipo == catalog.GENERIC_PANTS]
        if len(generic) != 1:
            fail("Una orden de lavandería envía exactamente un tipo de pantalón genérico.", "lineas")
    elif cantidad_prendas not in (None, ""):
        planned = parse_quantity(cantidad_prendas, "unidad", "cantidad_prendas")

    order = OrdenSalida.objects.create(
        codigo=next_code(catalog.ORDER_PREFIX[tipo]), tipo=tipo, fecha_salida=fecha_salida,
        responsable=responsable.strip(), destino=destino.strip(), ficha_tecnica=ficha_tecnica.strip(),
        producto_resultado=result, cantidad_prendas=planned,
        observaciones=observaciones.strip(), registrado_por=user,
    )
    for line in lineas:
        product = products[line["producto"]]
        OrdenLinea.objects.create(orden=order, producto=product, cantidad=quantities[product.id])
        _apply_movement(
            product, catalog.EXIT, catalog.REASON_ORDER_EXIT, quantities[product.id],
            fecha=fecha_salida, orden=order, lote=order.ficha_tecnica, registrado_por=user,
        )
    return order


@transaction.atomic
def cancel_order(*, user, order_id, motivo):
    if not motivo.strip():
        fail("Escribe el motivo de la anulación.", "motivo")
    try:
        order = OrdenSalida.objects.select_for_update().get(pk=order_id)
    except OrdenSalida.DoesNotExist:
        fail("La orden no existe.", "orden")
    if order.estado != catalog.STATUS_OPEN:
        fail("Solo se pueden anular órdenes en proceso.", "orden")

    lines = list(order.lineas.select_related("producto"))
    products = lock_products([line.producto_id for line in lines])
    for line in lines:
        _apply_movement(
            products[line.producto_id], catalog.ENTRY, catalog.REASON_CANCELLATION, line.cantidad,
            fecha=timezone.localdate(), orden=order, lote=order.ficha_tecnica,
            observaciones=f"Anulación de {order.codigo}: {motivo.strip()}", registrado_por=user,
        )
    order.estado = catalog.STATUS_CANCELLED
    order.anulada_at = timezone.now()
    order.motivo_anulacion = motivo.strip()[:255]
    order.save(update_fields=["estado", "anulada_at", "motivo_anulacion", "updated_at"])
    return order


# --- Alertas de stock mínimo (HU 2.4) -------------------------------------------

def stock_alerts():
    """Productos con mínimo definido cuyo saldo llegó o bajó de ese mínimo."""
    alerts = []
    products = Producto.objects.filter(stock_minimo__gt=0).order_by("stock_actual", "nombre")
    for product in products:
        if product.stock_actual > product.stock_minimo:
            continue
        out = product.stock_actual <= 0
        alerts.append({
            "id": product.id,
            "codigo": product.codigo,
            "name": product.nombre,
            "stock": str(product.stock_actual),
            "threshold": str(product.stock_minimo),
            "unit": product.unidad,
            "severity": "critical" if out else "warning",
            "message": "Sin existencias." if out else "Existencias en el mínimo o por debajo.",
        })
    return alerts


# --- Evidencias ------------------------------------------------------------------

SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"%PDF-", "application/pdf", ".pdf"),
]


def detect_type(header):
    """El tipo se decide por el contenido, no por el nombre ni por lo que diga el navegador."""
    for signature, content_type, extension in SIGNATURES:
        if header.startswith(signature):
            return content_type, extension
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None, None


@transaction.atomic
def attach_evidence(*, user, files, movement=None, order=None):
    owner = {"movimiento": movement} if movement else {"orden": order}
    current = Evidencia.objects.filter(**owner).count()
    if not files:
        fail("Adjunta al menos un archivo.", "archivos")
    if current + len(files) > catalog.EVIDENCE_MAX_PER_RECORD:
        fail(f"Máximo {catalog.EVIDENCE_MAX_PER_RECORD} evidencias por registro.", "archivos")

    saved = []
    for upload in files:
        if upload.size > catalog.EVIDENCE_MAX_BYTES:
            fail(f"{upload.name} pesa más de {catalog.EVIDENCE_MAX_BYTES // (1024 * 1024)} MB.", "archivos")
        content_type, extension = detect_type(upload.read(16))
        upload.seek(0)
        if not content_type:
            fail(f"{upload.name}: solo se aceptan fotos JPG, PNG, WEBP o PDF.", "archivos")
        original = _clean_name(upload.name)
        upload.name = f"evidencia{extension}"
        saved.append(Evidencia.objects.create(
            archivo=upload, nombre_original=original,
            content_type=content_type, tamano=upload.size, subido_por=user, **owner,
        ))
    return saved


def _clean_name(name):
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(ch for ch in name if ch.isprintable())[:120] or "evidencia"
