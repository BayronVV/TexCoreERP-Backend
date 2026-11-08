"""
Guías de envío y despachos (HU 7.2).

- Una factura tiene una sola guía vigente. `FacturaVenta.transportadora` y `numero_guia` son su espejo y solo se escriben aquí.
- Todo cambio de estado sigue la tabla de transiciones de `catalog.TRANSITIONS` y deja un evento (solo inserción).
- La relación de despacho es atómica: si una guía no sirve no cambia ninguna ni se gasta el consecutivo `RD`.
- La devolución física reutiliza `reconcile_collection` de la HU 7.3: el stock se reingresa una sola vez y la factura queda en devolución.
- Las consultas con bloqueo usan `of=("self",)`: PostgreSQL no admite bloquear el lado opcional de un join.
"""
import re
import uuid
from collections import deque

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.inventory.services import fail, next_code
from apps.sales import catalog as sales_catalog
from apps.sales import invoicing as sales_invoicing
from apps.sales.models import FacturaVenta

from . import catalog
from .models import EventoGuia, Guia, RelacionDespacho

MAX_FREIGHT = 10_000_000


class AlreadyDispatched(APIException):
    """409: ese formulario ya generó su relación de despacho (doble clic o reintento)."""
    status_code = 409
    default_detail = "Esta relación de despacho ya fue creada."
    default_code = "ya_despachada"


# --- Utilidades --------------------------------------------------------------------------------------------------------------------

def normalize_number(value):
    """Número de guía sin espacios: lo que se teclea o se pega no debe distinguir una guía de otra."""
    return "".join(str(value or "").split())


def format_warning(carrier, number):
    """Aviso (no bloqueo) si el número no tiene la forma habitual de la transportadora."""
    if carrier == "INTERRAPIDISIMO" and not re.match(catalog.INTERRAPIDISIMO_FORMAT, number):
        return "Las guías de Interrapidísimo suelen tener 12 dígitos: revisa el número."
    return ""


def clean_guide_input(carrier, number):
    carrier = str(carrier or "").strip()
    if carrier not in catalog.CARRIER_NAMES:
        fail("Elige una transportadora de la lista.", "transportadora")
    number = normalize_number(number)
    if not number:
        fail("Escribe el número de guía.", "numero_guia")
    if len(number) > catalog.MAX_GUIDE_LENGTH:
        fail(f"El número de guía admite máximo {catalog.MAX_GUIDE_LENGTH} caracteres.", "numero_guia")
    return carrier, number


def clean_token(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        fail("Falta el identificador único del formulario: recarga la página.", "token")


def record_event(guide, before, after, note="", origin=catalog.ORIGIN_MANUAL, user=None):
    return EventoGuia.objects.create(guia=guide, estado_antes=before, estado_despues=after, nota=str(note or "")[:255], origen=origin, usuario=user)


def lock_guide(guide_id):
    """Guía bloqueada para modificarla (404 si no existe)."""
    guide = Guia.objects.select_for_update(of=("self",)).filter(pk=guide_id).first()
    if guide is None:
        raise Http404("La guía no existe.")
    return guide


# --- Cambios de estado -------------------------------------------------------------------------------------------------------------

def _mirror(invoice, carrier="", number=""):
    invoice.transportadora = carrier
    invoice.numero_guia = number
    invoice.save(update_fields=["transportadora", "numero_guia", "updated_at"])


def _move(guide, target, note="", origin=catalog.ORIGIN_MANUAL, user=None, when=None, clear_mirror=True):
    """Un solo paso de la máquina de estados. Quien llama ya validó que la transición existe."""
    when = when or timezone.now()
    before = guide.estado
    guide.estado = target
    fields = ["estado", "updated_at"]
    if target == catalog.IN_TRANSIT:
        guide.despachada_en = guide.despachada_en or when
        guide.novedad = ""
        fields += ["despachada_en", "novedad"]
    elif target == catalog.INCIDENT:
        guide.novedad = str(note or "")[:255]
        fields.append("novedad")
    elif target == catalog.DELIVERED:
        guide.entregada_en = when
        guide.novedad = ""
        fields += ["entregada_en", "novedad"]
    elif target == catalog.RETURNED:
        guide.devuelta_en = when
        guide.novedad = str(note or "")[:255]
        guide.flete_vendedor = guide.valor_flete or 0  # el flete de una devolución se le descuenta al vendedor (solo se reporta)
        fields += ["devuelta_en", "novedad", "flete_vendedor"]
    elif target == catalog.VOIDED:
        guide.vigente = False
        fields.append("vigente")
    guide.save(update_fields=fields)
    record_event(guide, before, target, note, origin, user)
    if target == catalog.VOIDED and clear_mirror:
        _mirror(guide.factura)


def _path(start, target):
    """Camino más corto entre dos estados por la tabla de transiciones; `None` si no existe."""
    if start == target:
        return []
    queue, seen = deque([(start, [])]), {start}
    while queue:
        state, path = queue.popleft()
        for following in sorted(catalog.TRANSITIONS.get(state, ())):
            if following in seen:
                continue
            if following == target:
                return path + [following]
            seen.add(following)
            queue.append((following, path + [following]))
    return None


def advance_to(guide, target, note="", origin=catalog.ORIGIN_TRACK123, user=None, when=None):
    """Lleva la guía hasta `target` pasando por los estados intermedios (una guía que ya llegó puede seguir «por despachar» en el sistema).

    Devuelve los estados recorridos; `None` si la transición no es posible (p. ej. un estado final) y entonces no cambia nada.
    """
    path = _path(guide.estado, target)
    if path is None:
        return None
    for state in path:
        _move(guide, state, note if state == path[-1] else "Pasó por este estado antes de llegar al actual", origin, user, when)
    return path


@transaction.atomic
def change_state(*, guide_id, new_state, note="", user):
    """Cambio manual de estado con las reglas de la tabla de transiciones. Novedad y devolución exigen explicar qué pasó."""
    guide = lock_guide(guide_id)
    if new_state not in catalog.STATE_NAMES:
        fail("Estado de guía inválido.", "estado")
    if not guide.vigente:
        fail("Esta guía fue reemplazada: gestiona la guía vigente de la factura.", "estado")
    if new_state not in catalog.TRANSITIONS.get(guide.estado, set()):
        fail(f"Una guía «{catalog.STATE_NAMES[guide.estado].lower()}» no puede pasar a «{catalog.STATE_NAMES[new_state].lower()}».", "estado")
    note = str(note or "").strip()
    if new_state in catalog.NOTE_REQUIRED and len(note) < catalog.MIN_NOTE:
        fail(f"Explica qué pasó (mínimo {catalog.MIN_NOTE} caracteres).", "nota")
    if len(note) > 255:
        fail("La nota admite máximo 255 caracteres.", "nota")
    _move(guide, new_state, note, catalog.ORIGIN_MANUAL, user)
    return guide


# --- Asignar la guía a una factura -------------------------------------------------------------------------------------------------

@transaction.atomic
def assign_guide_to(invoice, carrier, number, user, origin=catalog.ORIGIN_MANUAL):
    """Crea la guía vigente de una factura (la factura ya viene bloqueada o recién creada). Reemplaza la anterior solo si no se despachó."""
    if invoice.estado != sales_catalog.STATUS_ISSUED:
        fail("No se puede asignar una guía a una factura anulada.", "factura")
    if invoice.estado_cobro == sales_catalog.COLLECT_RETURNED:
        fail("La factura ya fue gestionada como devolución.", "factura")
    carrier, number = clean_guide_input(carrier, number)
    current = Guia.objects.select_for_update(of=("self",)).filter(factura=invoice, vigente=True).first()
    if current is not None and current.transportadora == carrier and current.numero_guia == number:
        return current
    clash = Guia.objects.filter(transportadora=carrier, numero_guia=number, vigente=True).exclude(factura=invoice).select_related("factura").first()
    if clash is not None:
        fail(f"La guía {number} de {catalog.CARRIER_NAMES[carrier]} ya está asignada a la factura {clash.factura.numero}.", "numero_guia")
    if current is not None:
        if current.estado != catalog.PENDING:
            fail(f"La guía vigente ya fue despachada ({catalog.STATE_NAMES[current.estado].lower()}) y no se puede reemplazar.", "numero_guia")
        _move(current, catalog.VOIDED, f"Reemplazada por la guía {number} de {catalog.CARRIER_NAMES[carrier]}", origin, user, clear_mirror=False)
    try:
        with transaction.atomic():
            guide = Guia.objects.create(factura=invoice, transportadora=carrier, numero_guia=number, estado=catalog.PENDING)
    except IntegrityError:
        fail(f"La guía {number} de {catalog.CARRIER_NAMES[carrier]} ya está asignada a otra factura.", "numero_guia")
    record_event(guide, "", catalog.PENDING, "Guía asignada a la factura", origin, user)
    _mirror(invoice, carrier, number)
    return guide


@transaction.atomic
def assign_guide(*, invoice_id, carrier, number, user):
    """Asigna o reemplaza la guía de una factura ya emitida («Por despachar / sin guía»)."""
    invoice = FacturaVenta.objects.select_for_update(of=("self",)).filter(pk=invoice_id).first()
    if invoice is None:
        raise Http404("La factura no existe.")
    return assign_guide_to(invoice, carrier, number, user)


def release_guide_for_cancellation(invoice, user):
    """Se llama al anular una factura: con guía despachada se rechaza; con guía por despachar se anula la guía."""
    guide = Guia.objects.select_for_update(of=("self",)).filter(factura=invoice, vigente=True).first()
    if guide is None:
        return
    if guide.estado in catalog.DISPATCHED_STATES:
        fail(f"No se puede anular la factura: su guía ya fue despachada ({catalog.STATE_NAMES[guide.estado].lower()}).", "estado")
    if guide.estado == catalog.PENDING:
        _move(guide, catalog.VOIDED, f"Factura {invoice.numero} anulada", catalog.ORIGIN_SYSTEM, user, clear_mirror=False)


# --- Relación de despacho ----------------------------------------------------------------------------------------------------------

def _already(relation):
    return AlreadyDispatched({"detail": [f"Esta relación ya se creó como {relation.codigo}."], "relacion": relation.id, "codigo": relation.codigo})


@transaction.atomic
def _dispatch(*, user, carrier, guide_ids, token, when, responsible, notes):
    if carrier not in catalog.CARRIER_NAMES:
        fail("Elige una transportadora de la lista.", "transportadora")
    if not isinstance(guide_ids, list) or not guide_ids:
        fail("Elige al menos una guía para la relación.", "guias")
    if len(guide_ids) > catalog.MAX_DISPATCH_GUIDES:
        fail(f"Una relación admite máximo {catalog.MAX_DISPATCH_GUIDES} guías.", "guias")
    if any(isinstance(g, bool) or not isinstance(g, int) for g in guide_ids) or len(set(guide_ids)) != len(guide_ids):
        fail("La lista de guías es inválida o repite una guía.", "guias")
    guides = {g.id: g for g in Guia.objects.select_for_update(of=("self",)).select_related("factura").filter(pk__in=guide_ids).order_by("id")}
    problems = []
    for guide_id in guide_ids:
        guide = guides.get(guide_id)
        if guide is None:
            problems.append(f"La guía {guide_id} no existe.")
        elif not guide.vigente or guide.estado != catalog.PENDING:
            problems.append(f"La guía {guide.numero_guia} no está por despachar (está {catalog.STATE_NAMES[guide.estado].lower()}).")
        elif guide.transportadora != carrier:
            problems.append(f"La guía {guide.numero_guia} es de {catalog.CARRIER_NAMES[guide.transportadora]}, no de {catalog.CARRIER_NAMES[carrier]}.")
        elif guide.factura.estado != sales_catalog.STATUS_ISSUED:
            problems.append(f"La factura {guide.factura.numero} de la guía {guide.numero_guia} está anulada.")
    if problems:
        fail(" ".join(problems), "guias")
    relation = RelacionDespacho.objects.create(
        codigo=next_code(catalog.DISPATCH_PREFIX), transportadora=carrier, fecha=when or timezone.localdate(),
        responsable=str(responsible or "").strip()[:120], observaciones=str(notes or "").strip()[:255], token=token, creada_por=user,
    )
    for guide_id in sorted(guides):
        guide = guides[guide_id]
        guide.relacion = relation
        guide.save(update_fields=["relacion", "updated_at"])
        _move(guide, catalog.IN_TRANSIT, f"Despachada en la relación {relation.codigo}", catalog.ORIGIN_MANUAL, user)
    return relation


def create_dispatch(*, user, carrier, guide_ids, token, when=None, responsible="", notes=""):
    """Crea la relación de despacho y pasa todas sus guías a EN_TRANSITO. Un token repetido responde 409 con la relación ya creada."""
    token = clean_token(token)
    existing = RelacionDespacho.objects.filter(token=token).first()
    if existing is not None:
        raise _already(existing)
    try:
        return _dispatch(user=user, carrier=carrier, guide_ids=guide_ids, token=token, when=when, responsible=responsible, notes=notes)
    except IntegrityError:  # otro envío con el mismo token ganó la carrera
        existing = RelacionDespacho.objects.filter(token=token).first()
        if existing is None:
            raise
        raise _already(existing)


# --- Flete y devolución física -----------------------------------------------------------------------------------------------------

@transaction.atomic
def register_freight(*, guide_id, value, user):
    """Costo del flete de la guía. En una guía devuelta es el flete que se le descuenta al vendedor (solo se registra y reporta)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_FREIGHT:
        fail(f"El flete debe ser un entero en pesos entre 0 y {MAX_FREIGHT:,}.".replace(",", "."), "valor_flete")
    guide = lock_guide(guide_id)
    if guide.estado == catalog.VOIDED or not guide.vigente:
        fail("No se registra flete en una guía anulada o reemplazada.", "valor_flete")
    guide.valor_flete = value
    fields = ["valor_flete", "updated_at"]
    if guide.estado == catalog.RETURNED:
        guide.flete_vendedor = value
        fields.append("flete_vendedor")
    guide.save(update_fields=fields)
    record_event(guide, guide.estado, guide.estado, f"Flete registrado: ${value:,}".replace(",", "."), catalog.ORIGIN_MANUAL, user)
    return guide


@transaction.atomic
def return_to_stock(*, guide_id, user):
    """La guía devuelta ya llegó a la bodega: registra la devolución en cartera (HU 7.3), que reingresa el stock una sola vez."""
    guide = lock_guide(guide_id)
    if guide.estado != catalog.RETURNED or not guide.vigente:
        fail("Solo se registra la devolución de una guía devuelta.", "estado")
    invoice = FacturaVenta.objects.select_for_update(of=("self",)).get(pk=guide.factura_id)
    if invoice.estado_cobro != sales_catalog.COLLECT_PENDING:
        name = sales_catalog.COLLECT_STATE_NAMES.get(invoice.estado_cobro, invoice.estado_cobro)
        fail(f"La factura ya fue gestionada como {name.lower()}.", "estado_cobro")
    reason = (guide.novedad or "Devolución del paquete por la transportadora")[:255]
    sales_invoicing.reconcile_collection(user=user, factura_id=invoice.id, nuevo_estado=sales_catalog.COLLECT_RETURNED, motivo=reason)
    record_event(guide, guide.estado, guide.estado, "Devolución registrada en cartera: las prendas volvieron al inventario", catalog.ORIGIN_MANUAL, user)
    return guide


# --- Consultas ---------------------------------------------------------------------------------------------------------------------

def invoices_without_guide():
    """Facturas emitidas, aún sin cobrar, que no tienen una guía vigente (la guía debe anotarse lo antes posible)."""
    has_guide = Guia.objects.filter(factura=OuterRef("pk"), vigente=True)
    return (
        FacturaVenta.objects.filter(estado=sales_catalog.STATUS_ISSUED, estado_cobro=sales_catalog.COLLECT_PENDING)
        .annotate(tiene_guia=Exists(has_guide)).filter(tiene_guia=False).select_related("vendedor").order_by("created_at", "id")
    )


def hours_without_guide(invoice, now=None):
    """Horas enteras que lleva la factura sin guía."""
    delta = (now or timezone.now()) - invoice.created_at
    return max(int(delta.total_seconds() // 3600), 0)


def urgency(hours):
    """`vencida` desde OVERDUE_HOURS, `atencion` desde ATTENTION_HOURS y `normal` antes."""
    if hours >= catalog.OVERDUE_HOURS:
        return "vencida"
    if hours >= catalog.ATTENTION_HOURS:
        return "atencion"
    return "normal"
