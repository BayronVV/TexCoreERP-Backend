"""Consulta de los accesos al sistema (HU 1.5): quién entró, cuándo, desde qué IP y con qué resultado."""
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination

from . import catalog, trace
from .models import AccessLog

EVENT_LABELS = {
    trace.REGISTER: "Registro de cuenta",
    trace.LOGIN_OK: "Inicio de sesión",
    trace.LOGIN_FAIL: "Inicio de sesión fallido",
    trace.ACCOUNT_LOCKED: "Cuenta bloqueada",
    trace.BLOCKED_ATTEMPT: "Intento con la cuenta bloqueada",
    trace.UNLOCK: "Cuenta desbloqueada",
}
# Resultado de cada evento: lo que el Administrador filtra («fallidos de la última semana»).
RESULT_BY_EVENT = {
    trace.REGISTER: "exitoso",
    trace.LOGIN_OK: "exitoso",
    trace.UNLOCK: "exitoso",
    trace.LOGIN_FAIL: "fallido",
    trace.BLOCKED_ATTEMPT: "bloqueado",
    trace.ACCOUNT_LOCKED: "bloqueado",
}
RESULTS = ("exitoso", "fallido", "bloqueado")


class AccessLogSerializer(serializers.ModelSerializer):
    """Un acceso: fecha, usuario, evento, resultado e IP. No incluye cabeceras ni datos sensibles."""

    user_name = serializers.SerializerMethodField()
    event_label = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()

    class Meta:
        model = AccessLog
        fields = ["id", "created_at", "user", "email", "user_name", "event", "event_label", "result", "ip"]
        read_only_fields = fields

    def get_user_name(self, row) -> str:
        return (row.user.get_full_name() or row.user.email) if row.user else ""

    def get_event_label(self, row) -> str:
        return EVENT_LABELS.get(row.event, row.event)

    def get_result(self, row) -> str:
        return RESULT_BY_EVENT.get(row.event, "")


class AccessPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def _date_param(params, name):
    raw = params.get(name)
    if not raw:
        return None
    value = parse_date(raw)
    if value is None:
        raise ValidationError({name: "Usa el formato AAAA-MM-DD."})
    return value


@extend_schema(
    tags=["users"], summary="Consultar los accesos al sistema (HU 1.5)",
    description="Solo lectura y paginado, del más reciente al más antiguo. Exige `seguridad.accesos` (Administrador).",
    parameters=[
        OpenApiParameter("user", int, description="Id del usuario"),
        OpenApiParameter("q", str, description="Parte del correo"),
        OpenApiParameter("event", str, description="Evento: " + ", ".join(EVENT_LABELS)),
        OpenApiParameter("result", str, description="exitoso, fallido o bloqueado"),
        OpenApiParameter("ip", str, description="IP exacta"),
        OpenApiParameter("date_from", str, description="Desde (AAAA-MM-DD), inclusive"),
        OpenApiParameter("date_to", str, description="Hasta (AAAA-MM-DD), inclusive"),
    ],
)
class AccessLogListView(generics.ListAPIView):
    """Lista los accesos con filtros por usuario, evento, resultado, IP y fechas."""

    required_permissions = {"GET": catalog.ACCESS_VIEW}
    serializer_class = AccessLogSerializer
    pagination_class = AccessPagination

    def get_queryset(self):
        params = self.request.query_params
        rows = AccessLog.objects.select_related("user").order_by("-created_at", "-id")
        if params.get("user"):
            if not params["user"].isdigit():
                raise ValidationError({"user": "Debe ser el id del usuario."})
            rows = rows.filter(user_id=int(params["user"]))
        if params.get("q"):
            rows = rows.filter(email__icontains=params["q"].strip())
        if params.get("event"):
            if params["event"] not in EVENT_LABELS:
                raise ValidationError({"event": "Evento desconocido."})
            rows = rows.filter(event=params["event"])
        if params.get("result"):
            if params["result"] not in RESULTS:
                raise ValidationError({"result": "Usa exitoso, fallido o bloqueado."})
            rows = rows.filter(event__in=[e for e, r in RESULT_BY_EVENT.items() if r == params["result"]])
        if params.get("ip"):
            rows = rows.filter(ip=params["ip"].strip())
        date_from, date_to = _date_param(params, "date_from"), _date_param(params, "date_to")
        if date_from:
            rows = rows.filter(created_at__date__gte=date_from)
        if date_to:
            rows = rows.filter(created_at__date__lte=date_to)
        return rows
