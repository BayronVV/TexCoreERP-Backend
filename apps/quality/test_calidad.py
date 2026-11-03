"""Control de calidad (HU 6.1 / RF19 y RF20): catálogo de defectos, lotes por inspeccionar e inspecciones."""
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Consecutivo, Proveedor
from apps.inventory.tests import client_for, make_user
from apps.production import catalog as production_catalog
from apps.production.models import RecetaLavado
from apps.production.recepcion_services import create_laundry_reception
from apps.production.remisiones_services import create_laundry_remission
from apps.production.test_modelos import ModelBase

from . import catalog
from .models import Inspeccion, MarraDetalle, TipoDefecto


class QualityBase(ModelBase):
    """Orden de 100 prendas con dos lotes devueltos de lavandería: el 1 de 60 (recibe 55 conformes) y el 2 de 40 (recibe 40)."""

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.order = self.make_order(code="OP-0300", quantity=100)
        self.lot1 = self.make_lot(self.order, number=1, quantity=60)
        self.lot2 = self.make_lot(self.order, number=2, quantity=40)
        self.laundry = Proveedor.objects.create(
            nit="900111222", nit_dv="3", razon_social="Lavandería Aurora", categoria=inventory_catalog.CAT_LAUNDRY,
            ciudad="Itagüí", contacto="Marta", telefono="3100000000",
        )
        RecetaLavado.objects.create(codigo="REC-Q1", nombre="Stone wash", duracion_horas=24)
        self.finisher = client_for(make_user("terminacion@t.co", "TERMINACION"))
        self.viewer = client_for(make_user("gerente@t.co", "GERENTE"))
        self.store = client_for(make_user("almacen@t.co", "ALMACENISTA"))
        self.seller = client_for(make_user("ventas@t.co", "VENDEDOR"))
        self.returned(self.lot1, sent=60, good=55, lost=3, damaged=2)
        self.returned(self.lot2, sent=40, good=40)

    def returned(self, lot, sent, good, lost=0, damaged=0):
        """Envía el lote a lavandería y lo recibe de vuelta (HU 5.1 y 5.2), tal como lo haría el almacén."""
        remission = create_laundry_remission(
            user=self.boss, lavanderia_id=self.laundry.id, fecha_emision=self.today, transportador_nombre="Pedro", vehiculo_placa="ABC123",
            tulas_bultos=1, peso_kg=10, observaciones="",
            lotes_seleccionados=[{"lote_id": lot.id, "cantidad": sent, "receta_id": "REC-Q1", "instrucciones_especiales": ""}],
        )
        row = {
            "remision_lote_id": None, "cantidad_recibida_conforme": good, "cantidad_merma": lost, "cantidad_danada": damaged,
            "costo_unitario_prenda": "30000.00",
        }
        if lost:
            row["motivo_merma"] = "Extravío en tinas"
        if damaged:
            row["tipo_dano"] = "Decoloración irregular"
        from apps.production.models import RemisionLavanderia
        row["remision_lote_id"] = RemisionLavanderia.objects.get(codigo=remission["codigo"]).lotes_detalle.first().id
        create_laundry_reception(user=self.boss, remision_id=RemisionLavanderia.objects.get(codigo=remission["codigo"]).id,
                                 fecha_recepcion=self.today, lotes_recibidos=[row])

    def without_good_garments(self):
        """Lote cuya recepción no trajo prendas conformes (todo se perdió en lavandería)."""
        lot = self.make_lot(self.order, number=3, quantity=10)
        self.returned(lot, sent=10, good=9, lost=1)
        lot.recepciones_lavado.update(cantidad_recibida_conforme=0)
        return lot

    def defect(self, name="Costura floja", fixable=True, active=True):
        return TipoDefecto.objects.create(
            codigo=f"DEF-{TipoDefecto.all_objects.count() + 1:04d}", nombre=name, corregible=fixable, activo=active,
        )

    def inspect(self, lot=None, aptas=50, defects=None, client=None, **extra):
        body = {"lote": (lot or self.lot1).id, "aptas": aptas, "defectos": defects if defects is not None else []}
        body.update(extra)
        return (client or self.finisher).post(reverse("calidad_inspecciones"), body, format="json")


class DefectTests(QualityBase):
    url = "calidad_defectos"

    def create_defect(self, client=None, **body):
        body = {"nombre": "Mancha de grasa", "descripcion": "Mancha permanente", "corregible": False, **body}
        return (client or self.finisher).post(reverse(self.url), body, format="json")

    def test_crea_un_defecto_con_su_codigo(self):
        response = self.create_defect()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["codigo"], body["tipo"], body["activo"]), ("DEF-0001", "INCORREGIBLE", True))
        self.assertEqual(self.create_defect(nombre="Botón flojo", corregible=True).json()["tipo"], "CORREGIBLE")
        self.assertEqual(Consecutivo.objects.get(clave="DEF").ultimo, 2)

    def test_el_nombre_no_se_repite_aunque_cambien_mayusculas_o_espacios(self):
        self.create_defect()
        response = self.create_defect(nombre="  MANCHA   de grasa ")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Ya existe", response.json()["nombre"][0])
        self.assertEqual(Consecutivo.objects.get(clave="DEF").ultimo, 1)  # el rechazo no gasta el consecutivo

    def test_un_defecto_desactivado_sigue_ocupando_su_nombre(self):
        defect = self.defect("Tono desigual", active=False)
        self.assertEqual(self.create_defect(nombre="tono desigual").status_code, 400)
        self.assertEqual(defect.activo, False)

    def test_nombre_demasiado_corto_o_largo(self):
        self.assertEqual(self.create_defect(nombre="ab").status_code, 400)
        self.assertEqual(self.create_defect(nombre="x" * 81).status_code, 400)

    def test_modifica_y_desactiva_sin_borrar(self):
        defect = self.defect("Costura floja")
        url = reverse("calidad_defecto", args=[defect.id])
        response = self.finisher.patch(url, {"nombre": "Costura suelta", "corregible": False, "activo": False}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        defect.refresh_from_db()
        self.assertEqual((defect.nombre, defect.corregible, defect.activo), ("Costura suelta", False, False))
        self.assertEqual(self.finisher.delete(url).status_code, 403)  # no hay DELETE: la API falla cerrada
        self.assertTrue(TipoDefecto.objects.filter(pk=defect.id).exists())

    def test_al_renombrar_no_puede_chocar_con_otro_defecto(self):
        self.defect("Costura floja")
        other = self.defect("Mancha")
        response = self.finisher.patch(reverse("calidad_defecto", args=[other.id]), {"nombre": "costura FLOJA"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_lista_con_filtros(self):
        self.defect("Costura floja")
        self.defect("Mancha", active=False)
        everything = self.viewer.get(reverse(self.url)).json()
        self.assertEqual([row["nombre"] for row in everything], ["Costura floja", "Mancha"])
        only_active = self.viewer.get(reverse(self.url), {"activo": "true"}).json()
        self.assertEqual([row["nombre"] for row in only_active], ["Costura floja"])
        self.assertEqual(len(self.viewer.get(reverse(self.url), {"q": "manc"}).json()), 1)

    def test_permisos_por_rol(self):
        self.assertEqual(self.viewer.get(reverse(self.url)).status_code, 200)  # el Gerente consulta
        self.assertEqual(self.create_defect(client=self.viewer).status_code, 403)  # pero no modifica
        self.assertEqual(self.create_defect(client=self.store).status_code, 403)
        self.assertEqual(self.store.get(reverse(self.url)).status_code, 403)
        self.assertEqual(self.create_defect(client=self.boss_client()).status_code, 201)  # el Jefe de Producción define criterios

    def boss_client(self):
        return self.api

    def test_el_nombre_activo_es_unico_en_la_base(self):
        self.defect("Costura floja")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.defect("COSTURA FLOJA")


class PendingTests(QualityBase):
    def pending(self, client=None):
        response = (client or self.finisher).get(reverse("calidad_pendientes"))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_lista_los_lotes_devueltos_con_lo_recibido_conforme(self):
        rows = {row["codigo"]: row for row in self.pending()}
        self.assertEqual(set(rows), {self.lot1.codigo, self.lot2.codigo})
        first = rows[self.lot1.codigo]
        self.assertEqual(first["cantidad_recibida"], 55)  # lo recibido conforme, no lo enviado
        self.assertEqual((first["orden_codigo"], first["lavanderia_nombre"]), ("OP-0300", "Lavandería Aurora"))
        self.assertTrue(first["recepcion_codigo"])

    def test_un_lote_sin_recepcion_de_lavanderia_no_aparece(self):
        lot3 = self.make_lot(self.order, number=3, quantity=10)
        self.assertNotIn(lot3.codigo, [row["codigo"] for row in self.pending()])

    def test_un_lote_inspeccionado_sale_de_la_lista(self):
        self.assertEqual(self.inspect(self.lot2, aptas=40).status_code, 201)
        self.assertEqual([row["codigo"] for row in self.pending()], [self.lot1.codigo])

    def test_un_lote_sin_prendas_conformes_no_aparece(self):
        lot3 = self.without_good_garments()
        self.assertNotIn(lot3.codigo, [row["codigo"] for row in self.pending()])

    def test_los_lotes_de_una_orden_anulada_no_aparecen(self):
        out = self.order.orden_salida
        out.estado = inventory_catalog.STATUS_CANCELLED
        out.save()
        self.assertEqual(self.pending(), [])

    def test_solo_los_lotes_en_planta(self):
        self.lot1.estado_inventario = production_catalog.LOT_INV_IN_TRANSIT
        self.lot1.save()
        self.assertEqual([row["codigo"] for row in self.pending()], [self.lot2.codigo])

    def test_permisos(self):
        self.assertEqual(self.store.get(reverse("calidad_pendientes")).status_code, 403)
        self.assertEqual(self.pending(self.viewer)[0]["codigo"], self.lot1.codigo)

    def test_no_hace_consultas_por_fila(self):
        self.pending()  # la primera llamada carga los permisos del usuario
        with CaptureQueriesContext(connection) as small:
            self.pending()
        for number in range(3, 6):
            lot = self.make_lot(self.order, number=number, quantity=5)
            self.returned(lot, sent=5, good=5)
        with CaptureQueriesContext(connection) as big:
            rows = self.pending()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(big), len(small))


class InspectionTests(QualityBase):
    def setUp(self):
        super().setUp()
        self.seam = self.defect("Costura floja", fixable=True)
        self.stain = self.defect("Mancha permanente", fixable=False)

    def test_registra_la_inspeccion_con_su_desglose(self):
        response = self.inspect(aptas=50, defects=[
            {"defecto": self.seam.id, "cantidad": 3, "nota": "Pretina"}, {"defecto": self.stain.id, "cantidad": 2},
        ], observaciones="Revisado al 100 %")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["codigo"], body["lote_codigo"], body["orden_codigo"]), ("INS-0001", self.lot1.codigo, "OP-0300"))
        self.assertEqual((body["cantidad_recibida"], body["aptas"], body["marras"], body["porcentaje_marras"]), (55, 50, 5, "9.1"))
        self.assertEqual(body["lavanderia_nombre"], "Lavandería Aurora")
        self.assertEqual([(row["defecto_nombre"], row["cantidad"], row["tipo"]) for row in body["detalle"]],
                         [("Costura floja", 3, "CORREGIBLE"), ("Mancha permanente", 2, "INCORREGIBLE")])
        self.assertEqual(body["detalle"][0]["nota"], "Pretina")
        self.assertEqual(Inspeccion.objects.count(), 1)

    def test_todas_aptas_es_valido(self):
        body = self.inspect(self.lot2, aptas=40).json()
        self.assertEqual((body["aptas"], body["marras"], body["detalle"]), (40, 0, []))

    def test_la_suma_debe_ser_exactamente_lo_recibido(self):
        for aptas, defects in ((50, [{"defecto": self.seam.id, "cantidad": 4}]), (52, [{"defecto": self.seam.id, "cantidad": 4}]),
                               (54, [])):
            response = self.inspect(aptas=aptas, defects=defects)
            self.assertEqual(response.status_code, 400, (aptas, defects))
            self.assertIn("suman", response.json()["aptas"][0])
        self.assertEqual(self.inspect(aptas=50, defects=[{"defecto": self.seam.id, "cantidad": 4}]).json()["aptas"][0].split(": ")[1], "falta 1.")
        self.assertEqual(Inspeccion.objects.count(), 0)
        self.assertFalse(Consecutivo.objects.filter(clave="INS").exists())  # los rechazos no gastan el consecutivo

    def test_el_mensaje_dice_cuanto_falta_o_sobra(self):
        self.assertIn("faltan 5", self.inspect(aptas=50).json()["aptas"][0])
        self.assertIn("sobran 2", self.inspect(aptas=57).json()["aptas"][0])

    def test_un_lote_se_inspecciona_una_sola_vez(self):
        self.assertEqual(self.inspect(aptas=55).status_code, 201)
        response = self.inspect(aptas=55)
        self.assertEqual(response.status_code, 409)
        self.assertIn("ya fue inspeccionado", response.json()["lote"][0])
        self.assertEqual(Inspeccion.objects.count(), 1)

    def test_la_base_tambien_impide_dos_inspecciones_ni_sumas_que_no_cuadran(self):
        self.inspect(aptas=55)
        existing = Inspeccion.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Inspeccion.objects.create(
                codigo="INS-9999", lote=self.lot1, recepcion_lote=existing.recepcion_lote, cantidad_recibida=55, aptas=55,
                marras=0, fecha=self.today,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Inspeccion.objects.create(
                codigo="INS-9998", lote=self.lot2, recepcion_lote=existing.recepcion_lote, cantidad_recibida=40, aptas=30,
                marras=5, fecha=self.today,
            )

    def test_aptas_y_cantidades_deben_ser_enteros(self):
        for aptas in (-1, 5.5, "abc", True, None):
            self.assertEqual(self.inspect(aptas=aptas).status_code, 400, aptas)
        for amount in (0, -2, 1.5, "x"):
            response = self.inspect(aptas=50, defects=[{"defecto": self.seam.id, "cantidad": amount}])
            self.assertEqual(response.status_code, 400, amount)

    def test_el_defecto_debe_existir_estar_activo_y_no_repetirse(self):
        off = self.defect("Desactivado", active=False)
        self.assertEqual(self.inspect(aptas=50, defects=[{"defecto": 9999, "cantidad": 5}]).status_code, 400)
        response = self.inspect(aptas=50, defects=[{"defecto": off.id, "cantidad": 5}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("desactivado", response.json()["defectos"][0])
        response = self.inspect(aptas=50, defects=[{"defecto": self.seam.id, "cantidad": 2}, {"defecto": self.seam.id, "cantidad": 3}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("repetirse", response.json()["defectos"][0])

    def test_lote_inexistente_sin_recepcion_o_de_orden_anulada(self):
        self.assertEqual(self.inspect(aptas=1, lote=99999).status_code, 400)
        lot3 = self.make_lot(self.order, number=3, quantity=10)
        response = self.inspect(lot3, aptas=10)
        self.assertEqual(response.status_code, 400)
        self.assertIn("recepción de lavandería", response.json()["lote"][0])
        out = self.order.orden_salida
        out.estado = inventory_catalog.STATUS_CANCELLED
        out.save()
        self.assertIn("anulada", self.inspect(aptas=55).json()["lote"][0])

    def test_un_lote_sin_prendas_conformes_no_se_inspecciona(self):
        lot3 = self.without_good_garments()
        response = self.inspect(lot3, aptas=0)
        self.assertEqual(response.status_code, 400)
        self.assertIn("nada que inspeccionar", response.json()["lote"][0])

    def test_la_inspeccion_guarda_lo_recibido_y_no_cambia_con_el_defecto(self):
        self.inspect(aptas=50, defects=[{"defecto": self.seam.id, "cantidad": 5}])
        self.seam.nombre, self.seam.corregible = "Renombrado", False
        self.seam.save()
        detail = self.viewer.get(reverse("calidad_inspeccion", args=[Inspeccion.objects.get().id])).json()
        self.assertEqual((detail["detalle"][0]["defecto_nombre"], detail["detalle"][0]["tipo"]), ("Costura floja", "CORREGIBLE"))

    def test_las_inspecciones_no_se_editan_ni_se_borran(self):
        self.inspect(aptas=55)
        url = reverse("calidad_inspeccion", args=[Inspeccion.objects.get().id])
        for method in ("put", "patch", "delete"):
            self.assertIn(getattr(self.finisher, method)(url).status_code, (403, 405), method)
        self.assertEqual(Inspeccion.objects.count(), 1)

    def test_permisos_por_rol(self):
        self.assertEqual(self.inspect(aptas=55, client=self.viewer).status_code, 403)  # el Gerente solo consulta
        self.assertEqual(self.inspect(aptas=55, client=self.store).status_code, 403)
        self.assertEqual(self.inspect(aptas=55, client=self.seller).status_code, 403)
        self.assertEqual(self.inspect(aptas=55, client=self.api).status_code, 201)  # el Jefe de Producción también inspecciona
        self.assertEqual(self.viewer.get(reverse("calidad_inspecciones")).status_code, 200)
        self.assertEqual(self.store.get(reverse("calidad_inspecciones")).status_code, 403)

    def test_la_fecha_no_puede_ser_futura(self):
        future = (self.today + timezone.timedelta(days=1)).isoformat()
        self.assertEqual(self.inspect(aptas=55, fecha=future).status_code, 400)

    def test_lista_con_filtros_y_sin_consultas_por_fila(self):
        self.inspect(aptas=55)
        self.inspect(self.lot2, aptas=38, defects=[{"defecto": self.seam.id, "cantidad": 2}])
        url = reverse("calidad_inspecciones")
        self.assertEqual(len(self.viewer.get(url).json()), 2)
        self.assertEqual(len(self.viewer.get(url, {"lote": self.lot2.id}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"orden": self.order.id}).json()), 2)
        self.assertEqual(len(self.viewer.get(url, {"q": "INS-0002"}).json()), 1)
        self.assertEqual(len(self.viewer.get(url, {"desde": (self.today + timezone.timedelta(days=1)).isoformat()}).json()), 0)
        self.assertEqual(self.viewer.get(url, {"lote": "abc"}).status_code, 400)
        with CaptureQueriesContext(connection) as queries:
            self.viewer.get(url)
        self.assertLessEqual(len(queries), 8)

    def test_el_detalle_de_una_inspeccion_inexistente_responde_404(self):
        self.assertEqual(self.viewer.get(reverse("calidad_inspeccion", args=[9999])).status_code, 404)

    def test_los_detalles_se_guardan_con_la_inspeccion(self):
        self.inspect(aptas=50, defects=[{"defecto": self.seam.id, "cantidad": 5}])
        self.assertEqual(MarraDetalle.objects.count(), 1)
        self.assertEqual(MarraDetalle.objects.get().inspeccion.marras, 5)


class CatalogTests(QualityBase):
    def test_permisos_declarados(self):
        self.assertEqual((catalog.QUALITY_VIEW, catalog.QUALITY_MANAGE), ("calidad.ver", "calidad.gestionar"))
