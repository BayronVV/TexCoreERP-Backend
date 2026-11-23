"""Bloqueo temporal de la cuenta por intentos fallidos (RF01, HU 1.5).

El contador vive en la base de datos (no en la caché de cada proceso) y se actualiza con la fila
bloqueada (`select_for_update`), así todas las instancias del servidor ven el mismo número y dos
intentos simultáneos no se pisan. El bloqueo es temporal: uno permanente permitiría a cualquiera dejar
fuera a otra persona con solo conocer su correo.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from . import catalog
from .models import CustomUser

logger = logging.getLogger(__name__)

LOCKED_MESSAGE = "La cuenta está bloqueada temporalmente por intentos fallidos. Inténtalo más tarde o recupera tu contraseña."
LOCKED_CODE = "account_locked"


def locked_error():
    """401 de cuenta bloqueada; el `code` deja al frontend distinguirlo de una clave incorrecta."""
    return AuthenticationFailed({"detail": LOCKED_MESSAGE, "code": LOCKED_CODE})


def _working_admin_left(user):
    """¿Queda otro ADMIN activo, con contraseña y sin bloqueo, que pueda entrar?

    Bloquea las filas de todos los administradores en orden de id (igual que `other_working_admins`)
    para que dos bloqueos simultáneos no dejen el sistema sin ninguno.
    """
    now = timezone.now()
    admins = list(CustomUser.objects.select_for_update().filter(role_id=catalog.ADMIN, is_active=True).order_by("pk"))
    return any(
        admin.pk != user.pk
        and not admin.password.startswith("!")  # cuenta invitada que nunca definió su contraseña
        and not (admin.locked_until and admin.locked_until > now)
        for admin in admins
    )


def register_failure(user):
    """Suma un intento fallido. Devuelve True si con este intento la cuenta quedó bloqueada.

    No suma mientras la cuenta ya está bloqueada (no se alarga el bloqueo) y no bloquea al último
    administrador que pueda entrar: esa cuenta solo queda protegida por el límite por IP.
    """
    others_can_enter = True
    with transaction.atomic():
        if user.role_id == catalog.ADMIN:
            others_can_enter = _working_admin_left(user)  # también deja bloqueada la fila del propio usuario
        locked = CustomUser.objects.select_for_update().get(pk=user.pk)
        if locked.is_locked:
            return False
        locked.failed_login_count += 1
        newly_locked = False
        if locked.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
            if locked.role_id != catalog.ADMIN or others_can_enter:
                locked.locked_until = timezone.now() + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                locked.failed_login_count = 0
                newly_locked = True
            else:
                logger.warning("No se bloquea la cuenta %s: es el último administrador que puede entrar.", locked.pk)
        locked.save(update_fields=["failed_login_count", "locked_until"])
    if newly_locked:
        send_lock_email(locked)
    return newly_locked


def register_success(user):
    """Un acceso correcto pone el contador en cero."""
    if user.failed_login_count or user.locked_until:
        CustomUser.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=None)


def unlock(user):
    """Quita el bloqueo y reinicia el contador (desbloqueo del administrador o nueva contraseña)."""
    CustomUser.objects.filter(pk=user.pk).update(failed_login_count=0, locked_until=None)


def send_lock_email(user):
    """Avisa por correo al titular. Si el servidor de correo falla queda en el log y no afecta al login."""
    context = {"name": user.first_name or user.email, "minutes": settings.LOGIN_LOCK_MINUTES}
    try:
        send_mail(
            "Tu cuenta de TexCore ERP se bloqueó temporalmente",
            render_to_string("users/emails/cuenta_bloqueada.txt", context),
            None,
            [user.email],
            html_message=render_to_string("users/emails/cuenta_bloqueada.html", context),
        )
    except Exception:  # noqa: BLE001 - el aviso nunca debe romper el inicio de sesión
        logger.exception("No se pudo enviar el aviso de bloqueo a la cuenta %s", user.pk)
