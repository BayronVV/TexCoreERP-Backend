"""Consulta de la auditoría de operaciones críticas (HU 1.5): solo lectura, para Administrador y Gerente."""
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import generics, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import catalog
from .accesos import AccessPagination, _date_param
from .audit import AUDITED
from .models import AuditRecord

ACTIONS = sorted({action.replace("{accion}", "*") for action, _ in AUDITED.values()})
ENTITIES = sorted({entity for _, entity in AUDITED.values()})


class AuditRecordSerializer(serializers.ModelSerializer):
    """Una operación auditada: autor, fecha, acción, entidad afectada, resultado y los datos enviados."""

    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditRecord
        fields = [
            "id", "created_at", "user", "user_email", "user_name", "action", "entity", "entity_id",
            "result", "ip", "detail",
        ]
        read_only_fields = fields

    def get_user_name(self, row) -> str:
        return (row.user.get_full_name() or row.user.email) if row.user else row.user_email


@extend_schema(
    tags=["users"], summary="Consultar la auditoría de operaciones críticas (HU 1.5)",
    description="Solo lectura y paginado, del más reciente al más antiguo. Exige `seguridad.auditoria` "
    "(Administrador y Gerente). El registro no se edita ni se borra.",
    parameters=[
        OpenApiParameter("user", int, description="Id del autor"),
        OpenApiParameter("action", str, description="Acción, p. ej. `tarifa.modificar` o `factura.anular`"),
        OpenApiParameter("entity", str, description="Entidad afectada, p. ej. `factura`"),
        OpenApiParameter("entity_id", str, description="Id de la entidad afectada"),
        OpenApiParameter("result", str, description="exito, rechazado o error"),
        OpenApiParameter("date_from", str, description="Desde (AAAA-MM-DD), inclusive"),
        OpenApiParameter("date_to", str, description="Hasta (AAAA-MM-DD), inclusive"),
    ],
)
class AuditRecordListView(generics.ListAPIView):
    """Lista la auditoría con filtros por autor, acción, entidad, resultado y fechas."""

    required_permissions = {"GET": catalog.AUDIT_VIEW}
    serializer_class = AuditRecordSerializer
    pagination_class = AccessPagination

    def get_queryset(self):
        params = self.request.query_params
        rows = AuditRecord.objects.select_related("user")
        if params.get("user"):
            if not params["user"].isdigit():
                raise ValidationError({"user": "Debe ser el id del usuario."})
            rows = rows.filter(user_id=int(params["user"]))
        if params.get("action"):
            action = params["action"]
            # `lote.*` agrupa todas las acciones de lote (iniciar, terminar...).
            rows = rows.filter(action__startswith=action[:-1]) if action.endswith(".*") else rows.filter(action=action)
        if params.get("entity"):
            rows = rows.filter(entity=params["entity"])
        if params.get("entity_id"):
            rows = rows.filter(entity_id=params["entity_id"])
        if params.get("result"):
            if params["result"] not in dict(AuditRecord.RESULT_CHOICES):
                raise ValidationError({"result": "Usa exito, rechazado o error."})
            rows = rows.filter(result=params["result"])
        date_from, date_to = _date_param(params, "date_from"), _date_param(params, "date_to")
        if date_from:
            rows = rows.filter(created_at__date__gte=date_from)
        if date_to:
            rows = rows.filter(created_at__date__lte=date_to)
        return rows


@extend_schema(
    tags=["users"], summary="Acciones y entidades que se auditan",
    responses=inline_serializer("AuditoriaCatalogo", {
        "actions": serializers.ListField(child=serializers.CharField()),
        "entities": serializers.ListField(child=serializers.CharField()),
    }),
)
class AuditCatalogView(APIView):
    """Valores para los filtros de la pantalla de auditoría."""

    required_permissions = {"GET": catalog.AUDIT_VIEW}

    def get(self, request):
        return Response({"actions": ACTIONS, "entities": ENTITIES})
