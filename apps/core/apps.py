from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _harden_database(sender, using, **kwargs):
    from django.db import connections

    from .db_security import harden_public_schema

    harden_public_schema(connections[using])


class CoreConfig(AppConfig):
    """Utilidades transversales: salud del sistema, modelos base y permisos."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        # sender=self: se ejecuta una sola vez, al final de cada `migrate`.
        post_migrate.connect(_harden_database, sender=self, dispatch_uid="core.harden_database")
