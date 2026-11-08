"""Configuración de la app `core` (transversal)."""
from django.apps import AppConfig, apps
from django.db.models.signals import post_migrate


def _harden_database(sender, using, **kwargs):
    from django.db import connections

    from .db_security import harden_public_schema

    harden_public_schema(connections[using])


def _seed_demo_on_deploy(sender, using, **kwargs):
    """Siembra la demostración al final del `migrate` si SEED_DEMO_ON_DEPLOY=true. Nunca debe impedir el arranque."""
    import sys

    from django.conf import settings

    if not settings.SEED_DEMO_ON_DEPLOY or using != "default":
        return
    from django.core.management import call_command

    try:
        call_command("seed_demo_completo", permitir_produccion=True)
    except Exception as error:  # noqa: BLE001 - un fallo de la demo no debe tumbar el despliegue
        print(f"AVISO: la siembra de demostración no terminó: {error}", file=sys.stderr)


class CoreConfig(AppConfig):
    """Utilidades transversales: salud del sistema, modelos base y permisos."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        # sender=self: se ejecuta una sola vez, al final de cada `migrate`.
        post_migrate.connect(_harden_database, sender=self, dispatch_uid="core.harden_database")
        # La demo necesita todas las tablas: se dispara tras la última app del proyecto (envíos).
        post_migrate.connect(_seed_demo_on_deploy, sender=apps.get_app_config("shipping"), dispatch_uid="core.seed_demo_on_deploy")
