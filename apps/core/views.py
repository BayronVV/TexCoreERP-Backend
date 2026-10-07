"""Endpoints de salud usados para verificar que el sistema está vivo."""

import time

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(
    tags=["salud"], summary="Estado del servicio",
    responses=inline_serializer("Salud", {
        "status": serializers.CharField(), "service": serializers.CharField(),
        "version": serializers.CharField(), "environment": serializers.CharField(),
        "timestamp": serializers.DateTimeField(),
    }),
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """GET /api/health/ — responde sin tocar la base de datos."""
    return Response(
        {
            "status": "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
            "timestamp": timezone.now().isoformat(),
        }
    )


@extend_schema(
    tags=["salud"], summary="Estado de la conexión a la base de datos",
    description="Ejecuta `SELECT 1`. Responde 503 si la base no está disponible.",
    responses=inline_serializer("SaludBD", {
        "status": serializers.CharField(), "vendor": serializers.CharField(),
        "server_version": serializers.CharField(allow_null=True),
        "latency_ms": serializers.FloatField(),
    }),
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_db(request):
    """GET /api/health/db/ — ejecuta SELECT 1 y lista las tablas del esquema public."""
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            # La lista de tablas solo se expone en desarrollo.
            tables = sorted(connection.introspection.table_names(cursor)) if settings.DEBUG else None
            server_version = _server_version(cursor)
    except DatabaseError as exc:
        return Response(
            {"status": "error", "vendor": connection.vendor, "detail": str(exc).strip()},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response(
        {
            "status": "ok",
            "vendor": connection.vendor,
            "server_version": server_version,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "tables": tables,
        }
    )


def _server_version(cursor):
    if connection.vendor == "postgresql":
        cursor.execute("SHOW server_version")
        return cursor.fetchone()[0]
    if connection.vendor == "sqlite":
        cursor.execute("SELECT sqlite_version()")
        return cursor.fetchone()[0]
    return None
