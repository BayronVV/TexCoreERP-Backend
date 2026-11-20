import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.testing import PNG, client_for, make_user, today
from apps.references import catalog as reference_catalog
from apps.references.models import FichaLinea, FichaTecnica, Referencia

from . import catalog
from .models import Consecutivo, Movimiento, OrdenSalida, Producto, Proveedor

TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class InventoryBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.storekeeper = make_user("almacen@t.co", "ALMACENISTA")
        self.api = client_for(self.storekeeper)
        self.supplier = Proveedor.objects.create(
            nit="890900001", nit_dv="4", razon_social="Textiles SA", categoria=catalog.CAT_FABRIC
        )
        self.tela = self.product("Tela denim", catalog.CAT_FABRIC, "m", stock="1000", minimo="200")
        self.cierre = self.product("Cierre", catalog.CAT_ZIPPER, "unidad", stock="500", minimo="100")
        self.boton = self.product("Botón", catalog.CAT_BUTTON, "unidad", stock="300")
        self.generico = self.product("Pantalón genérico", catalog.CAT_GENERIC, "unidad")
        self.skinny = self.product("MOD-SKINNY 5 BOTONES V2", catalog.CAT_FINISHED, "unidad")
        # Referencia activa con ficha técnica: las órdenes de salida se hacen sobre una referencia.
        Consecutivo.objects.create(clave=reference_catalog.CODE_PREFIX, ultimo=1)  # REF-0001 ya está tomado
        self.referencia = Referencia.objects.create(
            codigo="REF-0001", nombre="Skinny 5 bolsillos", ajuste="SKINNY", estado=reference_catalog.ACTIVE
        )
        ficha = FichaTecnica.objects.create(referencia=self.referencia, lavado="ENZIMATICO")
        for product, quantity, waste in ((self.tela, "1.5", "10"), (self.cierre, "1", "0"), (self.boton, "1", "0")):
            FichaLinea.objects.create(ficha=ficha, producto=product, cantidad=Decimal(quantity), merma=Decimal(waste))

    def product(self, name, category, unit, stock="0", minimo="0"):
        return Producto.objects.create(
            codigo=f"T-{Producto.all_objects.count() + 1}", nombre=name, categoria=category,
            tipo=catalog.CATEGORIES[category]["tipo"], unidad=unit,
            stock_actual=Decimal(stock), stock_minimo=Decimal(minimo),
        )

    def production_order(self, **overrides):
        body = {
            "tipo": "PRODUCCION", "fecha_salida": today(), "responsable": "Marta Ruiz",
            "referencia": self.referencia.id, "cantidad_prendas": 100, "producto_resultado": self.generico.id,
            "lineas": [
                {"producto": self.tela.id, "cantidad": "300"},
                {"producto": self.cierre.id, "cantidad": "100"},
            ],
        }
        body.update(overrides)
        return self.api.post(reverse("inventario_ordenes"), body, format="json")

    def laundry_order(self, quantity="20", **overrides):
        body = {
            "tipo": "LAVANDERIA", "fecha_salida": today(), "responsable": "Lavandería Sol",
            "referencia": self.referencia.id, "producto_resultado": self.skinny.id,
            "lineas": [
                {"producto": self.generico.id, "cantidad": quantity},
                {"producto": self.boton.id, "cantidad": "100"},
            ],
        }
        body.update(overrides)
        return self.api.post(reverse("inventario_ordenes"), body, format="json")

    def refresh(self, *products):
        for product in products:
            product.refresh_from_db()


class PermissionTests(InventoryBase):
    def test_sin_sesion_no_entra(self):
        self.assertEqual(APIClient().get(reverse("inventario_productos")).status_code, 401)

    def test_rol_sin_permiso_no_entra(self):
        client = client_for(make_user("vendedor@t.co", "VENDEDOR"))
        self.assertEqual(client.get(reverse("inventario_productos")).status_code, 403)

    def test_produccion_consulta_pero_no_registra(self):
        client = client_for(make_user("jefe@t.co", "PRODUCCION"))
        self.assertEqual(client.get(reverse("inventario_productos")).status_code, 200)
        response = client.post(reverse("inventario_ingresos"), {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.post(reverse("inventario_ordenes"), {}, format="json").status_code, 403)


class PurchaseEntryTests(InventoryBase):
    def entry(self, **overrides):
        body = {
            "producto": self.tela.id, "cantidad": "150", "fecha": today(), "proveedor": self.supplier.id,
            "orden_compra": "OC-1", "lote": "L-2026-01",
        }
        body.update(overrides)
        return self.api.post(reverse("inventario_ingresos"), body, format="json")

    def test_ingreso_suma_al_saldo_y_deja_kardex(self):
        response = self.entry()
        self.assertEqual(response.status_code, 201, response.content)
        self.refresh(self.tela)
        self.assertEqual(self.tela.stock_actual, Decimal("1150"))
        movement = Movimiento.objects.get()
        self.assertEqual((movement.stock_antes, movement.stock_despues), (Decimal("1000"), Decimal("1150")))
        self.assertEqual(movement.registrado_por, self.storekeeper)
        # Se guarda el proveedor y su nombre de ese momento
        self.assertEqual((movement.proveedor, movement.proveedor_nombre), (self.supplier, "Textiles SA"))

    def test_exige_proveedor_y_lote(self):
        self.assertEqual(self.entry(proveedor=None).status_code, 400)
        self.assertEqual(self.entry(lote="").status_code, 400)
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_proveedor_inexistente_o_archivado_se_rechaza(self):
        self.assertEqual(self.entry(proveedor=99999).status_code, 400)
        self.supplier.delete()  # borrado lógico
        response = self.entry()
        self.assertEqual(response.status_code, 400)
        self.assertIn("archivado", response.json()["proveedor"][0])
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_el_historial_conserva_el_nombre_aunque_el_proveedor_cambie(self):
        movement_id = self.entry().json()["id"]
        self.supplier.razon_social = "Textiles Nueva SA"
        self.supplier.save()
        row = self.api.get(reverse("inventario_movimientos")).json()[0]
        self.assertEqual((row["id"], row["proveedor_nombre"]), (movement_id, "Textiles SA"))

    def test_cantidad_invalida(self):
        self.assertEqual(self.entry(cantidad="0").status_code, 400)
        self.assertEqual(self.entry(cantidad="-5").status_code, 400)
        self.assertEqual(self.entry(cantidad="abc").status_code, 400)
        self.assertEqual(self.entry(cantidad="1.555").status_code, 400)

    def test_unidad_entera_no_admite_decimales(self):
        self.assertEqual(self.entry(producto=self.cierre.id, cantidad="10.5").status_code, 400)

    def test_fecha_futura_no(self):
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertEqual(self.entry(fecha=future).status_code, 400)

    def test_compra_no_se_asocia_a_orden(self):
        self.assertEqual(self.entry(orden=1).status_code, 400)


class OrderTests(InventoryBase):
    def test_orden_de_produccion_descuenta_y_numera(self):
        response = self.production_order()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["codigo"], "OP-0001")
        self.assertEqual(body["estado"], "EN_PROCESO")
        self.assertEqual(len(body["lineas"]), 2)
        self.refresh(self.tela, self.cierre)
        self.assertEqual(self.tela.stock_actual, Decimal("700"))
        self.assertEqual(self.cierre.stock_actual, Decimal("400"))
        self.assertEqual(Movimiento.objects.filter(orden_id=body["id"], tipo="SALIDA").count(), 2)
        self.assertEqual(self.production_order().json()["codigo"], "OP-0002")

    def test_stock_insuficiente_no_guarda_nada_y_lista_faltantes(self):
        response = self.production_order(lineas=[
            {"producto": self.tela.id, "cantidad": "300"},
            {"producto": self.cierre.id, "cantidad": "9999"},
        ])
        self.assertEqual(response.status_code, 400)
        missing = response.json()["faltantes"]
        self.assertEqual([m["nombre"] for m in missing], ["Cierre"])
        self.refresh(self.tela)
        self.assertEqual(self.tela.stock_actual, Decimal("1000"))
        self.assertEqual(OrdenSalida.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_produccion_no_acepta_pantalones_como_insumo(self):
        self.generico.stock_actual = 10
        self.generico.save()
        response = self.production_order(lineas=[{"producto": self.generico.id, "cantidad": "1"}])
        self.assertEqual(response.status_code, 400)

    def test_resultado_debe_ser_del_tipo_correcto(self):
        self.assertEqual(self.production_order(producto_resultado=self.skinny.id).status_code, 400)
        self.assertEqual(self.production_order(producto_resultado=self.tela.id).status_code, 400)

    def test_producto_repetido_en_la_cesta(self):
        response = self.production_order(lineas=[
            {"producto": self.tela.id, "cantidad": "10"}, {"producto": self.tela.id, "cantidad": "10"},
        ])
        self.assertEqual(response.status_code, 400)

    def test_orden_sin_lineas(self):
        self.assertEqual(self.production_order(lineas=[]).status_code, 400)

    def test_crear_orden_lavanderia_se_rechaza_con_400_y_no_descuenta_insumos(self):
        self.generico.stock_actual = Decimal("50")
        self.generico.save()
        before_generic = self.generico.stock_actual
        before_button = self.boton.stock_actual

        response = self.laundry_order()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["tipo"][0], catalog.LAUNDRY_REDIRECT_MSG)

        self.refresh(self.generico, self.boton)
        self.assertEqual(self.generico.stock_actual, before_generic)
        self.assertEqual(self.boton.stock_actual, before_button)
        self.assertEqual(OrdenSalida.objects.count(), 0)
        self.assertEqual(Movimiento.objects.count(), 0)
        self.assertFalse(Consecutivo.objects.filter(clave="LV").exists())

        from rest_framework.exceptions import ValidationError

        from . import services

        with self.assertRaises(ValidationError) as ctx:
            services.create_order(
                user=self.storekeeper,
                tipo=catalog.ORDER_LAUNDRY,
                fecha_salida=timezone.localdate(),
                responsable="Lavandería Sol",
                referencia_id=self.referencia.id,
                producto_resultado_id=self.skinny.id,
                lineas=[{"producto": self.generico.id, "cantidad": "20"}],
            )
        self.assertIn(catalog.LAUNDRY_REDIRECT_MSG, str(ctx.exception.detail["tipo"][0]))

    def test_ordenes_lv_historicas_siguen_visibles_en_solo_lectura(self):
        legacy = OrdenSalida.objects.create(
            codigo="LV-0001",
            tipo=catalog.ORDER_LAUNDRY,
            estado=catalog.STATUS_OPEN,
            fecha_salida=today(),
            responsable="Lavandería Sol",
            referencia=self.referencia,
            ficha_tecnica=self.referencia.codigo,
            producto_resultado=self.skinny,
            cantidad_prendas=Decimal("20"),
            registrado_por=self.storekeeper,
        )
        Movimiento.objects.create(
            producto=self.generico,
            tipo=catalog.EXIT,
            motivo=catalog.REASON_ORDER_EXIT,
            cantidad=Decimal("20"),
            stock_antes=Decimal("20"),
            stock_despues=Decimal("0"),
            fecha=today(),
            orden=legacy,
            lote=self.referencia.codigo,
            registrado_por=self.storekeeper,
        )

        listed = self.api.get(reverse("inventario_ordenes"), {"tipo": catalog.ORDER_LAUNDRY})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([o["codigo"] for o in listed.json()], ["LV-0001"])

        detail = self.api.get(reverse("inventario_orden", args=[legacy.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual((detail.json()["tipo"], detail.json()["codigo"]), (catalog.ORDER_LAUNDRY, "LV-0001"))

        kardex = self.api.get(reverse("inventario_movimientos"), {"orden": legacy.id})
        self.assertEqual(kardex.status_code, 200)
        self.assertEqual([m["orden_codigo"] for m in kardex.json()], ["LV-0001"])


class OrderReturnTests(InventoryBase):
    def entry(self, product, order_id, quantity, **overrides):
        body = {"producto": product.id, "cantidad": quantity, "fecha": today(), "orden": order_id}
        body.update(overrides)
        return self.api.post(reverse("inventario_ingresos"), body, format="json")

    def test_produccion_termina_e_ingresa_genericos(self):
        order = self.production_order().json()
        response = self.entry(self.generico, order["id"], "80")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["lote"], "REF-0001")
        self.refresh(self.generico)
        self.assertEqual(self.generico.stock_actual, Decimal("80"))
        self.assertEqual(OrdenSalida.objects.get(pk=order["id"]).estado, "COMPLETADA")

    def test_formulario_envia_campos_vacios_como_cadena(self):
        """El formulario manda proveedor y lote vacíos al recibir un pantalón: no debe dar 400."""
        order = self.production_order().json()
        response = self.entry(
            self.generico, str(order["id"]), "80",
            proveedor="", orden_compra="", lote="", observaciones="",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_una_orden_no_se_recibe_dos_veces(self):
        order = self.production_order().json()
        self.assertEqual(self.entry(self.generico, order["id"], "80").status_code, 201)
        self.assertEqual(self.entry(self.generico, order["id"], "5").status_code, 400)

    def test_producto_de_otra_orden_se_rechaza(self):
        order = self.production_order().json()
        self.assertEqual(self.entry(self.skinny, order["id"], "5").status_code, 400)

    def test_generico_exige_orden(self):
        self.assertEqual(self.entry(self.generico, None, "5").status_code, 400)

    def test_ingreso_desde_orden_lv_o_producto_terminado_se_rechaza_y_op_no_cambia(self):
        legacy = OrdenSalida.objects.create(
            codigo="LV-0099",
            tipo=catalog.ORDER_LAUNDRY,
            estado=catalog.STATUS_OPEN,
            fecha_salida=today(),
            responsable="Lavandería Sol",
            referencia=self.referencia,
            ficha_tecnica=self.referencia.codigo,
            producto_resultado=self.skinny,
            cantidad_prendas=Decimal("20"),
            registrado_por=self.storekeeper,
        )
        # Intentar ingresar producto terminado desde Inventario (con o sin orden LV) falla con 400.
        direct = self.entry(self.skinny, None, "5")
        self.assertEqual(direct.status_code, 400)
        self.assertIn("Producción → Lavandería", str(direct.json()["producto"][0]))

        with_lv = self.entry(self.skinny, legacy.id, "15")
        self.assertEqual(with_lv.status_code, 400)
        self.assertIn("Producción → Lavandería", str(with_lv.json()["producto"][0]))

        # Tampoco permite usar una orden LV en el ingreso de otro producto.
        cross = self.entry(self.generico, legacy.id, "10")
        self.assertEqual(cross.status_code, 400)
        self.assertIn("Producción → Lavandería", str(cross.json()["orden"][0]))

        legacy.refresh_from_db()
        self.assertEqual(legacy.estado, catalog.STATUS_OPEN)
        self.refresh(self.skinny, self.generico)
        self.assertEqual((self.skinny.stock_actual, self.generico.stock_actual), (Decimal("0"), Decimal("0")))

        # Las órdenes OP de pantalones genéricos siguen cerrando normalmente.
        op = self.production_order().json()
        ok = self.entry(self.generico, op["id"], "95")
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(OrdenSalida.objects.get(pk=op["id"]).estado, catalog.STATUS_DONE)

    def test_ingreso_no_puede_ser_anterior_a_la_salida(self):
        order = self.production_order().json()
        past = (timezone.localdate() - timedelta(days=3)).isoformat()
        self.assertEqual(self.entry(self.generico, order["id"], "5", fecha=past).status_code, 400)


class CancelOrderTests(InventoryBase):
    def test_anular_devuelve_el_stock(self):
        order = self.production_order().json()
        url = reverse("inventario_orden_anular", args=[order["id"]])
        self.assertEqual(self.api.post(url, {}, format="json").status_code, 400)  # falta motivo
        response = self.api.post(url, {"motivo": "Error de digitación"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.refresh(self.tela, self.cierre)
        self.assertEqual(self.tela.stock_actual, Decimal("1000"))
        self.assertEqual(self.cierre.stock_actual, Decimal("500"))
        self.assertEqual(response.json()["estado"], "ANULADA")
        self.assertEqual(self.api.post(url, {"motivo": "otra vez"}, format="json").status_code, 400)

    def test_no_se_anula_una_orden_completada(self):
        order = self.production_order().json()
        self.api.post(
            reverse("inventario_ingresos"),
            {"producto": self.generico.id, "cantidad": "10", "fecha": today(), "orden": order["id"]},
            format="json",
        )
        url = reverse("inventario_orden_anular", args=[order["id"]])
        self.assertEqual(self.api.post(url, {"motivo": "x"}, format="json").status_code, 400)


class AlertTests(InventoryBase):
    def test_alerta_cuando_llega_al_minimo(self):
        self.assertEqual(self.api.get(reverse("inventario_alertas")).json()["count"], 0)
        self.production_order(lineas=[{"producto": self.tela.id, "cantidad": "800"}])
        alerts = self.api.get(reverse("inventario_alertas")).json()["alerts"]
        self.assertEqual([a["name"] for a in alerts], ["Tela denim"])
        self.assertEqual(alerts[0]["severity"], "warning")

    def test_sin_existencias_es_critica_y_sin_minimo_no_alerta(self):
        self.production_order(lineas=[{"producto": self.tela.id, "cantidad": "1000"}])
        alerts = self.api.get(reverse("inventario_alertas")).json()["alerts"]
        self.assertEqual(alerts[0]["severity"], "critical")
        # El botón no tiene mínimo definido: no genera alerta aunque llegue a cero.
        self.assertNotIn("Botón", [a["name"] for a in alerts])


class EvidenceTests(InventoryBase):
    def setUp(self):
        super().setUp()
        self.movement = self.api.post(
            reverse("inventario_ingresos"),
            {"producto": self.tela.id, "cantidad": "10", "fecha": today(), "proveedor": self.supplier.id, "lote": "L1"},
            format="json",
        ).json()

    def upload(self, name, content, content_type="image/png"):
        url = reverse("inventario_movimiento_evidencias", args=[self.movement["id"]])
        return self.api.post(url, {"archivos": [SimpleUploadedFile(name, content, content_type)]}, format="multipart")

    def test_sube_y_descarga_una_imagen(self):
        response = self.upload("factura.png", PNG)
        self.assertEqual(response.status_code, 201, response.content)
        evidence = response.json()[0]
        self.assertEqual(evidence["nombre_original"], "factura.png")
        download = self.api.get(reverse("inventario_evidencia", args=[evidence["id"]]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "image/png")
        self.assertEqual(b"".join(download.streaming_content), PNG)

    def test_el_tipo_lo_decide_el_contenido_no_el_nombre(self):
        response = self.upload("foto.png", b"<script>alert(1)</script>", "image/png")
        self.assertEqual(response.status_code, 400)

    def test_acepta_pdf(self):
        self.assertEqual(self.upload("orden.pdf", b"%PDF-1.4 contenido", "application/pdf").status_code, 201)

    def test_limite_de_tamano(self):
        big = PNG + b"0" * (catalog.EVIDENCE_MAX_BYTES + 1)
        self.assertEqual(self.upload("grande.png", big).status_code, 400)

    def test_sin_archivos(self):
        url = reverse("inventario_movimiento_evidencias", args=[self.movement["id"]])
        self.assertEqual(self.api.post(url, {}, format="multipart").status_code, 400)

    def test_descarga_exige_permiso(self):
        evidence = self.upload("f.png", PNG).json()[0]
        client = client_for(make_user("vendedor2@t.co", "VENDEDOR"))
        self.assertEqual(client.get(reverse("inventario_evidencia", args=[evidence["id"]])).status_code, 403)
        self.assertEqual(APIClient().get(reverse("inventario_evidencia", args=[evidence["id"]])).status_code, 401)

    def test_las_lineas_de_salida_muestran_las_evidencias_de_su_orden(self):
        order = self.production_order().json()
        url = reverse("inventario_orden_evidencias", args=[order["id"]])
        self.api.post(url, {"archivos": [SimpleUploadedFile("guia.png", PNG, "image/png")]}, format="multipart")
        rows = self.api.get(reverse("inventario_movimientos"), {"orden": order["id"]}).json()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual([e["nombre_original"] for e in row["evidencias"]], ["guia.png"])

    def test_descarga_evidencia_sin_archivo_fisico_responde_404(self):
        evidence = self.upload("efimero.png", PNG).json()[0]
        from pathlib import Path

        from .models import Evidencia

        record = Evidencia.objects.get(pk=evidence["id"])
        Path(record.archivo.path).unlink(missing_ok=True)
        with self.assertLogs("apps.inventory.views", level="WARNING"):
            download = self.api.get(reverse("inventario_evidencia", args=[evidence["id"]]))
        self.assertEqual(download.status_code, 404)
        self.assertIn("no está disponible", download.json()["detail"])
