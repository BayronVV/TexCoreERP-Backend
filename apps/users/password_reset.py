"""
Tokens de recuperación / activación de contraseña (HU 1.3).

El token en claro solo viaja en el enlace del correo; en la base se guarda
su SHA-256. Cada token sirve una vez y caduca (15 min para recuperación,
48 h para la invitación de una cuenta creada por un administrador).
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .models import PasswordResetToken

logger = logging.getLogger(__name__)

# Máximo de correos de recuperación por usuario en una hora, aunque cambie de IP.
MAX_RESET_REQUESTS_PER_HOUR = 3


def _hash(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _ttl(purpose):
    if purpose == PasswordResetToken.PURPOSE_INVITE:
        return timedelta(hours=settings.ACCOUNT_INVITE_TOKEN_HOURS)
    return timedelta(minutes=settings.PASSWORD_RESET_TOKEN_MINUTES)


def can_request_reset(user):
    """False si el usuario ya pidió el máximo de enlaces de recuperación en la última hora."""
    since = timezone.now() - timedelta(hours=1)
    recent = user.reset_tokens.filter(purpose=PasswordResetToken.PURPOSE_RESET, created_at__gte=since).count()
    return recent < MAX_RESET_REQUESTS_PER_HOUR


def issue_token(user, purpose=PasswordResetToken.PURPOSE_RESET, ip=None):
    """Crea un token nuevo, invalida los anteriores del usuario y devuelve el token en claro."""
    now = timezone.now()
    user.reset_tokens.filter(used_at__isnull=True, expires_at__gt=now).update(expires_at=now)

    raw = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        token_hash=_hash(raw),
        purpose=purpose,
        expires_at=now + _ttl(purpose),
        requested_ip=ip,
    )
    return raw


def find_usable_token(raw_token, lock=False):
    """Devuelve el token si todavía sirve. Con lock=True bloquea la fila para que
    dos peticiones simultáneas no puedan usar el mismo enlace (llamar dentro de
    transaction.atomic)."""
    if not raw_token:
        return None
    qs = PasswordResetToken.objects.select_related("user")
    if lock:
        qs = qs.select_for_update(of=("self",))
    token = qs.filter(token_hash=_hash(raw_token)).first()
    if token is None or not token.is_usable:
        return None
    user = token.user
    if user.deleted_at is not None or not user.is_active:
        return None
    return token


def consume_token(token, new_password):
    """Cambia la contraseña con el token, lo marca como usado e invalida los demás enlaces vigentes del usuario."""
    user = token.user
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    now = timezone.now()
    token.used_at = now
    token.save(update_fields=["used_at"])
    user.reset_tokens.filter(used_at__isnull=True, expires_at__gt=now).update(expires_at=now)
    return user


def send_token_email(user, raw_token, purpose):
    """Envía el enlace. Devuelve False si el servidor de correo falló (queda en el log)."""
    link = f"{settings.FRONTEND_URL.rstrip('/')}/restablecer-contrasena?token={raw_token}"
    invite = purpose == PasswordResetToken.PURPOSE_INVITE
    context = {
        "name": user.first_name or user.email,
        "link": link,
        "invite": invite,
        "expires": (
            f"{settings.ACCOUNT_INVITE_TOKEN_HOURS} horas"
            if invite
            else f"{settings.PASSWORD_RESET_TOKEN_MINUTES} minutos"
        ),
    }
    subject = "Activa tu cuenta de TexCore ERP" if invite else "Recupera tu contraseña de TexCore ERP"
    try:
        send_mail(
            subject,
            render_to_string("users/emails/password_token.txt", context),
            None,
            [user.email],
            html_message=render_to_string("users/emails/password_token.html", context),
        )
    except Exception:
        logger.exception("No se pudo enviar el correo de %s a %s", purpose, user.email)
        return False
    return True
