"""Utilidades compartidas de prueba para todos los módulos de TexCoreERP."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

DEFAULT_PASSWORD = "Passw0rd!23"
PASSWORD = DEFAULT_PASSWORD
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def make_user(email, role="PENDING", password=DEFAULT_PASSWORD, **extra):
    """Crea un usuario de prueba con el rol indicado."""
    User = get_user_model()
    return User.objects.create_user(username=email, email=email, password=password, role_id=role, **extra)


def client_for(user):
    """Devuelve un cliente DRF autenticado como `user`."""
    client = APIClient()
    client.force_authenticate(user)
    return client


def today():
    """Fecha local actual en formato ISO (AAAA-MM-DD)."""
    return timezone.localdate().isoformat()


def tiny_png(name="proto.png", content=PNG):
    """Archivo PNG mínimo válido para pruebas de subida de imágenes."""
    return SimpleUploadedFile(name, content, content_type="image/png")


def tiny_pdf(name="documento.pdf", content=PDF):
    """Archivo PDF mínimo válido para pruebas de subida de documentos."""
    return SimpleUploadedFile(name, content, content_type="application/pdf")
