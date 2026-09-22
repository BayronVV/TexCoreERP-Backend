"""Endpoints de salud usados para verificar que el sistema está vivo."""
import time

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
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


@api_view(["GET"])
def health_db(request):
    """GET /api/health/db/ — ejecuta SELECT 1 y lista las tablas del esquema public."""
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
            tables = sorted(connection.introspection.table_names(cursor))
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
