"""
Control de calidad (HU 6.1 / RF19 y RF20).

- El catálogo de defectos se crea y se edita, pero no se borra: se desactiva. El nombre no se repite (sin importar mayúsculas).
- Un lote se puede inspeccionar cuando ya tiene una recepción de lavandería (HU 5.2), está en planta, su orden no está
  anulada y todavía no tiene inspección. La cantidad a inspeccionar es lo recibido conforme en su recepción más reciente.
- La inspección es una sola transacción con el lote bloqueado: aptas + marras debe ser exactamente lo recibido, cada marra
  se desglosa por defecto y el resultado no se edita ni se borra. Los faltantes y daños de lavandería ya los liquida la
  recepción; aquí solo se clasifican las prendas que sí llegaron.
"""
import re

from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.inventory import catalog as inventory_catalog
from apps.inventory.services import fail, next_code
from apps.production import catalog as production_catalog
from apps.production.models import Lote, RecepcionLote

from . import catalog
from .models import Inspeccion, MarraDetalle, TipoDefecto


class AlreadyInspected(APIException):
    """409: el lote ya tiene su inspección (otra persona pudo registrarla un momento antes)."""
    status_code = 409
    default_detail = "El lote ya fue inspeccionado."
    default_code = "ya_inspeccionado"


# --- Catálogo de defectos (RF19) ----------------------------------------------------------------------------------

def clean_name(value):
    """Nombre del defecto sin espacios de más; entre 3 y 80 caracteres."""
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(name) < 3:
        fail("El nombre del defecto debe tener al menos 3 caracteres.", "nombre")
    if len(name) > 80:
        fail("El nombre del defecto no puede pasar de 80 caracteres.", "nombre")
    return name


def check_unique_name(name, exclude_id=None):
    others = TipoDefecto.objects.filter(nombre__iexact=name)
    if exclude_id:
        others = others.exclude(pk=exclude_id)
    if others.exists():
        fail("Ya existe un defecto con ese nombre (puede estar desactivado).", "nombre")


@transaction.atomic
def create_defect(*, nombre, descripcion="", corregible=False):
    """Registra un defecto activo del catálogo con su código DEF-0001."""
    name = clean_name(nombre)
    check_unique_name(name)
    return TipoDefecto.objects.create(
        codigo=next_code(catalog.DEFECT_PREFIX), nombre=name, descripcion=(descripcion or "").strip(), corregible=bool(corregible),
    )


@transaction.atomic
def update_defect(defect, data):
    """Cambia nombre, descripción, tipo o estado del defecto. Las inspecciones ya hechas conservan lo que guardaron."""
    defect = TipoDefecto.objects.select_for_update().get(pk=defect.pk)
    if "nombre" in data:
        name = clean_name(data["nombre"])
        check_unique_name(name, exclude_id=defect.pk)
        defect.nombre = name
    if "descripcion" in data:
        defect.descripcion = (data["descripcion"] or "").strip()
    if "corregible" in data:
        defect.corregible = bool(data["corregible"])
    if "activo" in data:
        defect.activo = bool(data["activo"])
    defect.save()
    return defect


# --- Lotes por inspeccionar ---------------------------------------------------------------------------------------

def latest_reception(lot_id):
    """Recepción de lavandería más reciente de un lote, o `None`."""
    return (
        RecepcionLote.objects.filter(lote_id=lot_id).select_related("recepcion__remision__lavanderia")
        .order_by("-recepcion__fecha_recepcion", "-id").first()
    )


def pending_lots():
    """Lotes por inspeccionar: con recepción de lavandería y prendas conformes, en planta, sin inspección y de orden vigente.
    Cada lote trae `recepcion_lote_id` y `por_inspeccionar` (lo recibido conforme en su recepción más reciente).
    """
    latest = RecepcionLote.objects.filter(lote=OuterRef("pk")).order_by("-recepcion__fecha_recepcion", "-id")
    return (
        Lote.objects.select_related("orden__referencia")
        .filter(estado_inventario=production_catalog.LOT_INV_INTERNAL)
        .exclude(orden__orden_salida__estado=inventory_catalog.STATUS_CANCELLED)
        .annotate(
            recepcion_lote_id=Subquery(latest.values("id")[:1]),
            por_inspeccionar=Subquery(latest.values("cantidad_recibida_conforme")[:1]),
            ya_inspeccionado=Exists(Inspeccion.objects.filter(lote=OuterRef("pk"))),
        )
        .filter(recepcion_lote_id__isnull=False, por_inspeccionar__gt=0, ya_inspeccionado=False)
        .order_by("orden_id", "numero")
    )


# --- Inspección (RF20) --------------------------------------------------------------------------------------------

def whole(value, message, field, minimum=0):
    """Entero a partir de lo que llegue en el JSON (rechaza booleanos, decimales y texto)."""
    text = "" if isinstance(value, bool) else str(value).strip()
    if not re.fullmatch(r"\d+", text) or int(text) < minimum:
        fail(message, field)
    return int(text)


def clean_defects(defects):
    """Líneas de marras `[(defecto, cantidad, nota)]`: defectos activos, sin repetir y con cantidades enteras mayores que cero."""
    if defects in (None, []):
        return []
    if not isinstance(defects, list):
        fail("El desglose de marras debe ser una lista.", "defectos")
    if len(defects) > catalog.MAX_DEFECT_LINES:
        fail(f"Se admiten máximo {catalog.MAX_DEFECT_LINES} defectos distintos por inspección.", "defectos")
    rows, seen = [], set()
    for number, item in enumerate(defects, start=1):
        if not isinstance(item, dict):
            fail(f"La fila {number} del desglose necesita el defecto y la cantidad.", "defectos")
        defect_id = item.get("defecto")
        if isinstance(defect_id, bool) or not isinstance(defect_id, int):
            fail(f"Elige el defecto de la fila {number}.", "defectos")
        if defect_id in seen:
            fail("Un defecto no puede repetirse: suma sus cantidades en una sola fila.", "defectos")
        seen.add(defect_id)
        defect = TipoDefecto.objects.filter(pk=defect_id).first()
        if defect is None or not defect.activo:
            fail(f"El defecto de la fila {number} no existe o está desactivado.", "defectos")
        amount = whole(item.get("cantidad"), f"La cantidad de «{defect.nombre}» debe ser un entero mayor que cero.", "defectos", 1)
        rows.append((defect, amount, str(item.get("nota") or "").strip()[:255]))
    return rows


@transaction.atomic
def register_inspection(*, user, lote_id, aptas, defectos=None, observaciones="", fecha=None):
    """Registra la inspección de un lote. Todo o nada: si algo falla no queda nada ni se gasta el consecutivo."""
    if isinstance(lote_id, bool) or not isinstance(lote_id, int):
        fail("Elige el lote que vas a inspeccionar.", "lote")
    lot = Lote.objects.select_for_update(of=("self",)).select_related("orden__orden_salida").filter(pk=lote_id).first()
    if lot is None:
        fail("El lote no existe.", "lote")
    if lot.orden.orden_salida.estado == inventory_catalog.STATUS_CANCELLED:
        fail(f"La orden {lot.orden.codigo} está anulada: no se inspeccionan sus lotes.", "lote")
    if Inspeccion.objects.filter(lote=lot).exists():
        raise AlreadyInspected({"lote": [f"El lote {lot.codigo} ya fue inspeccionado."]})
    reception = latest_reception(lot.pk)
    if reception is None or lot.estado_inventario != production_catalog.LOT_INV_INTERNAL:
        fail(f"El lote {lot.codigo} no tiene una recepción de lavandería lista para inspeccionar.", "lote")
    received = reception.cantidad_recibida_conforme
    if received < 1:
        fail(f"El lote {lot.codigo} no recibió prendas conformes de lavandería: no hay nada que inspeccionar.", "lote")

    good = whole(aptas, "Las prendas aptas deben ser un número entero, cero o más.", "aptas")
    rows = clean_defects(defectos)
    flawed = sum(amount for _, amount, _ in rows)
    if good + flawed != received:
        difference = received - (good + flawed)
        missing = abs(difference)
        word = ("falta" if missing == 1 else "faltan") if difference > 0 else ("sobra" if missing == 1 else "sobran")
        fail(
            f"Las aptas y las marras suman {good + flawed} y el lote trae {received}: {word} {missing}.", "aptas",
            recibidas=received,
        )

    inspection = Inspeccion.objects.create(
        codigo=next_code(catalog.INSPECTION_PREFIX), lote=lot, recepcion_lote=reception, cantidad_recibida=received,
        aptas=good, marras=flawed, observaciones=str(observaciones or "").strip()[:500], inspector=user,
        fecha=fecha or timezone.localdate(),
    )
    MarraDetalle.objects.bulk_create([
        MarraDetalle(
            inspeccion=inspection, tipo_defecto=defect, defecto_nombre=defect.nombre, corregible=defect.corregible,
            cantidad=amount, nota=note,
        )
        for defect, amount, note in rows
    ])
    return inspection
