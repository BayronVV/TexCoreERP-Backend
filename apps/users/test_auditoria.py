"""HU 1.5 (TE-175): auditoría de operaciones críticas y pruebas de acceso indebido por la API."""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import audit
from .audit import AUDITED, sanitize
from .models import AuditRecord, ModulePermission

User = get_user_model()
PASSWORD = "Passw0rd!23"


def make_user(email, role="PENDING"):
    return User.objects.create_user(username=email, email=email, password=PASSWORD, role_id=role)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def url_for(name):
    """URL de una ruta auditada con ids de relleno (la vista decide qué responde)."""
    for kwargs in ({}, {"pk": 1}, {"pk": 1, "accion": "iniciar"}, {"referencia": 1}):
        try:
            return reverse(name, kwargs=kwargs)
        except NoReverseMatch:
            continue
    raise AssertionError(f"No se pudo armar la URL de {name}")


class AuditedOperationsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        self.produccion = make_user("prod@t.co", "PRODUCCION")
        self.manager = make_user("ger@t.co", "GERENTE")

    def test_cambio_de_tarifa_queda_con_autor_fecha_tarifa_y_resultado(self):
        response = client_for(self.produccion).post(
            reverse("produccion_tarifas"),
            {"etapa": "CORTE", "costo_minuto": "275.5000", "vigente_desde": "2026-09-01"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        # el Gerente consulta la auditoría
        rows = client_for(self.manager).get(reverse("audit_list"), {"action": "tarifa.modificar"}).data["results"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["user_email"], "prod@t.co")
        self.assertEqual(row["entity"], "tarifa")
        self.assertEqual(row["entity_id"], str(response.data["id"]))
        self.assertEqual(row["result"], "exito")
        self.assertEqual(row["detail"]["datos"]["costo_minuto"], "275.5000")
        self.assertTrue(row["created_at"])

    def test_funciona_con_el_token_jwt_real(self):
        client = APIClient()
        token = client.post(reverse("token_obtain_pair"), {"username": "prod@t.co", "password": PASSWORD}).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.post(
            reverse("produccion_tarifas"), {"etapa": "CORTE", "costo_minuto": "100.0000"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AuditRecord.objects.get(action="tarifa.modificar").user, self.produccion)

    def test_operacion_rechazada_por_permiso_tambien_queda_registrada(self):
        almacen = make_user("alm@t.co", "ALMACENISTA")
        response = client_for(almacen).post(
            reverse("terminado_ajustes"), {"referencia": 1, "cantidad": 5, "motivo": "x"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        row = AuditRecord.objects.get()
        self.assertEqual((row.action, row.result, row.user_email), ("producto_terminado.ajuste", "rechazado", "alm@t.co"))
        self.assertEqual(row.detail["http"], 403)

    def test_error_de_validacion_queda_como_error(self):
        response = client_for(self.produccion).post(reverse("produccion_tarifas"), {"etapa": "CORTE"}, format="json")
        self.assertEqual(response.status_code, 400)
        row = AuditRecord.objects.get()
        self.assertEqual((row.action, row.result), ("tarifa.modificar", "error"))

    def test_sin_sesion_no_se_atribuye_a_nadie(self):
        APIClient().post(reverse("produccion_tarifas"), {}, format="json")
        self.assertEqual(AuditRecord.objects.count(), 0)

    def test_las_consultas_no_se_auditan(self):
        client_for(self.produccion).get(reverse("produccion_tarifas"))
        self.assertEqual(AuditRecord.objects.count(), 0)

    def test_no_guarda_contrasenas_ni_tokens(self):
        client_for(self.admin).post(
            reverse("user_list"),
            {"email": "nuevo@t.co", "first_name": "N", "password": "SuperSecreta#1", "token": "abc.def.ghi", "role": "VENDEDOR"},
            format="json",
        )
        row = AuditRecord.objects.get(action="usuario.crear")
        stored = str(row.detail)
        self.assertNotIn("SuperSecreta#1", stored)
        self.assertNotIn("abc.def.ghi", stored)
        self.assertEqual(row.detail["datos"]["password"], "***")
        self.assertEqual(row.detail["datos"]["email"], "nuevo@t.co")

    def test_cambio_de_rol_de_un_usuario_queda_auditado(self):
        target = make_user("pend@t.co", "PENDING")
        response = client_for(self.admin).patch(reverse("user_detail", args=[target.pk]), {"role": "VENDEDOR"}, format="json")
        self.assertEqual(response.status_code, 200)
        row = AuditRecord.objects.get(action="usuario.modificar")
        self.assertEqual(row.entity_id, str(target.pk))
        self.assertEqual(row.detail["datos"], {"role": "VENDEDOR"})

    def test_la_accion_del_lote_va_en_el_registro(self):
        client_for(self.produccion).post(reverse("produccion_lote_accion", args=[999, "iniciar"]), {}, format="json")
        self.assertTrue(AuditRecord.objects.filter(action="lote.iniciar", entity_id="999").exists())

    def test_archivos_y_formularios_no_guardan_datos(self):
        client_for(self.produccion).post(reverse("produccion_tarifas"), {"etapa": "CORTE"})  # multipart
        self.assertNotIn("datos", AuditRecord.objects.get().detail)


class UnauthorizedApiAccessTests(TestCase):
    """Prueba de acceso indebido por la API (H05): cada operación crítica rechaza a un rol sin permiso."""

    def setUp(self):
        cache.clear()
        self.nobody = make_user("pend@t.co", "PENDING")  # sin ningún permiso

    def test_todas_las_operaciones_criticas_rechazan_al_rol_sin_permiso_y_lo_auditan(self):
        for (name, method), (action, _entity) in AUDITED.items():
            with self.subTest(ruta=name, metodo=method):
                AuditRecord.objects.all()  # la lectura funciona
                before = AuditRecord.objects.count()
                response = getattr(client_for(self.nobody), method.lower())(url_for(name), {}, format="json")
                self.assertEqual(response.status_code, 403, f"{method} {name} debe responder «sin permiso»")
                self.assertEqual(AuditRecord.objects.count(), before + 1)
                row = AuditRecord.objects.first()
                self.assertEqual(row.result, "rechazado")
                self.assertEqual(row.user_email, "pend@t.co")
                self.assertEqual(row.action, action.format(accion="iniciar"))

    def test_sin_token_todas_responden_401_y_no_dejan_auditoria(self):
        for (name, method) in AUDITED:
            with self.subTest(ruta=name, metodo=method):
                response = getattr(APIClient(), method.lower())(url_for(name), {}, format="json")
                self.assertEqual(response.status_code, 401)
        self.assertEqual(AuditRecord.objects.count(), 0)

    def test_el_catalogo_solo_apunta_a_rutas_que_existen(self):
        for name, _method in AUDITED:
            url_for(name)  # falla si una ruta se renombra y la auditoría quedaría ciega


class AppendOnlyTests(TestCase):
    def setUp(self):
        self.row = AuditRecord.objects.create(action="x.y", result="exito", user_email="a@t.co")

    def test_no_se_edita_una_fila(self):
        self.row.action = "otra"
        with self.assertRaises(TypeError):
            self.row.save()

    def test_no_se_borra_una_fila_ni_en_bloque(self):
        with self.assertRaises(TypeError):
            self.row.delete()
        with self.assertRaises(TypeError):
            AuditRecord.objects.all().delete()
        with self.assertRaises(TypeError):
            AuditRecord.objects.all().update(action="otra")
        self.assertEqual(AuditRecord.objects.get().action, "x.y")

    def test_la_api_no_ofrece_escritura(self):
        admin = make_user("admin@t.co", "ADMIN")
        client = client_for(admin)
        for url in (reverse("audit_list"), reverse("audit_catalog")):
            for method in ("post", "put", "patch", "delete"):
                self.assertIn(getattr(client, method)(url, {}).status_code, (403, 405))
        self.assertEqual(AuditRecord.objects.count(), 1)


class AuditQueryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@t.co", "ADMIN")
        self.manager = make_user("ger@t.co", "GERENTE")
        self.ana = make_user("ana@t.co", "VENDEDOR")
        audit.record(self.ana, "factura.emitir", "factura", 10)
        audit.record(self.ana, "factura.anular", "factura", 10, result="rechazado")
        old = AuditRecord.objects.create(action="tarifa.modificar", entity="tarifa", result="exito", user_email="x@t.co")
        # la fecha de la fila antigua se fija con SQL directo: el modelo no permite editar
        with connection.cursor() as cursor:
            cursor.execute("UPDATE seguridad_auditoria SET created_at = %s WHERE id = %s", [timezone.now() - timedelta(days=30), old.pk])

    def get(self, who, **params):
        return client_for(who).get(reverse("audit_list"), params)

    def test_administrador_y_gerente_consultan_el_vendedor_no(self):
        self.assertEqual(self.get(self.admin).status_code, 200)
        self.assertEqual(self.get(self.manager).status_code, 200)
        self.assertEqual(self.get(self.ana).status_code, 403)
        self.assertEqual(APIClient().get(reverse("audit_list")).status_code, 401)

    def test_filtros(self):
        self.assertEqual(self.get(self.admin).data["count"], 3)
        self.assertEqual(self.get(self.admin, user=self.ana.pk).data["count"], 2)
        self.assertEqual(self.get(self.admin, result="rechazado").data["count"], 1)
        self.assertEqual(self.get(self.admin, action="factura.emitir").data["count"], 1)
        self.assertEqual(self.get(self.admin, entity="factura", entity_id="10").data["count"], 2)
        since = (timezone.localtime() - timedelta(days=7)).date().isoformat()
        self.assertEqual(self.get(self.admin, date_from=since).data["count"], 2)

    def test_filtros_invalidos(self):
        self.assertEqual(self.get(self.admin, result="raro").status_code, 400)
        self.assertEqual(self.get(self.admin, date_to="ayer").status_code, 400)
        self.assertEqual(self.get(self.admin, user="x").status_code, 400)

    def test_catalogo_de_filtros(self):
        data = client_for(self.manager).get(reverse("audit_catalog")).data
        self.assertIn("factura.anular", data["actions"])
        self.assertIn("lote.*", data["actions"])
        self.assertIn("tarifa", data["entities"])

    def test_el_permiso_existe_y_lo_tiene_el_gerente(self):
        perm = ModulePermission.objects.get(code="seguridad.auditoria")
        self.assertTrue(perm.roles.filter(code="GERENTE").exists())


class SanitizeAndRetentionTests(TestCase):
    def test_sanitize_oculta_secretos_y_acota_tamanos(self):
        data = sanitize({"password": "x", "Authorization": "Bearer y", "api_key": "z", "nombre": "a" * 500, "items": list(range(50))})
        self.assertEqual(data["password"], "***")
        self.assertEqual(data["Authorization"], "***")
        self.assertEqual(data["api_key"], "***")
        self.assertEqual(len(data["nombre"]), 200)
        self.assertEqual(len(data["items"]), 20)

    def test_la_purga_borra_lo_vencido_y_queda_registrada(self):
        old = AuditRecord.objects.create(action="vieja.accion", result="exito")
        recent = AuditRecord.objects.create(action="reciente.accion", result="exito")
        with connection.cursor() as cursor:
            cursor.execute("UPDATE seguridad_auditoria SET created_at = %s WHERE id = %s", [timezone.now() - timedelta(days=400), old.pk])
        call_command("purgar_registros", stdout=StringIO())
        actions = set(AuditRecord.objects.values_list("action", flat=True))
        self.assertEqual(actions, {"reciente.accion", "auditoria.purga"})
        self.assertTrue(AuditRecord.objects.filter(pk=recent.pk).exists())
        purge = AuditRecord.objects.get(action="auditoria.purga")
        self.assertEqual(purge.detail["auditoria"], 1)
