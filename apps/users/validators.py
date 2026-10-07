import re

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

# Misma política que muestra el frontend como checklist (passwordRules.js).
PASSWORD_RULES = [
    (lambda p: len(p) >= 8, "al menos 8 caracteres"),
    (lambda p: re.search(r"[A-Z]", p), "una letra mayúscula"),
    (lambda p: re.search(r"[a-z]", p), "una letra minúscula"),
    (lambda p: re.search(r"[0-9]", p), "un número"),
    # La ñ y las tildes son letras, no símbolos.
    (lambda p: re.search(r"[^\w\s]|_", p), "un símbolo"),
]


def validate_password_policy(password, user=None):
    """Aplica la política de contraseñas (8+ caracteres, mayúscula, minúscula, número y símbolo)
    y las reglas de Django. Lanza ValidationError con el detalle de lo que falta.
    """
    missing = [text for check, text in PASSWORD_RULES if not check(password or "")]
    if missing:
        raise ValidationError({"password": "La contraseña debe tener " + ", ".join(missing) + "."})
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as error:
        raise ValidationError({"password": list(error.messages)}) from error


def validate_passwords_match(password, confirmation):
    """Falla si la contraseña y su confirmación no coinciden."""
    if password != confirmation:
        raise ValidationError({"password_confirm": "Las contraseñas no coinciden."})
