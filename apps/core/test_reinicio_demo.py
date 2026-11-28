"""Reinicio y coherencia de los datos de demostración (TE-183).

Usa `TransactionTestCase` porque el reinicio vacía tablas con TRUNCATE en PostgreSQL, que no convive con la transacción envolvente
de un `TestCase`. También corre en el job de PostgreSQL de la integración continua.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings

from apps.core import demo_integrity
from apps.core.management.commands import reiniciar_datos_demo as reset
from apps.core.management.commands import seed_demo_completo as seed
from apps.core.testing import make_user
from apps.finished.models import MovimientoTerminado, StockTerminado
from apps.inventory.models import Producto
from apps.users.models import AccessLog, AuditRecord, ModulePermission, Role, RolePermission

ROLES = ("ADMIN", "GERENTE", "ALMACENISTA", "PRODUCCION", "SECRETARIA", "VENDEDOR", "TERMINACION")


def run(command, *args):
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def security_counts():
    return {
        "usuarios": get_user_model().objects.count(),
        "roles": Role.objects.count(),
        "permisos": ModulePermission.objects.count(),
        "permisos_por_rol": RolePermission.objects.count(),
        "accesos": AccessLog.objects.count(),
    }


def business_counts():
    return {path: seed._model(path).objects.count() for _, path in seed.REPORT if not path.endswith("CustomUser")}


@override_settings(DEBUG=False)
class ReinicioDemoTests(TransactionTestCase):
    serialized_rollback = True  # TransactionTestCase vacía la base al terminar: así vuelven los roles y permisos que crean las migraciones

    def setUp(self):
        for number, role in enumerate(ROLES):
            make_user(f"demo{number}@t.co", role)

    def reset(self, *extra):
        return run("reiniciar_datos_demo", "--confirmar", "--permitir-produccion", "--no-input", *extra)

    def test_reinicia_sin_tocar_usuarios_ni_permisos_y_queda_coherente(self):
        run("seed_demo_completo", "--permitir-produccion")
        security, audit = security_counts(), AuditRecord.objects.count()
        output = self.reset()
        self.assertIn("Datos de demostración reiniciados y coherentes.", output)
        self.assertEqual(security_counts(), security)
        self.assertEqual(AuditRecord.objects.count(), audit + 1)  # la auditoría se conserva y registra el reinicio
        self.assertTrue(AuditRecord.objects.filter(action="demo.reiniciar").exists())
        self.assertEqual([(name, problems) for name, problems in demo_integrity.run_checks() if problems], [])

    def test_reiniciar_dos_veces_deja_lo_mismo(self):
        self.reset()
        first = business_counts()
        first_ids = sorted(Producto.objects.values_list("id", flat=True))
        self.reset()
        self.assertEqual(business_counts(), first)
        self.assertEqual(sorted(Producto.objects.values_list("id", flat=True)), first_ids)  # los consecutivos se reinician

    def test_sembrar_dos_veces_no_duplica(self):
        run("seed_demo_completo", "--permitir-produccion")
        first = business_counts()
        run("seed_demo_completo", "--permitir-produccion")
        self.assertEqual(business_counts(), first)
        self.assertEqual([name for name, problems in demo_integrity.run_checks() if problems], [])

    def test_la_comprobacion_detecta_un_descuadre(self):
        self.reset()
        stock = StockTerminado.objects.filter(cantidad__gt=0).first()
        StockTerminado.objects.filter(pk=stock.pk).update(cantidad=stock.cantidad + 1)
        with self.assertRaises(CommandError):
            run("verificar_coherencia_demo")

    def test_la_comprobacion_detecta_un_movimiento_sin_documento(self):
        self.reset()
        problems = dict(demo_integrity.run_checks())
        self.assertEqual(problems["Registros huérfanos"], [])
        movement = MovimientoTerminado.objects.filter(ajuste__isnull=False).first()
        with transaction.atomic(), connection.cursor() as cursor:  # se daña a propósito, saltando la protección del libro (TE-188)
            if connection.vendor == "postgresql":
                cursor.execute("SET LOCAL texcore.permitir_reinicio = 'on'")
            cursor.execute("UPDATE terminado_movimiento SET ajuste_id = NULL WHERE id = %s", [movement.pk])
        self.assertTrue(dict(demo_integrity.run_checks())["Registros huérfanos"])

    def test_si_la_comprobacion_falla_se_deshace_todo(self):
        run("seed_demo_completo", "--permitir-produccion")
        before = business_counts()
        from unittest import mock

        with mock.patch.object(demo_integrity, "CHECKS", [("Prueba", lambda: ["descuadre forzado"])]):
            with self.assertRaises(CommandError):
                self.reset()
        self.assertEqual(business_counts(), before)
        self.assertFalse(AuditRecord.objects.filter(action="demo.reiniciar").exists())

    def test_sin_confirmar_no_borra_nada(self):
        run("seed_demo_completo", "--permitir-produccion")
        before = business_counts()
        with self.assertRaises(CommandError):
            run("reiniciar_datos_demo", "--permitir-produccion", "--no-input")
        self.assertEqual(business_counts(), before)

    def test_en_produccion_exige_el_permiso_explicito(self):
        with self.assertRaises(CommandError):
            run("reiniciar_datos_demo", "--confirmar", "--no-input")

    def test_el_nombre_de_la_base_debe_coincidir(self):
        from unittest import mock

        with mock.patch("builtins.input", return_value="otra-base"), self.assertRaises(CommandError):
            run("reiniciar_datos_demo", "--confirmar", "--permitir-produccion")

    def test_la_lavanderia_se_niega_fuera_de_desarrollo(self):
        with self.assertRaises(CommandError):
            run("seed_demo_lavanderia")

    def test_solo_vacia_tablas_de_negocio(self):
        tables = reset.business_tables()
        self.assertIn("inventario_movimiento", tables)
        self.assertFalse([table for table in tables if table.startswith(("seguridad_", "users_", "auth_", "django_"))])
        self.assertNotIn("seguridad_auditoria", tables)
