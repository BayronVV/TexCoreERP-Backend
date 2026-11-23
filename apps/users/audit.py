"""Auditoría de operaciones críticas (HU 1.5): catálogo, registro y middleware.

Un middleware mira cada petición que modifica datos (POST, PUT, PATCH, DELETE) y, si la ruta está en
`AUDITED`, guarda quién la hizo, sobre qué y con qué resultado, también cuando la API la rechaza por falta
de permiso. Así ninguna vista nueva puede olvidarse de auditar y las vistas no cambian.

DRF deja el usuario autenticado en `request.user` de Django al terminar la vista, por eso el middleware lo
ve aunque la autenticación sea por JWT. El registro se escribe fuera de la operación (después de
la respuesta), de modo que un rechazo o un error no se pierde por un rollback.
"""
import json
import logging
import re

from . import trace
from .models import AuditRecord

logger = logging.getLogger(__name__)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
MAX_BODY = 20_000
SENSITIVE = re.compile(r"pass|token|secret|clave|authorization|api_?key|credential", re.IGNORECASE)

# (nombre de la ruta, método) -> (acción, entidad). Una acción puede llevar {accion}, el parámetro de la URL.
AUDITED = {
    # Producción: órdenes, tarifas, lotes (estados, consumo de material, asignaciones)
    ("produccion_ordenes", "POST"): ("orden_produccion.crear", "orden_produccion"),
    ("produccion_orden_anular", "POST"): ("orden_produccion.anular", "orden_produccion"),
    ("produccion_tarifas", "POST"): ("tarifa.modificar", "tarifa"),
    ("produccion_lote_accion", "POST"): ("lote.{accion}", "lote"),
    ("produccion_lote_asignar", "POST"): ("lote.asignar", "lote"),
    ("produccion_lote_desvincular", "POST"): ("lote.desvincular", "lote"),
    # Inventario y materiales
    ("inventario_ingresos", "POST"): ("inventario.ingreso", "movimiento"),
    ("inventario_ordenes", "POST"): ("inventario.orden", "orden_inventario"),
    ("inventario_orden_anular", "POST"): ("inventario.orden_anular", "orden_inventario"),
    ("compras_recepciones", "POST"): ("compras.recepcion", "recepcion"),
    ("compras_orden_aprobar", "POST"): ("compras.aprobar", "orden_compra"),
    ("compras_orden_cancelar", "POST"): ("compras.cancelar", "orden_compra"),
    ("compras_orden_cerrar", "POST"): ("compras.cerrar", "orden_compra"),
    ("lavanderia_remisiones", "POST"): ("lavanderia.remision", "remision"),
    ("lavanderia_recepciones", "POST"): ("lavanderia.recepcion", "recepcion"),
    # Producto terminado
    ("terminado_ingresos", "POST"): ("producto_terminado.ingreso", "movimiento_terminado"),
    ("terminado_ajustes", "POST"): ("producto_terminado.ajuste", "movimiento_terminado"),
    # Ventas: precios, facturas, cartera
    ("ventas_precio", "PUT"): ("precio.modificar", "referencia"),
    ("ventas_facturas", "POST"): ("factura.emitir", "factura"),
    ("ventas_factura_anular", "POST"): ("factura.anular", "factura"),
    ("ventas_factura_conciliar", "POST"): ("cartera.conciliar", "factura"),
    ("envios_guia_devolucion", "POST"): ("cartera.devolucion", "guia"),
    # Seguridad: roles, permisos y cuentas
    ("role_list", "POST"): ("rol.crear", "rol"),
    ("role_detail", "PATCH"): ("rol.modificar", "rol"),
    ("role_detail", "PUT"): ("rol.modificar", "rol"),
    ("role_detail", "DELETE"): ("rol.eliminar", "rol"),
    ("user_list", "POST"): ("usuario.crear", "usuario"),
    ("user_detail", "PATCH"): ("usuario.modificar", "usuario"),
    ("user_detail", "PUT"): ("usuario.modificar", "usuario"),
    ("user_detail", "DELETE"): ("usuario.eliminar", "usuario"),
    ("user_unlock", "POST"): ("usuario.desbloquear", "usuario"),
}


def sanitize(value, depth=0):
    """Copia de los datos enviados sin contraseñas ni tokens y con tamaños acotados."""
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        return {
            str(key)[:60]: ("***" if SENSITIVE.search(str(key)) else sanitize(item, depth + 1))
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item, depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def record(user, action, entity="", entity_id="", result=AuditRecord.EXITO, ip=None, detail=None):
    """Guarda una fila de auditoría. Nunca interrumpe la operación si algo falla."""
    try:
        AuditRecord.objects.create(
            user=user if getattr(user, "pk", None) else None,
            user_email=(getattr(user, "email", "") or "")[:254],
            action=action[:60],
            entity=entity[:40],
            entity_id=str(entity_id or "")[:40],
            result=result,
            ip=ip,
            detail=detail or {},
        )
    except Exception:  # noqa: BLE001 - la auditoría no debe tumbar la petición
        logger.exception("No se pudo guardar el registro de auditoría")


def _read_payload(request):
    """Datos JSON enviados (acotados). Los archivos y formularios no se guardan."""
    if "json" not in (request.META.get("CONTENT_TYPE") or ""):
        return None
    try:
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_BODY:
            return None
        return sanitize(json.loads(request.body or b"null"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def _result_for(status_code):
    if status_code < 400:
        return AuditRecord.EXITO
    if status_code == 403:
        return AuditRecord.RECHAZADO
    return AuditRecord.ERROR


def _message(response):
    data = getattr(response, "data", None)
    if isinstance(data, dict):
        text = data.get("detail") or json.dumps(sanitize(data), ensure_ascii=False)
    else:
        text = data if isinstance(data, str) else ""
    return str(text)[:200]


class AuditMiddleware:
    """Registra las operaciones críticas de la API (ver `AUDITED`)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in MUTATING or not request.path.startswith("/api/"):
            return self.get_response(request)
        payload = _read_payload(request)
        response = self.get_response(request)
        try:
            self._record(request, response, payload)
        except Exception:  # noqa: BLE001
            logger.exception("Falló la auditoría de %s %s", request.method, request.path)
        return response

    def _record(self, request, response, payload):
        match = getattr(request, "resolver_match", None)
        spec = AUDITED.get((match.url_name, request.method)) if match else None
        user = getattr(request, "user", None)
        # Sin sesión (401) no hay a quién atribuirlo: eso queda en el registro de accesos.
        if spec is None or user is None or not getattr(user, "is_authenticated", False):
            return
        action, entity = spec
        kwargs = match.kwargs
        entity_id = kwargs.get("pk") or kwargs.get("referencia") or ""
        data = getattr(response, "data", None)
        if not entity_id and isinstance(data, dict) and response.status_code < 400:
            entity_id = data.get("id") or ""
        status_code = response.status_code
        detail = {"http": status_code, "metodo": request.method, "ruta": request.path[:200]}
        if payload is not None:
            detail["datos"] = payload
        if status_code >= 400:
            detail["motivo"] = _message(response)
        record(
            user,
            action.format(accion=kwargs.get("accion", "")),
            entity,
            entity_id,
            _result_for(status_code),
            ip=trace.client_ip(request),
            detail=detail,
        )
