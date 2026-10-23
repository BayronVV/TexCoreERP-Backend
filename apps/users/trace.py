"""Origen de las peticiones: IP del cliente detrás del proxy de Render y rastro de accesos."""
import ipaddress
import logging

from django.conf import settings
from django.db import transaction

from .models import AccessLog

logger = logging.getLogger(__name__)

REGISTER = "registro"
LOGIN_OK = "login_ok"
LOGIN_FAIL = "login_fallido"


def _valid(value):
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def client_ip(request):
    """IP de quien hizo la petición, no la del proxy.

    Render pone Cloudflare delante: `CF-Connecting-IP` la fija Cloudflare y el cliente no puede
    cambiarla. Si no viene, se usa `X-Forwarded-For` contando desde la derecha (NUM_PROXIES) para
    no fiarse de lo que el cliente escriba a la izquierda; sin proxies declarados, la conexión.
    """
    meta = request.META
    for header in ("HTTP_CF_CONNECTING_IP", "HTTP_TRUE_CLIENT_IP"):
        ip = _valid(meta.get(header))
        if ip:
            return ip
    chain = [part.strip() for part in meta.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
    hops = settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0
    if hops and len(chain) >= hops:
        ip = _valid(chain[-hops])
        if ip:
            return ip
    return _valid(meta.get("REMOTE_ADDR"))


def record(request, event, user=None, email=""):
    """Guarda el acceso sin interrumpir la petición si algo falla."""
    meta = request.META
    forwarded = "cf={} xff={} ra={}".format(
        meta.get("HTTP_CF_CONNECTING_IP", ""), meta.get("HTTP_X_FORWARDED_FOR", ""), meta.get("REMOTE_ADDR", "")
    )
    try:
        with transaction.atomic():
            AccessLog.objects.create(
                user=user,
                email=(email or "")[:254],
                event=event,
                ip=client_ip(request),
                forwarded=forwarded[:300],
                user_agent=meta.get("HTTP_USER_AGENT", "")[:255],
            )
    except Exception:  # noqa: BLE001 - el rastro nunca debe tumbar el login ni el registro
        logger.exception("No se pudo guardar el acceso")
