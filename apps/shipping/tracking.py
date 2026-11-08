"""
Rastreo de guías con Track123 (HU 7.2).

Principios:
- **Nunca automático.** Solo se consulta cuando alguien pulsa «Consultar estado» (o por la siembra de demostración).
- **Cuota cuidada.** Registrar una guía nueva gasta 1 de las 50 del plan: se hace una sola vez por guía, con una reserva mínima y avisando.
  Consultar no gasta. La última respuesta queda guardada y la pantalla la reutiliza sin volver a llamar.
- **Nunca bloquea.** Si la API falla, la guía no cambia y se devuelve un mensaje claro: vender y despachar no dependen de Track123.
- **Solo propone.** El estado que trae la transportadora pasa por la misma tabla de transiciones; lo que no encaja se ignora con aviso.
"""
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.inventory.services import fail

from . import catalog, track123
from .models import Guia
from .services import advance_to, lock_guide


class TrackingCooldown(APIException):
    """429: la guía se consultó hace muy poco."""
    status_code = 429
    default_code = "rastreo_en_espera"


class TrackingUnavailable(APIException):
    """503: el servicio de rastreo no respondió o no está configurado. La guía no cambia."""
    status_code = 503
    default_detail = "El servicio de rastreo no está disponible. La guía conserva su último estado."
    default_code = "rastreo_no_disponible"


# --- Mapeo de estados ---------------------------------------------------------------------------------------------------------------

def map_status(transit_status, sub_status=""):
    """Estado de nuestra guía que corresponde al de Track123, o `None` si no aporta información (INIT, NO_RECORD, EXPIRED)."""
    transit_status = (transit_status or "").strip()
    sub_status = (sub_status or "").strip()
    if transit_status in catalog.TRACK_DELIVERED:
        return catalog.DELIVERED
    if sub_status in catalog.TRACK_RETURNED_SUB:
        return catalog.RETURNED  # en Track123 no hay «devuelto»: viene dentro de ABNORMAL
    if transit_status in catalog.TRACK_INCIDENT or sub_status in catalog.TRACK_INCIDENT_SUB:
        return catalog.INCIDENT
    if transit_status in catalog.TRACK_IN_TRANSIT:
        return catalog.IN_TRANSIT
    return None


def last_event(result):
    """Evento más reciente de Track123 (la lista viene en orden cronológico inverso)."""
    details = ((result.get("localLogisticsInfo") or {}).get("trackingDetails")) or []
    return details[0] if details else {}


def describe(result):
    """Texto corto de lo último que reportó la transportadora."""
    event = last_event(result)
    sub = result.get("transitSubStatus") or event.get("transitSubStatus") or ""
    text = str(event.get("eventDetail") or catalog.TRACK_SUB_NAMES.get(sub, "")).strip()
    place = str(event.get("address") or "").strip()
    return (f"{text} ({place})" if text and place else text or place)[:255]


def parse_time(value):
    """Fecha y hora de Track123 (`AAAA-MM-DD HH:MM:SS`, sin zona) como datetime con la zona del proyecto."""
    if not value:
        return None
    try:
        naive = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return timezone.make_aware(naive, timezone.get_default_timezone())


# --- Cuota y disponibilidad --------------------------------------------------------------------------------------------------------

def tracking_status(client=None):
    """Estado del rastreo para la pantalla. Si está habilitado intenta leer la cuota (no gasta); si falla, lo dice sin romper."""
    enabled = bool(settings.TRACK123_ENABLED and settings.TRACK123_API_KEY)
    info = {"habilitado": enabled, "reserva": settings.TRACK123_QUOTA_RESERVE, "enfriamiento_minutos": settings.TRACK123_COOLDOWN_MINUTES,
            "total": None, "restante": None, "mensaje": ""}
    if not enabled:
        info["mensaje"] = "El rastreo con Track123 está apagado."
        return info
    try:
        quota = (client or track123.get_client()).quota()
        info.update(total=quota["total"], restante=quota["restante"])
        if quota["restante"] <= settings.TRACK123_QUOTA_RESERVE:
            info["mensaje"] = "La cuota de registros está en la reserva: no se inscribirán guías nuevas."
    except track123.Track123Error as error:
        info["mensaje"] = str(error)
    return info


def supports_tracking(guide):
    return guide.transportadora in catalog.TRACKING_COURIERS


# --- Consulta ----------------------------------------------------------------------------------------------------------------------

def _result_for(results, number):
    for item in results:
        if str(item.get("trackNo", "")) == number:
            return item
    return None


def refresh_tracking(*, guide_id, user, force=False, client=None):
    """Consulta a Track123 el estado de una guía, lo guarda y lo aplica con las reglas de transición.

    Devuelve `(guía, aviso)`: `aviso` explica lo que se ignoró o no se pudo hacer. La llamada HTTP se hace fuera de la transacción.
    """
    guide = Guia.objects.select_related("factura").filter(pk=guide_id).first()
    if guide is None:
        raise Http404("La guía no existe.")
    if not guide.vigente or guide.estado == catalog.VOIDED:
        fail("Esta guía está anulada o fue reemplazada: no se rastrea.", "estado")
    if not supports_tracking(guide):
        fail(f"El rastreo automático solo está disponible para Interrapidísimo; los estados de {catalog.CARRIER_NAMES[guide.transportadora]} se cambian a mano.", "transportadora")
    client = client or track123.get_client()
    if client is None:
        raise TrackingUnavailable("El rastreo con Track123 está apagado o sin clave. La guía conserva su último estado.")
    now = timezone.now()
    if not force and guide.rastreo_proxima_consulta and guide.rastreo_proxima_consulta > now:
        seconds = int((guide.rastreo_proxima_consulta - now).total_seconds())
        raise TrackingCooldown({"detail": [f"Esta guía se consultó hace poco: intenta de nuevo en {max(seconds // 60, 1)} min."], "segundos": seconds})
    if not force and guide.estado in (catalog.DELIVERED, catalog.RETURNED) and guide.rastreo_respuesta:
        fail("La guía ya llegó a un estado final y su última respuesta está guardada.", "estado")

    code = catalog.TRACKING_COURIERS[guide.transportadora]
    item = {"trackNo": guide.numero_guia, "courierCode": code}
    warning = ""
    try:
        if not guide.rastreo_registrado:
            quota = client.quota()
            if quota["restante"] <= settings.TRACK123_QUOTA_RESERVE:
                fail(f"La cuota de registros de Track123 está en la reserva ({quota['restante']} restantes): no se inscriben guías nuevas.", "rastreo")
            _, rejected = client.register([item])
            bad = [r for r in rejected if (r.get("error") or {}).get("code") != catalog.TRACKING_ALREADY_REGISTERED_CODE]
            if bad:
                fail("Track123 rechazó la guía: " + str((bad[0].get("error") or {}).get("msg", "motivo desconocido")), "rastreo")
        results, rejected = client.query([item])
    except track123.Track123Error as error:
        raise TrackingUnavailable(f"{error} La guía conserva su último estado.") from error

    result = _result_for(results, guide.numero_guia)
    not_registered = any(catalog.TRACKING_NOT_REGISTERED in str((r.get("error") or {}).get("msg", "")) for r in rejected)
    with transaction.atomic():
        guide = lock_guide(guide.id)
        guide.rastreo_registrado = not not_registered
        guide.rastreo_consultado_en = now
        guide.rastreo_proxima_consulta = now + timedelta(minutes=settings.TRACK123_COOLDOWN_MINUTES)
        if result is not None:
            guide.rastreo_estado = str(result.get("transitStatus") or "")
            guide.rastreo_subestado = str(result.get("transitSubStatus") or "")
            guide.rastreo_respuesta = result
            guide.rastreo_sintetico = False
        guide.save(update_fields=["rastreo_registrado", "rastreo_consultado_en", "rastreo_proxima_consulta", "rastreo_estado", "rastreo_subestado",
                                  "rastreo_respuesta", "rastreo_sintetico", "updated_at"])
        if result is None:
            return guide, "Track123 no devolvió información para esta guía: se conserva el último estado."
        target = map_status(result.get("transitStatus"), result.get("transitSubStatus"))
        if target is None:
            return guide, "Sin información de la transportadora todavía: se conserva el último estado."
        if target == guide.estado:
            return guide, warning
        when = parse_time(result.get("deliveredTime")) if target == catalog.DELIVERED else None
        if advance_to(guide, target, describe(result) or catalog.STATE_NAMES[target], catalog.ORIGIN_TRACK123, user, when) is None:
            warning = (f"La transportadora reporta «{catalog.STATE_NAMES[target].lower()}», pero la guía está «{catalog.STATE_NAMES[guide.estado].lower()}» "
                       "y esa transición no se aplica automáticamente.")
    return guide, warning
