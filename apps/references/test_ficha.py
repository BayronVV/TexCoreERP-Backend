"""Ficha técnica de consumo por unidad (HU 3.2): materiales, consumo contra el stock, PDF y permisos."""
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import OrdenSalida, Producto
from apps.inventory.tests import client_for, make_user

from . import catalog
from .models import FichaLinea, FichaTecnica, Referencia
from .tests import PNG, ReferenceBase, image

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def pdf(content=PDF, name="ficha-extensa.pdf"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class FichaBase(ReferenceBase):
    def setUp(self):
        super().setUp()
        self.tela = self.material("Denim rígido 14 oz", inventory_catalog.CAT_FABRIC, "m", stock="500")
        self.hilo = self.material("Hilo poliéster negro", inventory_catalog.CAT_THREAD, "kg", stock="10")
        self.cierre = self.material("Cierre metálico 18 cm", inventory_catalog.CAT_ZIPPER, "unidad", stock="300")
        self.boton = self.material("Botón 17 mm", inventory_catalog.CAT_BUTTON, "unidad", stock="200")
        self.ref = self.new()

    def material(self, name, category, unit, stock="0"):
        return Producto.objects.create(
            codigo=f"M-{Producto.all_objects.count() + 1}", nombre=name, categoria=category,
            tipo=inventory_catalog.CATEGORIES[category]["tipo"], unidad=unit, stock_actual=Decimal(stock),
        )

    def url(self, reference=None):
        return reverse("referencia_ficha", args=[(reference or self.ref)["id"]])

    def line(self, product, quantity, waste="0", notes=""):
        return {"producto": product.id, "cantidad": quantity, "merma": waste, "observaciones": notes}

    def put(self, lines=None, reference=None, client=None, **extra):
        body = {"lavado": "ENZIMATICO", "notas": "Costura doble", "lineas": lines if lines is not None else [
            self.line(self.tela, "1.5", "10"), self.line(self.cierre, "1"), self.line(self.boton, "1"),
        ]}
        body.update(extra)
        return (client or self.api).put(self.url(reference), body, format="json")

    def saved(self, **kwargs):
        response = self.put(**kwargs)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class FichaSaveTests(FichaBase):
    def test_referencia_sin_ficha(self):
        body = self.api.get(self.url()).json()
        self.assertFalse(body["existe"])
        self.assertEqual((body["lineas"], body["documento"]), ([], None))
        self.assertEqual(body["referencia"]["codigo"], self.ref["codigo"])

    def test_guarda_la_ficha_con_sus_materiales(self):
        body = self.saved()
        self.assertTrue(body["existe"])
        self.assertEqual((body["lavado"], body["lavado_nombre"]), ("ENZIMATICO", "Lavado enzimático"))
        self.assertEqual(body["notas"], "Costura doble")
        self.assertEqual(body["actualizado_por_nombre"], "produccion@t.co")
        by_name = {line["nombre"]: line for line in body["lineas"]}
        tela = by_name["Denim rígido 14 oz"]
        self.assertEqual((Decimal(tela["cantidad"]), Decimal(tela["merma"])), (Decimal("1.5"), Decimal("10")))
        self.assertEqual(Decimal(tela["consumo_bruto"]), Decimal("1.65"))  # 1,5 × 1,10
        self.assertEqual(tela["unidad"], "m")
        self.assertEqual(len(body["lineas"]), 3)

    def test_aparece_al_consultar_y_marca_la_referencia(self):
        self.saved()
        self.assertEqual(len(self.api.get(self.url()).json()["lineas"]), 3)
        listed = self.api.get(reverse("referencias")).json()
        self.assertEqual({r["id"]: r["tiene_ficha"] for r in listed}, {self.ref["id"]: True})
        self.assertTrue(self.api.get(reverse("referencia", args=[self.ref["id"]])).json()["tiene_ficha"])

    def test_la_referencia_sin_ficha_no_la_marca(self):
        self.assertFalse(self.api.get(reverse("referencia", args=[self.ref["id"]])).json()["tiene_ficha"])

    def test_guardar_dos_veces_reemplaza_la_ficha(self):
        first = self.saved()
        kept = next(line["id"] for line in first["lineas"] if line["nombre"] == "Denim rígido 14 oz")
        second = self.saved(
            lines=[self.line(self.tela, "1.6", "8", "Corte"), self.line(self.hilo, "0.02", "10")],
            lavado="", notas="",
        )
        by_name = {line["nombre"]: line for line in second["lineas"]}
        self.assertEqual(set(by_name), {"Denim rígido 14 oz", "Hilo poliéster negro"})
        self.assertEqual(by_name["Denim rígido 14 oz"]["id"], kept)  # el material que sigue no se recrea
        self.assertEqual(Decimal(by_name["Denim rígido 14 oz"]["cantidad"]), Decimal("1.6"))
        self.assertEqual(by_name["Denim rígido 14 oz"]["observaciones"], "Corte")
        self.assertEqual((second["lavado"], second["notas"]), ("", ""))
        self.assertEqual(FichaTecnica.objects.count(), 1)
        self.assertEqual(FichaLinea.all_objects.filter(deleted_at__isnull=False).count(), 2)  # cierre y botón archivados

    def test_un_material_quitado_se_puede_volver_a_agregar(self):
        self.saved()
        self.saved(lines=[self.line(self.tela, "1.5")])
        again = self.saved(lines=[self.line(self.tela, "1.5"), self.line(self.cierre, "1")])
        self.assertEqual(len(again["lineas"]), 2)

    def test_el_lavado_es_opcional(self):
        body = self.api.put(self.url(), {"lineas": [self.line(self.tela, "1.5")]}, format="json").json()
        self.assertEqual(body["lavado"], "")

    def test_acepta_numeros_y_cadenas(self):
        body = self.saved(lines=[{"producto": self.tela.id, "cantidad": 1.5}, {"producto": self.cierre.id, "cantidad": "1"}])
        self.assertEqual(len(body["lineas"]), 2)

    def test_las_observaciones_se_limpian(self):
        body = self.saved(lines=[self.line(self.tela, "1.5", notes="  Bolsillo   trasero ")])
        self.assertEqual(body["lineas"][0]["observaciones"], "Bolsillo trasero")


class FichaValidationTests(FichaBase):
    def assertRejected(self, lines, field="lineas", **extra):
        response = self.put(lines=lines, **extra)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(field, response.json())
        self.assertFalse(FichaTecnica.objects.exists(), "una ficha inválida no se guarda")
        return response.json()[field][0]

    def test_exige_al_menos_un_material(self):
        self.assertIn("al menos un material", self.assertRejected([]))

    def test_no_repite_materiales(self):
        self.assertIn("dos veces", self.assertRejected([self.line(self.tela, "1"), self.line(self.tela, "2")]))

    def test_el_material_debe_existir(self):
        self.assertIn("no existe", self.assertRejected([{"producto": 99999, "cantidad": "1"}]))

    def test_no_acepta_un_material_archivado(self):
        self.tela.delete()
        self.assertIn("no existe", self.assertRejected([self.line(self.tela, "1")]))

    def test_solo_materias_primas_e_insumos(self):
        generico = self.material("Pantalón genérico", inventory_catalog.CAT_GENERIC, "unidad")
        terminado = self.material("Jean terminado", inventory_catalog.CAT_FINISHED, "unidad")
        for product in (generico, terminado):
            self.assertIn("solo lleva materiales", self.assertRejected([self.line(product, "1")]))

    def test_cantidad_invalida(self):
        for bad in ("0", "-1", "abc", "", None, "1001", "NaN"):
            response = self.put(lines=[{"producto": self.tela.id, "cantidad": bad}])
            self.assertEqual(response.status_code, 400, bad)

    def test_cantidad_con_mas_de_tres_decimales(self):
        self.assertIn("3 decimales", self.assertRejected([self.line(self.tela, "1.2345")]))

    def test_unidades_enteras_no_admiten_decimales(self):
        self.assertIn("debe ser entera", self.assertRejected([self.line(self.cierre, "1.5")]))
        self.assertEqual(self.put(lines=[self.line(self.cierre, "2")]).status_code, 200)

    def test_merma_fuera_de_rango_o_con_muchos_decimales(self):
        for bad in ("-1", "50.01", "100"):
            self.assertIn("0 a 50", self.assertRejected([self.line(self.tela, "1", bad)]), bad)
        self.assertIn("2 decimales", self.assertRejected([self.line(self.tela, "1", "5.555")]))

    def test_las_piezas_enteras_no_llevan_merma(self):
        self.assertIn("no lleva merma", self.assertRejected([self.line(self.boton, "1", "5")]))

    def test_lavado_invalido(self):
        response = self.put(lavado="PLANCHADO")
        self.assertEqual(response.status_code, 400)
        self.assertIn("lavado", response.json())

    def test_limite_de_materiales(self):
        products = [self.material(f"Material {n}", inventory_catalog.CAT_OTHER, "unidad")
                    for n in range(catalog.MAX_FICHA_LINES + 1)]
        too_many = [self.line(p, "1") for p in products]
        self.assertIn("máximo", self.assertRejected(too_many))
        self.assertEqual(self.put(lines=too_many[:-1]).status_code, 200)

    def test_una_ficha_invalida_no_modifica_la_vigente(self):
        self.saved()
        response = self.put(lines=[self.line(self.tela, "9"), self.line(self.cierre, "1.5")], notas="Cambiada")
        self.assertEqual(response.status_code, 400)
        body = self.api.get(self.url()).json()
        self.assertEqual(body["notas"], "Costura doble")
        self.assertEqual(len(body["lineas"]), 3)
        self.assertEqual(Decimal(next(l for l in body["lineas"] if l["producto"] == self.tela.id)["cantidad"]), Decimal("1.5"))

    def test_referencia_inexistente(self):
        self.assertEqual(self.api.put(reverse("referencia_ficha", args=[999]), {"lineas": []}, format="json").status_code, 404)
        self.assertEqual(self.api.get(reverse("referencia_ficha", args=[999])).status_code, 404)

    def test_falta_la_lista_de_lineas(self):
        self.assertEqual(self.api.put(self.url(), {"lavado": "OTRO"}, format="json").status_code, 400)


class FichaDeleteTests(FichaBase):
    def test_quita_la_ficha_con_sus_materiales(self):
        self.saved()
        self.assertEqual(self.api.delete(self.url()).status_code, 204)
        self.assertFalse(FichaTecnica.objects.exists())
        self.assertFalse(FichaLinea.objects.exists())
        self.assertFalse(self.api.get(self.url()).json()["existe"])
        self.assertEqual(self.saved()["existe"], True)  # se puede volver a crear

    def test_sin_ficha_no_hay_nada_que_quitar(self):
        self.assertEqual(self.api.delete(self.url()).status_code, 400)

    def open_order(self):
        referencia = Referencia.objects.get(pk=self.ref["id"])
        resultado = self.material("Pantalón genérico", inventory_catalog.CAT_GENERIC, "unidad")
        return OrdenSalida.objects.create(
            codigo="OP-0001", tipo="PRODUCCION", fecha_salida="2026-10-01", responsable="Marta",
            referencia=referencia, ficha_tecnica=referencia.codigo, producto_resultado=resultado,
        )

    def test_no_se_quita_con_ordenes_en_proceso(self):
        self.saved()
        order = self.open_order()
        response = self.api.delete(self.url())
        self.assertEqual(response.status_code, 400)
        self.assertIn("órdenes en proceso", response.json()["detail"][0])
        order.estado = "COMPLETADA"
        order.save()
        self.assertEqual(self.api.delete(self.url()).status_code, 204)

    def test_archivar_la_referencia_archiva_su_ficha(self):
        self.saved()
        self.assertEqual(self.api.delete(reverse("referencia", args=[self.ref["id"]])).status_code, 204)
        self.assertFalse(FichaTecnica.objects.exists())
        self.assertFalse(FichaLinea.objects.exists())

    def test_no_se_archiva_con_ordenes_en_proceso(self):
        self.saved()
        self.open_order()
        response = self.api.delete(reverse("referencia", args=[self.ref["id"]]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("órdenes en proceso", response.json()["estado"][0])
        self.assertTrue(Referencia.objects.filter(pk=self.ref["id"]).exists())


class ConsumoTests(FichaBase):
    def setUp(self):
        super().setUp()
        self.activate(self.ref["id"])
        self.saved()  # tela 1,5 m (+10 %), cierre 1, botón 1

    def consumo(self, quantity, client=None, reference=None):
        return (client or self.api).get(
            reverse("ficha_consumo", args=[(reference or self.ref)["id"]]), {"cantidad": quantity}
        )

    def rows(self, quantity):
        response = self.consumo(quantity)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json(), {row["nombre"]: row for row in response.json()["lineas"]}

    def test_calcula_el_consumo_con_la_merma_aplicada_una_sola_vez(self):
        body, rows = self.rows(100)
        self.assertEqual(Decimal(rows["Denim rígido 14 oz"]["requerido"]), Decimal("165.00"))  # 1,5 × 1,10 × 100
        self.assertEqual(Decimal(rows["Cierre metálico 18 cm"]["requerido"]), Decimal("100"))
        self.assertEqual(body["cantidad"], 100)
        self.assertEqual(body["referencia"]["codigo"], self.ref["codigo"])

    def test_redondea_hacia_arriba_y_solo_al_final(self):
        self.saved(lines=[self.line(self.tela, "1.333", "10"), self.line(self.hilo, "0.001"), self.line(self.cierre, "3")])
        _, rows = self.rows(7)
        # 1,333 × 1,10 × 7 = 10,2641 -> 10,27 (si se redondeara por prenda daría 1,47 × 7 = 10,29)
        self.assertEqual(Decimal(rows["Denim rígido 14 oz"]["requerido"]), Decimal("10.27"))
        self.assertEqual(Decimal(rows["Hilo poliéster negro"]["requerido"]), Decimal("0.01"))  # 0,007 -> 0,01
        self.assertEqual(Decimal(rows["Cierre metálico 18 cm"]["requerido"]), Decimal("21"))

    def test_las_unidades_enteras_siempre_dan_enteros(self):
        for quantity in (1, 7, 333):
            _, rows = self.rows(quantity)
            for name in ("Cierre metálico 18 cm", "Botón 17 mm"):
                value = Decimal(rows[name]["requerido"])
                self.assertEqual(value, value.to_integral_value(), name)

    def test_cruza_con_el_stock_y_marca_los_faltantes(self):
        body, rows = self.rows(400)  # tela necesaria: 660 y hay 500; cierres 400 y hay 300; botones 400 y hay 200
        self.assertFalse(body["viable"])
        self.assertEqual({row["nombre"] for row in body["faltantes"]},
                         {"Denim rígido 14 oz", "Cierre metálico 18 cm", "Botón 17 mm"})
        tela = rows["Denim rígido 14 oz"]
        self.assertEqual((Decimal(tela["disponible"]), Decimal(tela["falta"]), tela["suficiente"]),
                         (Decimal("500"), Decimal("160.00"), False))

    def test_viable_cuando_alcanza_justo(self):
        body, rows = self.rows(200)  # botones: 200 pedidos y 200 disponibles; tela 330 de 500; cierres 200 de 300
        self.assertTrue(body["viable"])
        self.assertEqual(body["faltantes"], [])
        self.assertEqual(Decimal(rows["Botón 17 mm"]["falta"]), Decimal("0"))
        self.assertTrue(rows["Botón 17 mm"]["suficiente"])

    def test_cantidad_invalida(self):
        for bad in ("0", "-5", "abc", "1.5", "", "100001"):
            self.assertEqual(self.consumo(bad).status_code, 400, bad)
        self.assertEqual(self.api.get(reverse("ficha_consumo", args=[self.ref["id"]])).status_code, 400)
        self.assertEqual(self.consumo(catalog.MAX_GARMENTS).status_code, 200)

    def test_solo_referencias_activas_y_con_ficha(self):
        borrador = self.new(nombre="Borrador")
        self.assertEqual(self.consumo(10, reference=borrador).status_code, 404)
        sin_ficha = self.new(nombre="Sin ficha")
        self.activate(sin_ficha["id"])
        response = self.consumo(10, reference=sin_ficha)
        self.assertEqual(response.status_code, 400)
        self.assertIn("ficha técnica", response.json()["referencia"][0])
        self.assertEqual(self.consumo(10, reference={"id": 9999}).status_code, 404)

    def test_el_numero_de_consultas_no_crece_con_los_materiales(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(self.consumo(10).status_code, 200)
            return len(queries)

        few = count()
        extra = [self.line(self.material(f"Extra {n}", inventory_catalog.CAT_OTHER, "unidad"), "1") for n in range(15)]
        self.saved(lines=[self.line(self.tela, "1.5", "10"), *extra])
        self.assertEqual(count(), few)

    def test_no_toca_el_stock(self):
        self.consumo(400)
        self.tela.refresh_from_db()
        self.assertEqual(self.tela.stock_actual, Decimal("500"))

    def test_el_almacenista_consulta_el_consumo_pero_no_edita_la_ficha(self):
        store = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        self.assertEqual(self.consumo(10, client=store).status_code, 200)
        self.assertEqual(store.get(self.url()).status_code, 403)  # la ficha es de Producción
        self.assertEqual(self.put(client=store).status_code, 403)

    def test_quien_no_ve_inventario_no_consulta_el_consumo(self):
        finisher = client_for(make_user("terminacion@t.co", "TERMINACION"))
        self.assertEqual(self.consumo(10, client=finisher).status_code, 403)
        self.assertEqual(APIClient().get(reverse("ficha_consumo", args=[self.ref["id"]]), {"cantidad": 1}).status_code, 401)


class ReferenciasParaOrdenTests(FichaBase):
    def names(self, client=None):
        response = (client or self.api).get(reverse("fichas_para_orden"))
        self.assertEqual(response.status_code, 200, response.content)
        return {row["nombre"]: row for row in response.json()}

    def test_solo_lista_las_referencias_activas(self):
        self.activate(self.ref["id"])
        self.new(nombre="Borrador")
        descontinuada = self.new(nombre="Vieja")
        self.activate(descontinuada["id"])
        self.set_state(descontinuada["id"], catalog.DISCONTINUED)
        self.assertEqual(set(self.names()), {"Skinny 5 bolsillos"})

    def test_indica_si_tiene_ficha_y_cuantos_materiales(self):
        self.activate(self.ref["id"])
        con = self.names()["Skinny 5 bolsillos"]
        self.assertEqual((con["tiene_ficha"], con["materiales"], con["lavado"]), (False, 0, ""))
        self.saved()
        con = self.names()["Skinny 5 bolsillos"]
        self.assertEqual((con["tiene_ficha"], con["materiales"]), (True, 3))
        self.assertEqual((con["lavado"], con["lavado_nombre"]), ("ENZIMATICO", "Lavado enzimático"))
        self.assertEqual(con["ajuste_nombre"], "Skinny")

    def test_no_cuenta_materiales_archivados(self):
        self.activate(self.ref["id"])
        self.saved()
        self.saved(lines=[self.line(self.tela, "1.5")])
        self.assertEqual(self.names()["Skinny 5 bolsillos"]["materiales"], 1)

    def test_lo_ve_quien_tiene_inventario(self):
        self.activate(self.ref["id"])
        store = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        self.assertIn("Skinny 5 bolsillos", self.names(client=store))
        finisher = client_for(make_user("terminacion@t.co", "TERMINACION"))
        self.assertEqual(finisher.get(reverse("fichas_para_orden")).status_code, 403)


class FichaPermissionTests(FichaBase):
    def test_roles_de_solo_lectura_no_modifican(self):
        self.saved()
        manager = client_for(make_user("gerente@t.co", "GERENTE"))  # fichas_tecnicas.ver
        self.assertEqual(manager.get(self.url()).status_code, 200)
        self.assertEqual(self.put(client=manager).status_code, 403)
        self.assertEqual(manager.delete(self.url()).status_code, 403)
        self.assertEqual(manager.post(reverse("referencia_ficha_documento", args=[self.ref["id"]]), {"documento": pdf()},
                                      format="multipart").status_code, 403)
        self.assertEqual(len(self.api.get(self.url()).json()["lineas"]), 3)

    def test_sin_el_permiso_no_se_ve(self):
        seller = client_for(make_user("ventas@t.co", "VENDEDOR"))
        self.assertEqual(seller.get(self.url()).status_code, 403)
        self.assertEqual(APIClient().get(self.url()).status_code, 401)

    def test_el_administrador_puede_todo(self):
        admin = client_for(make_user("admin@t.co", "ADMIN"))
        self.assertEqual(self.put(client=admin).status_code, 200)


class FichaDocumentoTests(FichaBase):
    def doc_url(self):
        return reverse("referencia_ficha_documento", args=[self.ref["id"]])

    def upload(self, file=None, client=None, reference=None):
        url = reverse("referencia_ficha_documento", args=[(reference or self.ref)["id"]])
        return (client or self.api).post(url, {"documento": file or pdf()}, format="multipart")

    def test_exige_que_la_ficha_exista(self):
        response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertIn("Guarda primero la ficha", response.json()["documento"][0])

    def test_adjunta_el_pdf(self):
        self.saved()
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.content)
        doc = response.json()["documento"]
        self.assertEqual((doc["nombre"], doc["tamano"], doc["version"]), ("ficha-extensa.pdf", len(PDF), 1))
        self.assertEqual(self.api.get(self.url()).json()["documento"]["nombre"], "ficha-extensa.pdf")
        self.assertEqual(len(response.json()["lineas"]), 3)  # el PDF no toca los materiales

    def test_descarga_con_etag(self):
        self.saved()
        self.upload()
        response = self.api.get(self.doc_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content, PDF)
        self.assertIn(f'{self.ref["codigo"]}-ficha-tecnica.pdf', response["Content-Disposition"])
        self.assertEqual(self.api.get(self.doc_url(), HTTP_IF_NONE_MATCH=response["ETag"]).status_code, 304)

    def test_reemplazar_sube_la_version_y_cambia_el_etag(self):
        self.saved()
        self.upload()
        first = self.api.get(self.doc_url())["ETag"]
        other = PDF + b"\n% segunda version"
        body = self.upload(pdf(other, "nueva.pdf")).json()
        self.assertEqual((body["documento"]["nombre"], body["documento"]["version"]), ("nueva.pdf", 2))
        second = self.api.get(self.doc_url())
        self.assertNotEqual(second["ETag"], first)
        self.assertEqual(second.content, other)

    def test_solo_acepta_pdf_por_contenido(self):
        self.saved()
        for content, name in ((PNG, "falso.pdf"), (b"texto plano", "nota.pdf"), (b"", "vacio.pdf")):
            response = self.upload(pdf(content, name))
            self.assertEqual(response.status_code, 400, name)
        self.assertIn("PDF", self.upload(pdf(PNG, "falso.pdf")).json()["documento"][0])
        self.assertIsNone(self.api.get(self.url()).json()["documento"])

    def test_rechaza_un_pdf_muy_pesado(self):
        self.saved()
        with mock.patch.object(catalog, "DOCUMENT_MAX_BYTES", 10):
            response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertIn("pesa más de", response.json()["documento"][0])

    def test_sin_archivo(self):
        self.saved()
        response = self.api.post(self.doc_url(), {}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("documento", response.json())

    def test_quitar_el_pdf(self):
        self.saved()
        self.upload()
        body = self.api.delete(self.doc_url()).json()
        self.assertIsNone(body["documento"])
        self.assertEqual(self.api.get(self.doc_url()).status_code, 404)
        self.assertEqual(self.api.delete(self.doc_url()).status_code, 400)  # ya no hay nada que quitar
        self.assertEqual(len(body["lineas"]), 3)

    def test_sin_pdf_la_descarga_es_404(self):
        self.assertEqual(self.api.get(self.doc_url()).status_code, 404)
        self.saved()
        self.assertEqual(self.api.get(self.doc_url()).status_code, 404)

    def test_guardar_la_ficha_conserva_el_pdf(self):
        self.saved()
        self.upload()
        self.saved(lines=[self.line(self.tela, "2")])
        self.assertEqual(self.api.get(self.url()).json()["documento"]["version"], 1)
        self.assertEqual(self.api.get(self.doc_url()).content, PDF)

    def test_quitar_la_ficha_borra_su_pdf(self):
        self.saved()
        self.upload()
        self.api.delete(self.url())
        self.assertEqual(self.api.get(self.doc_url()).status_code, 404)
        self.assertIsNone(self.saved()["documento"])  # una ficha nueva empieza sin PDF

    def test_el_pdf_no_se_carga_al_listar(self):
        self.saved()
        self.upload()
        ficha = FichaTecnica.objects.get()
        self.assertIn("documento", ficha.get_deferred_fields())
        self.assertTrue(ficha.tiene_documento)

    def test_las_imagenes_siguen_funcionando(self):
        self.saved()
        self.assertEqual(self.upload_image().status_code, 201)

    def upload_image(self):
        return self.client_upload(self.ref["id"], image())

    def client_upload(self, reference_id, file):
        return self.api.post(
            reverse("referencia_imagenes", args=[reference_id]), {"imagen": [file]}, format="multipart"
        )
