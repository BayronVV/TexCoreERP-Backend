"""Comprueba que el modelo de datos (MER y esquema físico) coincide con la base de datos real (TE-188).

    python manage.py verificar_mer

Solo lee. Compara claves primarias y foráneas, restricciones únicas y de chequeo, nulabilidad y las cardinalidades del MER con el
esquema de la base conectada (ver `apps/core/mer_check.py`). Termina con error si encuentra una diferencia, para poder correrlo en la
integración continua y en la sustentación (`DATABASE_URL` apuntando a la base que se quiere verificar).
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from ... import mer_check
from .generar_erd import project_models, schema_version


class Command(BaseCommand):
    """Comando de gestión: verificación del modelo de datos contra la base (solo lectura)."""
    help = "Compara el modelo de datos (MER y esquema físico) con la base conectada; falla si no coinciden."

    def handle(self, *args, **options):
        tables = [m for m in project_models() if m._meta.managed]
        self.stdout.write(f"Base: {connection.vendor}. Tablas del modelo: {len(tables)}. Esquema: {schema_version()}.")
        problems = mer_check.compare()
        for problem in problems:
            self.stdout.write(self.style.ERROR(f"  ✗ {problem}"))
        if problems:
            raise CommandError(f"El modelo de datos no coincide con la base: {len(problems)} diferencia(s).")
        self.stdout.write(self.style.SUCCESS("El modelo de datos coincide con la base: claves, restricciones, nulos y cardinalidades."))
