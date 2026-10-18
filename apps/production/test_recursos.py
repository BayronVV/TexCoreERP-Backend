"""Asignación de recursos (HU 4.4 / RF14): catálogo de operarios y máquinas, asignación por etapa, historial y avisos."""
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.inventory.tests import client_for, make_user

from . import catalog, resources
from .models import AsignacionEtapa, EtapaLote, Maquina, Operario
from .test_ordenes import OrderBase

ALL_STAGES = ["CORTE", "CONFECCION", "TERMINACION"]


class ResourcesBase(OrderBase):
    def setUp(self):
        super().setUp()
        self.viewer = client_for(make_user("gerente_recursos@t.co", "GERENTE"))
        self.stranger = client_for(make_user("almacen_recursos@t.co", "ALMACENISTA"))

    # --- catálogo por servicio (rápido) ---
    def operator(self, name="Ana Pérez", stages=None, **extra):
        return resources.create_operator(data={"nombres": name, "etapas": stages or ALL_STAGES, **extra})

    def machine(self, kind="PLANA", stages=None, **extra):
        return resources.create_machine(data={"tipo": kind, "etapas": stages or ALL_STAGES, **extra})

    # --- órdenes y lotes ---
    def lots(self, sizes=(5, 5)):
        order = self.placed(sum(sizes), lots=[{"cantidad": size} for size in sizes])
        return [lot["id"] for lot in order["lotes"]], order

    def assign_url(self, lot_id):
        return reverse("produccion_lote_asignar", kwargs={"pk": lot_id})

    def assign(self, lot_id, stage="CORTE", client=None, **body):
        return (client or self.api).post(self.assign_url(lot_id), {"etapa": stage, **body}, format="json")

    def unlink(self, lot_id, stage="CORTE", resource="ambos"):
        url = reverse("produccion_lote_desvincular", kwargs={"pk": lot_id})
        return self.api.post(url, {"etapa": stage, "recurso": resource}, format="json")

    def act(self, lot_id, action):
        url = reverse("produccion_lote_accion", kwargs={"pk": lot_id, "accion": action})
        response = self.api.post(url, {}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def history(self, lot_id):
        response = self.api.get(reverse("produccion_lote_asignaciones", kwargs={"pk": lot_id}))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def stage_of(self, body, code="CORTE"):
        """La etapa del lote; acepta la respuesta de asignar (`{"lote": ...}`) o el lote mismo."""
        lot = body.get("lote", body) if "etapas" not in body else body
        return next(stage for stage in lot["etapas"] if stage["etapa"] == code)

    def assertBlocked(self, response, field, text):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(text, str(response.json()[field][0]))
        self.assertFalse(AsignacionEtapa.objects.exists())


class CatalogoOperariosTests(ResourcesBase):
    list_url = property(lambda self: reverse("produccion_operarios"))

    def test_crea_con_codigo_consecutivo_y_etapas_en_orden_del_flujo(self):
        first = self.api.post(self.list_url, {"nombres": "Ana Pérez", "etapas": ["TERMINACION", "CORTE"]}, format="json")
        second = self.api.post(self.list_url, {"nombres": "Luis Gómez", "etapas": ["CONFECCION"], "tipo_pago": "PIEZA"}, format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 201), first.content)
        self.assertEqual((first.json()["codigo"], second.json()["codigo"]), ("OPE-0001", "OPE-0002"))
        self.assertEqual(first.json()["etapas"], ["CORTE", "TERMINACION"])
        self.assertEqual(first.json()["tipo_pago"], "TIEMPO")  # el valor por defecto
        self.assertEqual((second.json()["tipo_pago"], second.json()["tipo_pago_nombre"]), ("PIEZA", "Por pieza"))
        self.assertEqual((first.json()["advertencias"], first.json()["activo"]), ([], True))

    def test_valida_los_datos(self):
        for body, field in (
            ({"etapas": ["CORTE"]}, "nombres"),
            ({"nombres": "Ana", "etapas": []}, "etapas"),
            ({"nombres": "Ana", "etapas": ["LAVADO"]}, "etapas"),
            ({"nombres": "Ana"}, "etapas"),
            ({"nombres": "Ana", "etapas": ["CORTE"], "documento": "12ab"}, "documento"),
            ({"nombres": "Ana", "etapas": ["CORTE"], "tipo_pago": "OTRO"}, "tipo_pago"),
            ({"nombres": "A" * 121, "etapas": ["CORTE"]}, "nombres"),
        ):
            response = self.api.post(self.list_url, body, format="json")
            self.assertEqual(response.status_code, 400, (body, response.content))
            self.assertIn(field, response.json())
        self.assertEqual(Operario.objects.count(), 0)

    def test_el_documento_es_unico_entre_los_activos(self):
        self.operator(documento="1090123456")
        response = self.api.post(self.list_url, {"nombres": "Otra", "etapas": ["CORTE"], "documento": "1090123456"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("documento", response.json())
        # sin documento puede haber varios
        self.operator("Uno")
        self.operator("Dos")
        self.assertEqual(Operario.objects.count(), 3)

    def test_permisos(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.assertEqual(self.viewer.get(self.list_url).status_code, 200)  # el gerente consulta
        body = {"nombres": "Ana", "etapas": ["CORTE"]}
        self.assertEqual(self.viewer.post(self.list_url, body, format="json").status_code, 403)  # pero no administra
        self.assertEqual(self.stranger.get(self.list_url).status_code, 403)
        self.assertEqual(self.stranger.post(self.list_url, body, format="json").status_code, 403)
        self.assertEqual(Operario.objects.count(), 0)

    def test_filtros_de_la_lista(self):
        ana = self.operator("Ana Pérez", ["CORTE"], documento="1000000001")
        luis = self.operator("Luis Gómez", ["CONFECCION", "TERMINACION"])
        resources.update_operator(luis, data={"activo": False})

        def names(**params):
            body = self.api.get(self.list_url, params).json()
            return [item["nombres"] for item in body]

        self.assertEqual(names(), ["Ana Pérez", "Luis Gómez"])
        self.assertEqual(names(activo="1"), ["Ana Pérez"])
        self.assertEqual(names(activo="0"), ["Luis Gómez"])
        self.assertEqual(names(etapa="CONFECCION"), ["Luis Gómez"])
        self.assertEqual(names(q="pérez"), ["Ana Pérez"])
        self.assertEqual(names(q=ana.codigo), ["Ana Pérez"])
        self.assertEqual(names(q="1000000001"), ["Ana Pérez"])
        self.assertEqual(self.api.get(self.list_url, {"activo": "quizás"}).status_code, 400)
        self.assertEqual(self.api.get(self.list_url, {"etapa": "LAVADO"}).status_code, 400)

    def test_editar_y_desactivar(self):
        operator = self.operator("Ana Pérez", ["CORTE"])
        url = reverse("produccion_operario", kwargs={"pk": operator.pk})
        response = self.api.patch(url, {"nombres": "Ana María Pérez", "etapas": ["CONFECCION", "CORTE"]}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["nombres"], response.json()["etapas"]), ("Ana María Pérez", ["CORTE", "CONFECCION"]))
        self.assertEqual(self.api.patch(url, {"activo": False}, format="json").json()["activo"], False)
        self.assertEqual(self.api.get(url).json()["codigo"], operator.codigo)  # sigue existiendo
        self.assertEqual(self.viewer.patch(url, {"activo": True}, format="json").status_code, 403)
        self.assertEqual(self.api.patch(reverse("produccion_operario", kwargs={"pk": 9999}), {}, format="json").status_code, 404)
        self.assertIn(self.api.delete(url).status_code, (403, 405))  # no se borra: se desactiva

    def test_editar_no_puede_repetir_el_documento_de_otro(self):
        self.operator("Ana", documento="1000000001")
        luis = self.operator("Luis", documento="1000000002")
        url = reverse("produccion_operario", kwargs={"pk": luis.pk})
        self.assertEqual(self.api.patch(url, {"documento": "1000000001"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"documento": "1000000002"}, format="json").status_code, 200)  # el suyo, sí

    def test_desactivar_con_etapa_en_curso_avisa_y_no_cierra_nada(self):
        operator = self.operator("Ana", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assertEqual(self.assign(lot_id, operario=operator.pk).status_code, 200)
        self.act(lot_id, "iniciar")
        response = self.api.patch(reverse("produccion_operario", kwargs={"pk": operator.pk}), {"activo": False}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("sigue asignado", response.json()["advertencias"][0])
        self.assertEqual(AsignacionEtapa.objects.filter(fin_at__isnull=True).count(), 1)

    def test_la_lista_muestra_donde_esta_ocupado(self):
        operator = self.operator("Ana", ["CORTE"])
        (lot_id, _), order = self.lots()
        self.assign(lot_id, operario=operator.pk)
        listed = lambda: self.api.get(self.list_url).json()[0]["ocupado_en"]
        self.assertEqual(listed(), [])  # asignado a una etapa que no está en curso: no está ocupado
        self.act(lot_id, "iniciar")
        self.assertEqual(listed(), [f"{order['codigo']}-L01 · Corte"])


class CatalogoMaquinasTests(ResourcesBase):
    list_url = property(lambda self: reverse("produccion_maquinas"))

    def test_crea_con_codigo_consecutivo(self):
        body = {"tipo": "FILETEADORA", "etapas": ["CONFECCION"], "marca_modelo": "Juki MO-6814", "ubicacion": "Línea 2"}
        first = self.api.post(self.list_url, body, format="json")
        second = self.api.post(self.list_url, {"tipo": "CORTADORA", "etapas": ["CORTE"]}, format="json")
        self.assertEqual((first.status_code, second.status_code), (201, 201), first.content)
        self.assertEqual((first.json()["codigo"], second.json()["codigo"]), ("MAQ-0001", "MAQ-0002"))
        data = first.json()
        self.assertEqual((data["tipo_nombre"], data["estado"], data["estado_nombre"]), ("Fileteadora", "DISPONIBLE", "Disponible"))
        self.assertEqual((data["asignable"], data["ocupada_en"], data["advertencias"]), (True, [], []))

    def test_valida_los_datos(self):
        for body, field in (
            ({"etapas": ["CORTE"]}, "tipo"),
            ({"tipo": "LASER", "etapas": ["CORTE"]}, "tipo"),
            ({"tipo": "PLANA", "etapas": []}, "etapas"),
            ({"tipo": "PLANA", "etapas": ["PLANCHADO"]}, "etapas"),
            ({"tipo": "PLANA", "etapas": ["CORTE"], "estado": "OCUPADA"}, "estado"),
        ):
            response = self.api.post(self.list_url, body, format="json")
            self.assertEqual(response.status_code, 400, (body, response.content))
            self.assertIn(field, response.json())
        self.assertEqual(Maquina.objects.count(), 0)

    def test_ocupada_no_es_un_estado_que_se_guarde(self):
        self.assertNotIn("OCUPADA", [code for code, _ in catalog.MACHINE_STATES])

    def test_permisos(self):
        body = {"tipo": "PLANA", "etapas": ["CONFECCION"]}
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.assertEqual(self.viewer.get(self.list_url).status_code, 200)
        self.assertEqual(self.viewer.post(self.list_url, body, format="json").status_code, 403)
        self.assertEqual(self.stranger.get(self.list_url).status_code, 403)
        self.assertEqual(Maquina.objects.count(), 0)

    def test_filtros_de_la_lista(self):
        self.machine("PLANA", ["CONFECCION"], ubicacion="Línea 1", marca_modelo="Juki")
        cutter = self.machine("CORTADORA", ["CORTE"])
        resources.update_machine(cutter, data={"estado": catalog.MACHINE_MAINTENANCE})

        def codes(**params):
            return [item["codigo"] for item in self.api.get(self.list_url, params).json()]

        self.assertEqual(codes(), ["MAQ-0001", "MAQ-0002"])
        self.assertEqual(codes(tipo="CORTADORA"), ["MAQ-0002"])
        self.assertEqual(codes(estado="MANTENIMIENTO"), ["MAQ-0002"])
        self.assertEqual(codes(etapa="CONFECCION"), ["MAQ-0001"])
        self.assertEqual(codes(q="juki"), ["MAQ-0001"])
        self.assertEqual(codes(q="línea 1"), ["MAQ-0001"])
        self.assertEqual(codes(activo="0"), [])
        asignable = {item["codigo"]: item["asignable"] for item in self.api.get(self.list_url).json()}
        self.assertEqual(asignable, {"MAQ-0001": True, "MAQ-0002": False})

    def test_cambiar_el_estado_y_desactivar(self):
        machine = self.machine("PLANA", ["CONFECCION"])
        url = reverse("produccion_maquina", kwargs={"pk": machine.pk})
        data = self.api.patch(url, {"estado": "FUERA_SERVICIO", "observaciones": "Motor quemado"}, format="json").json()
        self.assertEqual((data["estado_nombre"], data["asignable"], data["observaciones"]), ("Fuera de servicio", False, "Motor quemado"))
        self.assertEqual(self.api.patch(url, {"estado": "OCUPADA"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"activo": False}, format="json").json()["activo"], False)
        self.assertEqual(self.viewer.patch(url, {"activo": True}, format="json").status_code, 403)
        self.assertIn(self.api.delete(url).status_code, (403, 405))  # no se borra: se desactiva

    def test_pasar_a_mantenimiento_con_etapa_en_curso_avisa(self):
        machine = self.machine("PLANA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, maquina=machine.pk)
        self.act(lot_id, "iniciar")
        data = self.api.patch(reverse("produccion_maquina", kwargs={"pk": machine.pk}), {"estado": "MANTENIMIENTO"}, format="json").json()
        self.assertIn("sigue asignada", data["advertencias"][0])  # concuerda con «la máquina»
        self.assertEqual(AsignacionEtapa.objects.filter(fin_at__isnull=True).count(), 1)  # no se cierra por su cuenta


class AsignarTests(ResourcesBase):
    def test_asigna_operario_y_maquina_a_una_etapa(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        response = self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["advertencias"], [])
        assignment = self.stage_of(body)["asignacion"]
        self.assertEqual(assignment["operario"], {"id": operator.pk, "codigo": "OPE-0001", "nombres": "Ana"})
        self.assertEqual(assignment["maquina"]["codigo"], "MAQ-0001")
        self.assertEqual(assignment["maquina"]["tipo_nombre"], "Cortadora de tela")
        self.assertIsNone(self.stage_of(body, "CONFECCION")["asignacion"])  # solo la etapa pedida
        stored = AsignacionEtapa.objects.get()
        self.assertIsNotNone(stored.asignada_por)  # queda quién hizo la asignación
        self.assertIsNone(stored.fin_at)

    def test_se_puede_asignar_solo_el_operario_o_solo_la_maquina(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (first, second), _ = self.lots()
        self.assertEqual(self.assign(first, operario=operator.pk).status_code, 200)
        self.assertEqual(self.assign(second, maquina=machine.pk).status_code, 200)
        self.assertIsNone(AsignacionEtapa.objects.get(etapa_lote__lote_id=first).maquina)
        self.assertIsNone(AsignacionEtapa.objects.get(etapa_lote__lote_id=second).operario)

    def test_la_clave_que_no_se_envia_se_deja_como_esta(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        other = self.machine("PLANA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        body = self.assign(lot_id, maquina=other.pk).json()  # cambia solo la máquina
        assignment = self.stage_of(body)["asignacion"]
        self.assertEqual((assignment["operario"]["id"], assignment["maquina"]["id"]), (operator.pk, other.pk))

    def test_reasignar_cierra_la_anterior_y_deja_historial(self):
        ana, luis = self.operator("Ana", ["CORTE"]), self.operator("Luis", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=ana.pk)
        self.assign(lot_id, operario=luis.pk)
        rows = self.history(lot_id)
        self.assertEqual([(row["operario_nombre"], row["vigente"]) for row in rows], [("Ana", False), ("Luis", True)])
        self.assertIsNotNone(rows[0]["fin_at"])
        self.assertLessEqual(rows[0]["inicio_at"], rows[1]["inicio_at"])
        self.assertEqual(AsignacionEtapa.objects.filter(etapa_lote__lote_id=lot_id, fin_at__isnull=True).count(), 1)
        self.assertEqual(rows[1]["etapa_nombre"], "Corte")
        self.assertTrue(rows[1]["asignada_por_nombre"])

    def test_repetir_la_misma_asignacion_no_crea_otra_fila(self):
        operator = self.operator("Ana", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=operator.pk)
        self.assign(lot_id, operario=operator.pk)
        self.assertEqual(AsignacionEtapa.objects.count(), 1)

    def test_desvincular_quita_solo_lo_pedido(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        body = self.unlink(lot_id, resource="operario").json()
        assignment = self.stage_of(body["lote"])["asignacion"]
        self.assertIsNone(assignment["operario"])
        self.assertEqual(assignment["maquina"]["id"], machine.pk)
        body = self.unlink(lot_id, resource="maquina").json()
        self.assertIsNone(self.stage_of(body["lote"])["asignacion"])  # ya no queda nada
        self.assertEqual(AsignacionEtapa.objects.filter(fin_at__isnull=True).count(), 0)
        self.assertEqual(AsignacionEtapa.objects.count(), 2)  # el historial se conserva

    def test_desvincular_ambos_y_enviar_null(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        self.assertIsNone(self.stage_of(self.unlink(lot_id).json()["lote"])["asignacion"])
        self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        body = self.assign(lot_id, operario=None, maquina=None).json()  # `null` también quita
        self.assertIsNone(self.stage_of(body)["asignacion"])
        self.assertEqual(self.unlink(lot_id).status_code, 200)  # desvincular lo que no hay no falla

    def test_desvincular_con_recurso_invalido(self):
        (lot_id, _), _ = self.lots()
        self.assertEqual(self.unlink(lot_id, resource="todo").status_code, 400)

    def test_pide_al_menos_un_recurso_y_una_etapa_valida(self):
        (lot_id, _), _ = self.lots()
        self.assertEqual(self.assign(lot_id).status_code, 400)  # ni operario ni máquina
        operator = self.operator("Ana", ["CORTE"])
        self.assertEqual(self.assign(lot_id, stage="LAVADO", operario=operator.pk).status_code, 400)
        self.assertEqual(self.api.post(self.assign_url(lot_id), {"operario": operator.pk}, format="json").status_code, 400)
        self.assertFalse(AsignacionEtapa.objects.exists())

    def test_lote_inexistente(self):
        operator = self.operator("Ana", ["CORTE"])
        self.assertEqual(self.assign(999999, operario=operator.pk).status_code, 400)

    def test_permisos(self):
        operator = self.operator("Ana", ["CORTE"])
        (lot_id, _), _ = self.lots()
        body = {"etapa": "CORTE", "operario": operator.pk}
        self.assertEqual(self.client.post(self.assign_url(lot_id), body, format="json").status_code, 401)
        self.assertEqual(self.viewer.post(self.assign_url(lot_id), body, format="json").status_code, 403)
        self.assertEqual(self.stranger.post(self.assign_url(lot_id), body, format="json").status_code, 403)
        self.assertEqual(self.viewer.get(reverse("produccion_lote_asignaciones", kwargs={"pk": lot_id})).status_code, 200)
        self.assertEqual(self.stranger.get(reverse("produccion_lote_asignaciones", kwargs={"pk": lot_id})).status_code, 403)
        self.assertFalse(AsignacionEtapa.objects.exists())

    def test_las_rutas_de_asignacion_no_se_confunden_con_las_acciones_del_lote(self):
        # `asignar` y `desvincular` están antes de `<accion>`: no responden «la acción debe ser una de iniciar...».
        operator = self.operator("Ana", ["CORTE"])
        (lot_id, _), _ = self.lots()
        response = self.assign(lot_id, operario=operator.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn("accion", response.json())


class BloqueosTests(ResourcesBase):
    def setUp(self):
        super().setUp()
        (self.lot_id, self.other_lot), self.order = self.lots()

    def test_operario_inactivo(self):
        operator = self.operator("Ana", ["CORTE"])
        resources.update_operator(operator, data={"activo": False})
        self.assertBlocked(self.assign(self.lot_id, operario=operator.pk), "operario", "inactivo")

    def test_operario_no_habilitado_para_la_etapa(self):
        operator = self.operator("Ana", ["CONFECCION"])
        self.assertBlocked(self.assign(self.lot_id, operario=operator.pk), "operario", "no está habilitado para Corte")

    def test_operario_o_maquina_inexistentes_o_con_id_invalido(self):
        for key in ("operario", "maquina"):
            for value in (999999, True):
                response = self.assign(self.lot_id, **{key: value})
                self.assertEqual(response.status_code, 400, (key, value, response.content))
        self.assertFalse(AsignacionEtapa.objects.exists())

    def test_maquina_en_mantenimiento_o_fuera_de_servicio(self):
        for state, text in ((catalog.MACHINE_MAINTENANCE, "en mantenimiento"), (catalog.MACHINE_OUT, "fuera de servicio")):
            machine = self.machine("PLANA", ["CORTE"], estado=state)
            self.assertBlocked(self.assign(self.lot_id, maquina=machine.pk), "maquina", text)

    def test_maquina_inactiva(self):
        machine = self.machine("PLANA", ["CORTE"])
        resources.update_machine(machine, data={"activo": False})
        self.assertBlocked(self.assign(self.lot_id, maquina=machine.pk), "maquina", "inactiva")

    def test_maquina_que_no_se_usa_en_la_etapa(self):
        machine = self.machine("OJALADORA", ["TERMINACION"])
        self.assertBlocked(self.assign(self.lot_id, maquina=machine.pk), "maquina", "no se usa en Corte")

    def test_un_rechazo_no_cambia_la_asignacion_vigente(self):
        ana = self.operator("Ana", ["CORTE"])
        broken = self.machine("PLANA", ["CORTE"], estado=catalog.MACHINE_OUT)
        self.assign(self.lot_id, operario=ana.pk)
        response = self.assign(self.lot_id, maquina=broken.pk)
        self.assertEqual(response.status_code, 400)
        rows = AsignacionEtapa.objects.filter(etapa_lote__lote_id=self.lot_id)
        self.assertEqual((rows.count(), rows.get().operario_id, rows.get().fin_at), (1, ana.pk, None))

    def test_etapa_terminada(self):
        operator = self.operator("Ana", ALL_STAGES)
        self.act(self.lot_id, "iniciar")
        self.act(self.lot_id, "completar")
        self.assertBlocked(self.assign(self.lot_id, operario=operator.pk), "etapa", "ya terminó")
        self.assertEqual(self.assign(self.lot_id, stage="CONFECCION", operario=operator.pk).status_code, 200)  # la siguiente, sí

    def test_orden_anulada(self):
        operator = self.operator("Ana", ["CORTE"])
        response = self.api.post(reverse("produccion_orden_anular", kwargs={"pk": self.order["id"]}), {"motivo": "Error"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertBlocked(self.assign(self.lot_id, operario=operator.pk), "orden", "anulada")


class AvisosTests(ResourcesBase):
    def test_recurso_en_otra_etapa_en_curso_solo_avisa(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (first, second), order = self.lots()
        self.assign(first, operario=operator.pk, maquina=machine.pk)
        self.act(first, "iniciar")
        response = self.assign(second, operario=operator.pk, maquina=machine.pk)
        self.assertEqual(response.status_code, 200, response.content)  # no bloquea
        warnings = response.json()["advertencias"]
        self.assertEqual(len(warnings), 2)
        self.assertIn(f"{order['codigo']}-L01 (Corte)", warnings[0])
        self.assertTrue(warnings[0].startswith("El operario Ana") and warnings[1].startswith("La máquina MAQ-0001"))
        self.assertIn("ya está asignado a", warnings[0])
        self.assertIn("ya está asignada a", warnings[1])
        self.assertEqual(AsignacionEtapa.objects.filter(fin_at__isnull=True).count(), 2)

    def test_una_etapa_que_no_ha_empezado_no_cuenta_como_ocupada(self):
        operator = self.operator("Ana", ["CORTE"])
        (first, second), _ = self.lots()
        self.assign(first, operario=operator.pk)  # asignada, pero sin iniciar
        self.assertEqual(self.assign(second, operario=operator.pk).json()["advertencias"], [])

    def test_no_se_avisa_contra_si_misma_ni_contra_etapas_terminadas(self):
        operator = self.operator("Ana", ALL_STAGES)
        (first, second), _ = self.lots()
        self.assign(first, operario=operator.pk)
        self.act(first, "iniciar")
        self.assertEqual(self.assign(first, operario=operator.pk).json()["advertencias"], [])  # la misma etapa
        self.act(first, "completar")
        self.assertEqual(self.assign(second, operario=operator.pk).json()["advertencias"], [])  # ya terminó


class HistorialYCierreTests(ResourcesBase):
    def test_terminar_la_etapa_cierra_la_asignacion_y_libera_al_operario(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        self.act(lot_id, "iniciar")
        self.act(lot_id, "pausar")
        self.assertEqual(AsignacionEtapa.objects.filter(fin_at__isnull=True).count(), 1)  # en pausa sigue asignada
        body = self.act(lot_id, "completar")
        self.assertIsNone(self.stage_of({"lote": body})["asignacion"])
        row = self.history(lot_id)[0]
        self.assertEqual((row["vigente"], row["operario_nombre"], row["maquina_codigo"]), (False, "Ana", "MAQ-0001"))
        self.assertEqual(self.api.get(reverse("produccion_operarios")).json()[0]["ocupado_en"], [])

    def test_la_siguiente_etapa_puede_tener_otro_operario(self):
        cutter = self.operator("Carlos", ["CORTE"])
        sewer = self.operator("Sofía", ["CONFECCION"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, stage="CORTE", operario=cutter.pk)
        self.act(lot_id, "iniciar")
        self.act(lot_id, "completar")
        self.assign(lot_id, stage="CONFECCION", operario=sewer.pk)
        rows = self.history(lot_id)
        self.assertEqual([(row["etapa"], row["operario_nombre"], row["vigente"]) for row in rows],
                         [("CORTE", "Carlos", False), ("CONFECCION", "Sofía", True)])

    def test_anular_la_orden_cierra_las_asignaciones_abiertas(self):
        operator, machine = self.operator("Ana", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (first, second), order = self.lots()
        self.assign(first, operario=operator.pk, maquina=machine.pk)
        self.assign(second, operario=operator.pk)
        self.act(first, "iniciar")
        self.api.post(reverse("produccion_orden_anular", kwargs={"pk": order["id"]}), {"motivo": "Error de carga"}, format="json")
        self.assertEqual(AsignacionEtapa.objects.filter(fin_at__isnull=True).count(), 0)
        self.assertEqual(AsignacionEtapa.objects.count(), 2)
        self.assertEqual(self.api.get(reverse("produccion_operarios")).json()[0]["ocupado_en"], [])

    def test_historial_de_un_lote_sin_asignaciones(self):
        (lot_id, _), _ = self.lots()
        self.assertEqual(self.history(lot_id), [])


class IntegracionTests(ResourcesBase):
    def test_el_monitor_muestra_el_operario_y_la_maquina_de_la_etapa_en_curso(self):
        operator, machine = self.operator("Ana Pérez", ["CORTE"]), self.machine("CORTADORA", ["CORTE"])
        (lot_id, _), _ = self.lots()
        self.assign(lot_id, operario=operator.pk, maquina=machine.pk)
        self.act(lot_id, "iniciar")
        board = self.api.get(reverse("produccion_monitor")).json()
        cards = [card for column in board["columnas"] for card in column["lotes"] if card["id"] == lot_id]
        self.assertEqual((cards[0]["operario_nombre"], cards[0]["maquina_codigo"]), ("Ana Pérez", "MAQ-0001"))
        other = next(card for column in board["columnas"] for card in column["lotes"] if card["id"] != lot_id)
        self.assertEqual((other["operario_nombre"], other["maquina_codigo"]), ("", ""))

    def test_la_orden_y_el_lote_traen_la_asignacion_de_cada_etapa(self):
        operator = self.operator("Ana", ["CORTE"])
        (lot_id, _), order = self.lots()
        self.assign(lot_id, operario=operator.pk)
        detail = self.api.get(reverse("produccion_orden", kwargs={"pk": order["id"]})).json()
        stage = next(item for item in detail["lotes"][0]["etapas"] if item["etapa"] == "CORTE")
        self.assertEqual(stage["asignacion"]["operario"]["nombres"], "Ana")

    def test_las_consultas_no_crecen_con_el_numero_de_lotes(self):
        operator = self.operator("Ana", ["CORTE"])
        small, _ = self.lots((2, 2))
        for lot_id in small:
            self.assign(lot_id, operario=operator.pk)
        big, _ = self.lots((1, 1, 1, 1, 1, 1))
        for lot_id in big:
            self.assign(lot_id, operario=operator.pk)

        def count(url):
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.api.get(url).status_code, 200)
            return len(queries)

        orders_url = reverse("produccion_ordenes")
        count(orders_url)  # calienta cachés de permisos
        baseline = count(orders_url)
        # Con 2 órdenes y 8 lotes las consultas son las mismas que con una orden y menos lotes: no hay N+1 por etapa.
        with transaction.atomic():
            self.lots((1, 1, 1, 1, 1, 1, 1, 1))
        self.assertEqual(count(orders_url), baseline)
        monitor_url = reverse("produccion_monitor")
        count(monitor_url)
        monitor_baseline = count(monitor_url)
        with transaction.atomic():
            self.lots((1, 1, 1, 1))
        self.assertEqual(count(monitor_url), monitor_baseline)


class ModeloTests(ResourcesBase):
    def stage(self):
        (lot_id, _), _ = self.lots()
        return EtapaLote.objects.get(lote_id=lot_id, etapa="CORTE")

    def test_una_etapa_tiene_como_maximo_una_asignacion_abierta(self):
        stage, operator = self.stage(), self.operator("Ana")
        AsignacionEtapa.objects.create(etapa_lote=stage, operario=operator, inicio_at=timezone.now())
        with self.assertRaises(IntegrityError), transaction.atomic():
            AsignacionEtapa.objects.create(etapa_lote=stage, operario=operator, inicio_at=timezone.now())

    def test_una_asignacion_lleva_al_menos_un_recurso(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AsignacionEtapa.objects.create(etapa_lote=self.stage(), inicio_at=timezone.now())

    def test_codigo_de_operario_y_de_maquina_unicos_entre_activos(self):
        operator, machine = self.operator("Ana"), self.machine()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Operario.objects.create(codigo=operator.codigo, nombres="Otra")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Maquina.objects.create(codigo=machine.codigo, tipo="PLANA")

    def test_representacion_en_texto(self):
        self.assertEqual(str(self.operator("Ana")), "OPE-0001 Ana")
        self.assertEqual(str(self.machine("OJALADORA")), "MAQ-0001 Ojaladora")

    def test_el_campo_usuario_del_operario_queda_listo_para_enlazar(self):
        user = make_user("operario_usuario@t.co", "PRODUCCION")
        operator = self.operator("Ana")
        self.assertIsNone(operator.usuario)
        operator.usuario = user
        operator.save()
        self.assertEqual(Operario.objects.get(pk=operator.pk).usuario_id, user.pk)
