"""Tarifas de mano de obra de demostración (HU 4.6).

    python manage.py seed_demo_tarifas     # idempotente; solo con DJANGO_DEBUG=true

Sin tarifas, la liquidación de una orden marca el costo de mano de obra como incompleto. Registra una tarifa por minuto para cada etapa
(corte, confección y terminación) vigente desde el 1 de enero de 2026. Son valores de demostración: el Gerente los corrige en
Producción → Tarifas. Una etapa que ya tiene tarifa no se toca.
"""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ... import catalog
from ...models import TarifaManoObra

# etapa → costo por minuto en pesos colombianos (≈ salario mínimo con prestaciones dividido entre las horas trabajadas)
RATES = {
    catalog.STAGE_CUTTING: Decimal("210.0000"),
    catalog.STAGE_SEWING: Decimal("240.0000"),
    catalog.STAGE_FINISHING: Decimal("190.0000"),
}
SINCE = date(2026, 1, 1)


class Command(BaseCommand):
    """Comando de gestión: siembra las tarifas de mano de obra por etapa (solo con `DJANGO_DEBUG=true`)."""
    help = "Registra una tarifa de mano de obra por minuto para cada etapa (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        manager = users.filter(role_id="GERENTE").first() or users.filter(role_id="ADMIN").first() or users.first()
        created = 0
        for stage, cost in RATES.items():
            if TarifaManoObra.objects.filter(etapa=stage).exists():
                continue
            TarifaManoObra.objects.create(etapa=stage, costo_minuto=cost, vigente_desde=SINCE, creado_por=manager)
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Tarifas nuevas: {created}."))
