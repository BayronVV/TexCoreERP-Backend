"""
Cliente delgado de la API de Track123 (HU 7.2). Solo usa la biblioteca estándar.

Hechos verificados con la clave del PO (8/nov/2026), que corrigen la documentación:
- Las rutas vigentes son `/tk/v2.1/...`. Registrar (`track/import`) gasta 1 de cuota por guía; consultar (`track/query`) no gasta.
- La autodetección de transportadora falló en 2 de 3 guías reales de Interrapidísimo: el `courierCode` siempre va explícito.
- Una clave inválida NO responde con error HTTP: responde 200 con `code = B0001`.
- Una guía no registrada responde 200 con la guía en `data.rejected` y `error.msg = "trackNo not registered"`.

La clave sale de `settings.TRACK123_API_KEY`; nunca se imprime, se registra ni viaja en un mensaje de error.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings

from . import catalog


class Track123Error(Exception):
    """Falla al hablar con Track123. `kind`: `auth`, `rate`, `network` o `api`. El mensaje nunca contiene la clave."""

    def __init__(self, message, kind="api", code=""):
        super().__init__(message)
        self.kind = kind
        self.code = code


def default_transport(method, url, headers, body):
    """Envía la petición y devuelve `(estado_http, json)`. Se reemplaza en las pruebas: nunca llaman a la API real."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=settings.TRACK123_TIMEOUT) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8"))
        except ValueError:
            return error.code, {}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise Track123Error("No se pudo comunicar con el servicio de rastreo.", kind="network") from error


class Track123Client:
    def __init__(self, api_key, base_url=None, transport=None):
        self.api_key = api_key
        self.base_url = (base_url or settings.TRACK123_BASE_URL).rstrip("/")
        self.transport = transport or default_transport

    def _call(self, method, path, body=None):
        headers = {"Track123-Api-Secret": self.api_key, "Content-Type": "application/json"}
        status, data = self.transport(method, f"{self.base_url}{path}", headers, body)
        data = data if isinstance(data, dict) else {}
        code = str(data.get("code", ""))
        if code == catalog.TRACKING_OK_CODE:
            return data.get("data") or {}
        if code in catalog.TRACKING_AUTH_CODES or status in (401, 403):
            raise Track123Error("La clave de Track123 no es válida o no tiene permiso.", kind="auth", code=code)
        if code in catalog.TRACKING_RATE_CODES or status == 429:
            raise Track123Error("Track123 recibió demasiadas consultas: intenta de nuevo en un momento.", kind="rate", code=code)
        raise Track123Error(f"Track123 respondió con un error ({code or status}).", kind="api", code=code)

    def quota(self):
        """`{total, restante}` de registros de guías del ciclo actual."""
        data = self._call("GET", "/account/quota")
        return {"total": int(data.get("quotaTotal", 0)), "restante": int(data.get("quotaRemain", 0))}

    def register(self, items):
        """Inscribe guías (gasta 1 de cuota por guía). `items`: `[{"trackNo", "courierCode"}]`. Devuelve `(aceptadas, rechazadas)`."""
        data = self._call("POST", "/track/import", items)
        return data.get("accepted") or [], data.get("rejected") or []

    def query(self, items):
        """Consulta guías ya inscritas (no gasta cuota). Devuelve `(resultados, rechazadas)`."""
        data = self._call("POST", "/track/query", {"trackNoInfos": items})
        accepted = data.get("accepted") or {}
        return (accepted.get("content") or []), data.get("rejected") or []


def get_client(transport=None):
    """Cliente listo para usar, o `None` si el rastreo está apagado o sin clave."""
    if not settings.TRACK123_ENABLED or not settings.TRACK123_API_KEY:
        return None
    return Track123Client(settings.TRACK123_API_KEY, transport=transport)
