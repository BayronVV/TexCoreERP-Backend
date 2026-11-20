"""Manejador global de excepciones de la API REST y registro de errores no controlados (TE-181)."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DataError, IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("apps.core.exceptions")
request_logger = logging.getLogger("django.request")


def _data_error_message(exc):
    text = str(exc).lower()
    if any(token in text for token in ("value too long", "too long", "string data", "exceeds")):
        return "Uno de los campos excede la longitud máxima permitida."
    if any(token in text for token in ("date", "time", "timestamp")):
        return "El formato de fecha u hora enviado no es válido."
    if any(token in text for token in ("numeric", "overflow", "out of range")):
        return "Uno de los valores numéricos excede el rango permitido."
    return "Uno de los datos enviados excede el tamaño o formato permitido."


def _integrity_error_response(exc):
    text = str(exc).lower()
    if any(token in text for token in ("check constraint", "ck_")):
        return Response(
            {"detail": ["Los datos enviados no cumplen las restricciones de validación."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if any(token in text for token in ("not-null", "not null")):
        return Response(
            {"detail": ["Falta un campo obligatorio para completar la operación."]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if any(token in text for token in ("unique", "duplicate", "uq_")):
        return Response(
            {"detail": ["Ya existe un registro activo con esos mismos datos."]},
            status=status.HTTP_409_CONFLICT,
        )
    if any(token in text for token in ("foreign key", "referential")):
        return Response(
            {"detail": ["No se puede completar la operación porque el registro está en uso o hace referencia a un elemento inexistente."]},
            status=status.HTTP_409_CONFLICT,
        )
    return Response(
        {"detail": ["Conflicto de integridad al guardar los datos."]},
        status=status.HTTP_409_CONFLICT,
    )


def api_exception_handler(exc, context):
    """Traduce errores de validación y base de datos en respuestas 400/409 claras y registra todo error 500."""
    response = drf_exception_handler(exc, context)
    request = context.get("request")
    method = getattr(request, "method", "-")
    path = getattr(request, "path", "-")

    if response is not None:
        if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("Error de servidor controlado en %s %s", method, path, exc_info=exc)
        return response

    if isinstance(exc, DjangoValidationError):
        logger.warning("Validación de modelo rechazada en %s %s: %s", method, path, exc)
        if hasattr(exc, "message_dict"):
            payload = {key: [str(msg) for msg in msgs] for key, msgs in exc.message_dict.items()}
        else:
            payload = {"detail": [str(msg) for msg in exc.messages]}
        return Response(payload, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, DataError):
        logger.warning("Error de longitud o formato en BD en %s %s", method, path, exc_info=exc)
        return Response({"detail": [_data_error_message(exc)]}, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, IntegrityError):
        logger.warning("Error de integridad en BD en %s %s", method, path, exc_info=exc)
        return _integrity_error_response(exc)

    request_logger.error("Error interno no controlado en %s %s", method, path, exc_info=exc)
    return Response(
        {"detail": "Ocurrió un error interno en el servidor."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

