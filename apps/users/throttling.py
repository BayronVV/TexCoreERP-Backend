"""Límites por IP que usan el mismo criterio de IP que el registro de accesos (`trace.client_ip`)."""
from rest_framework.throttling import ScopedRateThrottle

from . import trace


class ClientIPScopedRateThrottle(ScopedRateThrottle):
    """`ScopedRateThrottle` que identifica al cliente con `trace.client_ip` (detrás de Cloudflare/Render
    la conexión es la del proxy: todos los clientes compartirían el mismo contador)."""

    def get_ident(self, request):
        return trace.client_ip(request) or super().get_ident(request)
