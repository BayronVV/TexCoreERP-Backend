"""
Crea (o actualiza) la cuenta de Administrador que se necesita para entrar
al ERP por primera vez y aprobar el resto de registros.

Uso:
    python manage.py seed_admin
    python manage.py seed_admin --email admin@texcore.test --password "Otra#Clave1"
    python manage.py seed_admin --reset-password    # fuerza la contraseña de nuevo

Es idempotente: si la cuenta ya existe, solo confirma que tenga
role=ADMIN, is_staff e is_superuser en True. Nunca crea una segunda
cuenta ni pisa la contraseña salvo que se pida explícitamente.

Credenciales por defecto (para local/texcore-dev). Se pueden fijar con
las variables de entorno ADMIN_EMAIL / ADMIN_PASSWORD, o con --email /
--password. En texcore-prod usa --password (o la variable de entorno)
con una contraseña real: nunca dejes la de ejemplo.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import IntegrityError

DEFAULT_EMAIL = "admin@texcore.test"
DEFAULT_PASSWORD = "Admin#2026"  # Solo para desarrollo local.


class Command(BaseCommand):
    help = "Crea o actualiza la cuenta de Administrador inicial de TexCore."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default=None,
            help="Correo del administrador (por defecto: $ADMIN_EMAIL o admin@texcore.test).",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Contraseña del administrador (por defecto: $ADMIN_PASSWORD o una de desarrollo).",
        )
        parser.add_argument(
            "--first-name", default="Admin", help="Nombre (solo al crear la cuenta)."
        )
        parser.add_argument(
            "--last-name", default="TexCore", help="Apellido (solo al crear la cuenta)."
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Si la cuenta ya existe, sobrescribe su contraseña también.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        email = options["email"] or self._env("ADMIN_EMAIL") or DEFAULT_EMAIL
        password = options["password"] or self._env("ADMIN_PASSWORD") or DEFAULT_PASSWORD

        if password == DEFAULT_PASSWORD and not settings.DEBUG:
            raise CommandError(
                "No uses la contraseña de ejemplo fuera de desarrollo. "
                "Pasa --password o define ADMIN_PASSWORD."
            )

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": options["first_name"],
                "last_name": options["last_name"],
                "role": "ADMIN",
                "is_staff": True,
                "is_superuser": True,
            },
        )

        if created:
            user.set_password(password)
            try:
                user.save()
            except IntegrityError as exc:
                raise CommandError(f"No se pudo crear el administrador: {exc}") from exc
            self.stdout.write(self.style.SUCCESS(f"Administrador creado: {email}"))
        else:
            changed = []
            if user.role != "ADMIN":
                user.role = "ADMIN"
                changed.append("role")
            if not user.is_staff:
                user.is_staff = True
                changed.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True
                changed.append("is_superuser")
            if options["reset_password"]:
                user.set_password(password)
                changed.append("password")
            if changed:
                user.save(update_fields=changed + ["updated_at"])
                self.stdout.write(
                    self.style.WARNING(f"Administrador ya existía, actualizado: {', '.join(changed)}")
                )
            else:
                self.stdout.write(self.style.SUCCESS(f"Administrador ya existía y estaba correcto: {email}"))

        if created or options["reset_password"]:
            self.stdout.write(f"  Correo:      {email}")
            self.stdout.write(f"  Contraseña:  {password}")
            self.stdout.write(self.style.WARNING("  Cámbiala si esta cuenta va a producción."))

    @staticmethod
    def _env(name):
        import os

        value = os.getenv(name, "").strip()
        return value or None
