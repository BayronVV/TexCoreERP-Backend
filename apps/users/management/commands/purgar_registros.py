"""Retención de los registros de seguridad (HU 1.5): borra lo que supere los meses de conservación.

Pensado para programarse (cron de Render, una vez al día o a la semana):

    python manage.py purgar_registros            # conserva 12 meses
    python manage.py purgar_registros --meses 6
    python manage.py purgar_registros --simular  # solo cuenta, no borra
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.users import audit
from apps.users.models import AccessLog, AuditRecord

logger = logging.getLogger(__name__)
DEFAULT_MONTHS = 12


class Command(BaseCommand):
    help = "Borra los accesos y la auditoría con más de N meses (por defecto 12)."

    def add_arguments(self, parser):
        parser.add_argument("--meses", type=int, default=DEFAULT_MONTHS, help="Meses de conservación (12).")
        parser.add_argument("--simular", action="store_true", help="Solo muestra cuántos registros se borrarían.")

    def handle(self, *args, **options):
        months = options["meses"]
        if months < 1:
            raise CommandError("--meses debe ser al menos 1.")
        limit = timezone.now() - timedelta(days=30 * months)
        old_access = AccessLog.objects.filter(created_at__lt=limit)
        old_audit = AuditRecord.objects.filter(created_at__lt=limit)
        accesses, audits = old_access.count(), old_audit.count()
        if options["simular"]:
            self.stdout.write(
                f"Se borrarían {accesses} accesos y {audits} registros de auditoría anteriores a {limit:%Y-%m-%d}."
            )
            return
        old_access.delete()
        AuditRecord.objects.purge_before(limit)
        # La purga es la única excepción a «no se borra»: queda registrada en la propia auditoría.
        audit.record(
            None, "auditoria.purga", "auditoria", "", detail={
                "meses": months, "antes_de": limit.date().isoformat(), "accesos": accesses, "auditoria": audits,
            },
        )
        logger.info("Purga de registros de seguridad: %s accesos y %s auditorías anteriores a %s", accesses, audits, limit.isoformat())
        self.stdout.write(
            f"Se borraron {accesses} accesos y {audits} registros de auditoría anteriores a {limit:%Y-%m-%d}."
        )
