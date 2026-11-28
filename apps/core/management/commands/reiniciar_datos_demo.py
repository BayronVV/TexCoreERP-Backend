"""Vacía los datos de negocio y vuelve a sembrar la demostración completa, coherente de punta a punta (TE-183).

    python manage.py reiniciar_datos_demo --confirmar                            # desarrollo (DJANGO_DEBUG=true)
    python manage.py reiniciar_datos_demo --confirmar --permitir-produccion      # base de producción (datos SIMULADOS)

**Conserva** usuarios, roles, permisos, accesos, tokens y la auditoría (app `users`) y las tablas propias de Django. **Vacía** todas
las tablas de los módulos de negocio, tomadas de los modelos (no de una lista escrita a mano), y reinicia sus consecutivos para que la
siembra dé siempre el mismo resultado.

Todo pasa en una sola transacción: vaciar → `seed_demo_completo` → `verificar_coherencia_demo`. Si la siembra o la comprobación
fallan, se deshace todo y la base queda como estaba. Al terminar refresca las vistas de reportes y deja una fila en la auditoría.

Guardas: exige `--confirmar`; con DJANGO_DEBUG=false exige además `--permitir-produccion`; en modo interactivo pide escribir el nombre
de la base. Nunca se llama desde el arranque de Render (`SEED_DEMO_ON_DEPLOY` solo siembra, no borra). En PostgreSQL limita la espera
de bloqueos para no quedarse colgado si la aplicación está en uso: conviene correrlo con la aplicación sin tráfico y por el puerto de
sesión (5432) de Supabase.
"""
from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction

from .verificar_coherencia_demo import report

# Módulos de negocio que se reinician. `users` (cuentas, roles, permisos, accesos y auditoría) nunca está aquí.
BUSINESS_APPS = ("inventory", "references", "production", "purchasing", "quality", "finished", "sales", "shipping", "reports")
# Variable de sesión que autoriza borrar los libros protegidos por los triggers de inmutabilidad (TE-188). Vale solo en esta transacción.
RESET_FLAG = "texcore.permitir_reinicio"


def business_tables():
    """Tablas de los modelos de negocio gestionados por Django (incluidas las intermedias de muchos a muchos), sin vistas ni proxies."""
    tables = []
    for label in BUSINESS_APPS:
        for model in apps.get_app_config(label).get_models(include_auto_created=True):
            meta = model._meta
            if meta.managed and not meta.proxy and meta.db_table not in tables:
                tables.append(meta.db_table)
    return tables


def flush_business_tables(tables):
    """Vacía las tablas en una sola sentencia y reinicia sus consecutivos (TRUNCATE … RESTART IDENTITY en PostgreSQL; DELETE en SQLite).

    Sin CASCADE: si una tabla que no es de negocio apuntara a estas, la base lo rechaza en vez de vaciarla sin avisar.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '15s'")
            cursor.execute("SET LOCAL statement_timeout = '10min'")
            cursor.execute(f"SET LOCAL {RESET_FLAG} = 'on'")
    statements = connection.ops.sql_flush(no_style(), tables, reset_sequences=True, allow_cascade=False)
    connection.ops.execute_sql_flush(statements)


def counts(tables):
    with connection.cursor() as cursor:
        result = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
            result[table] = cursor.fetchone()[0]
        return result


class Command(BaseCommand):
    """Comando de gestión: reinicia los datos de negocio de la demostración sin tocar usuarios, roles ni permisos."""
    help = "Vacía los datos de negocio y vuelve a sembrar la demostración completa en una sola transacción (conserva usuarios y permisos)."

    def add_arguments(self, parser):
        parser.add_argument("--confirmar", action="store_true", help="Confirma que se borrarán todos los datos de negocio.")
        parser.add_argument("--permitir-produccion", action="store_true", help="Permite correr con DJANGO_DEBUG=false (datos simulados).")
        parser.add_argument("--no-input", "--noinput", action="store_false", dest="interactive", help="No pide escribir el nombre de la base.")

    def handle(self, *args, **options):
        if not options["confirmar"]:
            raise CommandError("Este comando borra todos los datos de negocio: pasa --confirmar para hacerlo.")
        if not settings.DEBUG and not options["permitir_produccion"]:
            raise CommandError("Con DJANGO_DEBUG=false hay que pasar --permitir-produccion: los datos de negocio son SIMULADOS.")
        tables = business_tables()
        before = counts(tables)
        database = str(connection.settings_dict.get("NAME") or "")
        self.stdout.write(f"Base: {database} ({connection.vendor}). Se vaciarán {len(tables)} tablas con {sum(before.values())} filas:")
        for table, rows in before.items():
            if rows:
                self.stdout.write(f"  {table}: {rows}")
        if options["interactive"]:
            answer = input(f"Escribe el nombre de la base ({database}) para continuar: ")
            if answer.strip() != database:
                raise CommandError("El nombre no coincide: no se borró nada.")

        with transaction.atomic():
            flush_business_tables(tables)
            self.stdout.write("Datos de negocio vaciados. Sembrando la demostración completa…")
            call_command("seed_demo_completo", permitir_produccion=True, stdout=self.stdout)
            self.stdout.write("Comprobando la coherencia:")
            failed = report(self.stdout, self.style)
            if failed:
                raise CommandError(f"La comprobación encontró {failed} problema(s): se deshizo el reinicio y la base quedó como estaba.")

        from apps.reports.services import refresh_materialized_views
        from apps.users import audit

        refresh_materialized_views()
        audit.record(None, "demo.reiniciar", entity="datos_demo", detail={"tablas": len(tables), "filas_borradas": sum(before.values())})
        self.stdout.write(self.style.SUCCESS("Datos de demostración reiniciados y coherentes."))

