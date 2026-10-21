"""Operarios y máquinas de demostración (HU 4.4), asignados a las etapas en curso de las órdenes de demostración.

    python manage.py seed_demo_recursos     # conviene correr antes seed_demo_produccion (las órdenes y sus tiempos)

Pasa por las mismas reglas que usa la aplicación (`resources.create_operator`, `create_machine` y `assign`), así que los
códigos son consecutivos y las validaciones se cumplen. Es idempotente: un operario se reconoce por su documento y una
máquina por su serial (ambos ficticios), y una etapa que ya tiene asignación no se toca. Una máquina queda en
mantenimiento a propósito para mostrar que no se puede asignar. Solo con DJANGO_DEBUG=true.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from ... import catalog, resources, tracking
from ...models import AsignacionEtapa, Lote, Maquina, Operario

CUT, SEW, FINISH = catalog.STAGE_CUTTING, catalog.STAGE_SEWING, catalog.STAGE_FINISHING

# Documentos ficticios: solo sirven para reconocer al operario si el comando se corre otra vez.
OPERATORS = [
    {"nombres": "Carlos Ramírez", "documento": "1090100001", "etapas": [CUT], "tipo_pago": catalog.PAY_TIME},
    {"nombres": "Diana Torres", "documento": "1090100002", "etapas": [CUT], "tipo_pago": catalog.PAY_SALARY},
    {"nombres": "Luis Fernández", "documento": "1090100003", "etapas": [SEW], "tipo_pago": catalog.PAY_PIECE},
    {"nombres": "Sofía Mendoza", "documento": "1090100004", "etapas": [SEW], "tipo_pago": catalog.PAY_PIECE},
    {"nombres": "Andrés Castro", "documento": "1090100005", "etapas": [SEW, FINISH], "tipo_pago": catalog.PAY_TIME},
    {"nombres": "Paola Jiménez", "documento": "1090100006", "etapas": [FINISH], "tipo_pago": catalog.PAY_SALARY},
]

# `serial` ficticio, para reconocer la máquina si el comando se corre otra vez.
MACHINES = [
    {"serial": "DEMO-MAQ-01", "tipo": "CORTADORA", "etapas": [CUT], "ubicacion": "Zona de corte", "marca_modelo": "Cortadora de cuchilla (demo)"},
    {"serial": "DEMO-MAQ-02", "tipo": "PLANA", "etapas": [SEW], "ubicacion": "Línea 1", "marca_modelo": "Plana industrial (demo)"},
    {"serial": "DEMO-MAQ-03", "tipo": "PLANA", "etapas": [SEW], "ubicacion": "Línea 1", "marca_modelo": "Plana industrial (demo)"},
    {"serial": "DEMO-MAQ-04", "tipo": "FILETEADORA", "etapas": [SEW], "ubicacion": "Línea 2", "marca_modelo": "Fileteadora de 5 hilos (demo)"},
    {"serial": "DEMO-MAQ-05", "tipo": "COLLARIN", "etapas": [SEW], "ubicacion": "Línea 2", "marca_modelo": "Collarín (demo)"},
    {"serial": "DEMO-MAQ-06", "tipo": "PRESILLADORA", "etapas": [SEW, FINISH], "ubicacion": "Línea 3", "marca_modelo": "Presilladora (demo)"},
    {"serial": "DEMO-MAQ-07", "tipo": "OJALADORA", "etapas": [FINISH], "ubicacion": "Zona de terminación", "marca_modelo": "Ojaladora (demo)"},
    {
        "serial": "DEMO-MAQ-08", "tipo": "REMACHADORA", "etapas": [FINISH], "ubicacion": "Zona de terminación",
        "marca_modelo": "Remachadora (demo)", "estado": catalog.MACHINE_MAINTENANCE, "observaciones": "En mantenimiento: cambio de pistón",
    },
    {"serial": "DEMO-MAQ-09", "tipo": "CORTADORA", "etapas": [CUT], "ubicacion": "Zona de corte", "marca_modelo": "Cortadora circular (demo)"},
]


class Command(BaseCommand):
    """Comando de gestión: siembra operarios y máquinas de demostración y los asigna a etapas en curso (solo con `DJANGO_DEBUG=true`)."""
    help = "Crea operarios y máquinas de demostración y los asigna a las etapas en curso (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        user = users.filter(role_id="PRODUCCION").first() or users.first()
        if user is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        operators = sum(self._operator(spec) for spec in OPERATORS)
        machines = sum(self._machine(spec) for spec in MACHINES)
        assigned = self._assign(user)
        self.stdout.write(self.style.SUCCESS(
            f"Operarios nuevos: {operators} · máquinas nuevas: {machines} · etapas con asignación nueva: {assigned}."
        ))

    def _operator(self, spec):
        if Operario.objects.filter(documento=spec["documento"]).exists():
            return 0
        resources.create_operator(data=spec)
        return 1

    def _machine(self, spec):
        if Maquina.objects.filter(serial=spec["serial"]).exists():
            return 0
        resources.create_machine(data=spec)
        return 1

    def _assign(self, user):
        """Da operario y máquina a la etapa en curso (o siguiente) de cada lote de las órdenes de demostración que todavía
        no tiene asignación. Prefiere los recursos que no están en otra etapa en curso y, si todos lo están, los reparte por turnos.
        """
        demo_operators = list(Operario.objects.filter(documento__in=[spec["documento"] for spec in OPERATORS], activo=True))
        demo_machines = list(
            Maquina.objects.filter(serial__in=[spec["serial"] for spec in MACHINES], activo=True, estado=catalog.MACHINE_AVAILABLE)
        )
        lots = Lote.objects.filter(
            orden__orden_salida__observaciones__startswith="Orden de demostración"
        ).exclude(orden__orden_salida__estado="ANULADA").select_related("orden").order_by("id")
        assigned = 0
        for turn, lot in enumerate(lots):
            stage = tracking.current_stage(list(lot.etapas.all()))
            if stage is None or AsignacionEtapa.objects.filter(etapa_lote=stage, fin_at__isnull=True).exists():
                continue
            operators = [op for op in demo_operators if stage.etapa in op.etapas]
            machines = [machine for machine in demo_machines if stage.etapa in machine.etapas]
            if not operators:
                continue
            busy_operators, busy_machines = resources.busy_by_operator(), resources.busy_by_machine()
            free_operators = [op for op in operators if op.id not in busy_operators] or operators
            free_machines = [machine for machine in machines if machine.id not in busy_machines] or machines
            changes = {"operario": free_operators[turn % len(free_operators)].id}
            if free_machines:
                changes["maquina"] = free_machines[turn % len(free_machines)].id
            try:
                resources.assign(user=user, lot_id=lot.id, stage_code=stage.etapa, changes=changes)
            except ValidationError as error:
                self.stdout.write(f"No se asignó {lot.codigo}: {error.detail}")
                continue
            assigned += 1
        return assigned
