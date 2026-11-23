"""Endpoints de salud usados para verificar que el sistema está vivo."""

import logging
import time

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)


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
    description="Ejecuta `SELECT 1`. Responde `ok` con la latencia, o 503 con `no disponible`. "
                "No expone la versión del servidor, el motor ni el texto del error (el error queda en el registro del servidor).",
    responses=inline_serializer("SaludBD", {
        "status": serializers.CharField(), "latency_ms": serializers.FloatField(),
    }),
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_db(request):
    """GET /api/health/db/ — ejecuta SELECT 1. Público: solo dice si la base responde y en cuánto tiempo.

    El motor, su versión y el texto del error no se devuelven (ayudarían a un atacante); el error se
    registra en el servidor con su traza para poder diagnosticarlo.
    """
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.exception("La comprobación de la base de datos (/api/health/db/) falló")
        return Response({"status": "no disponible"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 1)})
