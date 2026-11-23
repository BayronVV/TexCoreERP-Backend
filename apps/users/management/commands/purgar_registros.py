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

from apps.users.models import AccessLog

logger = logging.getLogger(__name__)
DEFAULT_MONTHS = 12


class Command(BaseCommand):
    help = "Borra los accesos al sistema con más de N meses (por defecto 12)."

    def add_arguments(self, parser):
        parser.add_argument("--meses", type=int, default=DEFAULT_MONTHS, help="Meses de conservación (12).")
        parser.add_argument("--simular", action="store_true", help="Solo muestra cuántos registros se borrarían.")

    def handle(self, *args, **options):
        months = options["meses"]
        if months < 1:
            raise CommandError("--meses debe ser al menos 1.")
        limit = timezone.now() - timedelta(days=30 * months)
        old = AccessLog.objects.filter(created_at__lt=limit)
        count = old.count()
        if options["simular"]:
            self.stdout.write(f"Se borrarían {count} accesos anteriores a {limit:%Y-%m-%d}.")
            return
        old.delete()
        # La purga es la única excepción a «no se borra»: queda constancia en el log del servidor.
        logger.info("Purga de registros de seguridad: %s accesos anteriores a %s", count, limit.isoformat())
        self.stdout.write(f"Se borraron {count} accesos anteriores a {limit:%Y-%m-%d}.")
