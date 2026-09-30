"""Proveedores (HU 2.1 / RF04) y catálogo de telas e insumos (HU 2.2 / RF05)."""
import importlib
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from . import catalog
from .models import Movimiento, OrdenSalida, Producto, Proveedor
from .tests import InventoryBase, PNG, client_for, make_user, today

classify = importlib.import_module("apps.inventory.migrations.0003_clasificar_productos_existentes")


class SupplierBase(InventoryBase):
    def new_supplier(self, **overrides):
        body = {
            "nit": "890.900.123-1", "razon_social": "Fabricato Textil S.A.", "categoria": "TELA",
            "contacto": "Guillermo Restrepo", "telefono": "310 455 8899", "correo": "ventas@fabricato.com",
            "ciudad": "Medellín", "direccion": "Km 2 Vía Medellín - Bello",
        }
        body.update(overrides)
        return self.api.post(reverse("inventario_proveedores"), body, format="json")


class SupplierTests(SupplierBase):
    def test_crea_proveedor_y_normaliza_el_nit(self):
        response = self.new_supplier()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body["nit"], body["nit_dv"]), ("890900123", "1"))
        self.assertEqual(body["nit_formateado"], "890.900.123-1")
        self.assertEqual(body["categoria_nombre"], "Telas y tejidos denim")
        self.assertEqual(body["insumos_vinculados"], 0)

    def test_el_nit_sin_digito_de_verificacion_tambien_sirve(self):
        body = self.new_supplier(nit="900234567").json()
        self.assertEqual((body["nit"], body["nit_dv"], body["nit_formateado"]), ("900234567", "", "900.234.567"))

    def test_nit_con_estructura_invalida(self):
        for bad in ("abc", "12345", "12345678901", "890.900.123-12", "890-900-123", ""):
            response = self.new_supplier(nit=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("nit", response.json())
        self.assertEqual(Proveedor.objects.filter(razon_social="Fabricato Textil S.A.").count(), 0)

    def test_nit_duplicado_aunque_se_escriba_distinto(self):
        self.assertEqual(self.new_supplier().status_code, 201)
        for same in ("890900123-1", "890.900.123", "890 900 123 - 1"):
            response = self.new_supplier(nit=same, razon_social="Otra")
            self.assertEqual(response.status_code, 400, same)
            self.assertIn("NIT", response.json()["nit"][0])

    def test_archivado_libera_el_nit_y_restaurar_respeta_la_unicidad(self):
        first = self.new_supplier().json()
        self.assertEqual(self.api.delete(reverse("inventario_proveedor", args=[first["id"]])).status_code, 204)
        second = self.new_supplier(razon_social="Nueva razón social")
        self.assertEqual(second.status_code, 201)  # el NIT del archivado se puede volver a usar
        restore = self.api.post(reverse("inventario_proveedor_restaurar", args=[first["id"]]))
        self.assertEqual(restore.status_code, 400)  # pero ahora choca con el activo
        self.api.delete(reverse("inventario_proveedor", args=[second.json()["id"]]))
        restore = self.api.post(reverse("inventario_proveedor_restaurar", args=[first["id"]]))
        self.assertEqual(restore.status_code, 200, restore.content)
        self.assertFalse(restore.json()["archivado"])

    def test_no_se_puede_usar_el_nit_de_otro_al_editar(self):
        other = self.new_supplier(nit="860.001.234-9", razon_social="Eka").json()
        mine = self.new_supplier().json()
        url = reverse("inventario_proveedor", args=[mine["id"]])
        self.assertEqual(self.api.patch(url, {"nit": "860001234"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"nit": "890.900.123-1", "ciudad": "Bello"}, format="json").status_code, 200)
        self.assertEqual(Proveedor.objects.get(pk=mine["id"]).ciudad, "Bello")
        self.assertEqual(Proveedor.objects.get(pk=other["id"]).nit, "860001234")

    def test_campos_obligatorios_y_formatos(self):
        self.assertEqual(self.new_supplier(razon_social="   ").status_code, 400)
        self.assertEqual(self.new_supplier(categoria="PANTALON_GENERICO").status_code, 400)
        self.assertEqual(self.new_supplier(correo="no-es-correo").status_code, 400)
        self.assertEqual(self.new_supplier(telefono="abc").status_code, 400)
        self.assertEqual(self.new_supplier(telefono="123").status_code, 400)
        self.assertEqual(self.new_supplier(telefono="+57 (607) 555-1234").status_code, 201)

    def test_contacto_ciudad_y_correo_son_opcionales(self):
        body = {"nit": "900.111.222-3", "razon_social": "Mínimo S.A.S.", "categoria": "HILO"}
        self.assertEqual(self.api.post(reverse("inventario_proveedores"), body, format="json").status_code, 201)

    def test_busqueda_y_filtros(self):
        self.new_supplier()
        self.new_supplier(nit="860.001.234-9", razon_social="Cierres Eka", categoria="CIERRE", ciudad="Bogotá")
        url = reverse("inventario_proveedores")
        names = lambda params: [p["razon_social"] for p in self.api.get(url, params).json()]  # noqa: E731
        self.assertEqual(names({"q": "eka"}), ["Cierres Eka"])
        self.assertEqual(names({"q": "860.001"}), ["Cierres Eka"])  # por NIT, con o sin puntos
        self.assertEqual(names({"q": "bogot"}), ["Cierres Eka"])
        self.assertEqual(set(names({"categoria": "TELA"})), {"Fabricato Textil S.A.", "Textiles SA"})
        self.assertEqual(names({"q": "zzz"}), [])
        # El proveedor de las pruebas (Textiles SA) también está activo
        self.assertEqual(len(names({})), 3)

    def test_archivados_solo_aparecen_si_se_piden(self):
        created = self.new_supplier().json()
        self.api.delete(reverse("inventario_proveedor", args=[created["id"]]))
        url = reverse("inventario_proveedores")
        self.assertNotIn(created["id"], [p["id"] for p in self.api.get(url).json()])
        archived = self.api.get(url, {"archivados": "1"}).json()
        self.assertEqual([p["id"] for p in archived], [created["id"]])
        self.assertTrue(archived[0]["archivado"])
        # Un archivado no se edita ni se vuelve a archivar
        detail = reverse("inventario_proveedor", args=[created["id"]])
        self.assertEqual(self.api.patch(detail, {"ciudad": "X"}, format="json").status_code, 404)

    def test_insumos_vinculados_sale_del_historial_de_compras(self):
        def buy(product):
            return self.api.post(
                reverse("inventario_ingresos"),
                {"producto": product.id, "cantidad": "5", "fecha": today(), "proveedor": self.supplier.id, "lote": "L"},
                format="json",
            )

        self.assertEqual(buy(self.tela).status_code, 201)
        self.assertEqual(buy(self.tela).status_code, 201)  # el mismo insumo dos veces cuenta una
        self.assertEqual(buy(self.cierre).status_code, 201)
        row = next(p for p in self.api.get(reverse("inventario_proveedores")).json() if p["id"] == self.supplier.id)
        self.assertEqual(row["insumos_vinculados"], 2)

    def test_permisos(self):
        url = reverse("inventario_proveedores")
        production = client_for(make_user("jefe@t.co", "PRODUCCION"))  # inventario.ver, sin gestionar
        self.assertEqual(production.get(url).status_code, 200)
        self.assertEqual(production.post(url, {}, format="json").status_code, 403)
        detail = reverse("inventario_proveedor", args=[self.supplier.id])
        self.assertEqual(production.patch(detail, {"ciudad": "X"}, format="json").status_code, 403)
        self.assertEqual(production.delete(detail).status_code, 403)
        seller = client_for(make_user("vendedor@t.co", "VENDEDOR"))
        self.assertEqual(seller.get(url).status_code, 403)
        self.assertEqual(self.api.__class__().get(url).status_code, 401)


class CatalogBase(InventoryBase):
    def new_product(self, **overrides):
        body = {
            "nombre": "Denim Rígido Azul 14oz", "categoria": "TELA", "unidad": "m", "stock_minimo": "100",
            "ancho_util": "1.60", "color": "Azul índigo", "composicion": "98% algodón / 2% elastano",
        }
        body.update(overrides)
        return self.api.post(reverse("inventario_catalogo"), body, format="json")


class CatalogCreateTests(CatalogBase):
    def test_crea_tela_con_codigo_y_tipo_derivados(self):
        response = self.new_product()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["codigo"], "TEL-0001")
        self.assertEqual((body["tipo"], body["categoria_nombre"]), ("MATERIA_PRIMA", "Telas y tejidos denim"))
        self.assertEqual(body["ancho_util"], "1.60")
        self.assertEqual(self.new_product(nombre="Otra tela").json()["codigo"], "TEL-0002")

    def test_el_catalogo_no_expone_las_existencias(self):
        body = self.new_product().json()
        self.assertNotIn("stock_actual", body)
        self.assertNotIn("bajo_minimo", body)
        for item in self.api.get(reverse("inventario_catalogo")).json():
            self.assertNotIn("stock_actual", item)
            self.assertNotIn("bajo_minimo", item)
        created = Producto.objects.get(pk=body["id"])
        self.assertEqual(created.stock_actual, Decimal("0"))

    def test_las_existencias_no_se_fijan_desde_el_catalogo(self):
        body = self.new_product(stock_actual="500").json()  # campo ignorado
        self.assertEqual(Producto.objects.get(pk=body["id"]).stock_actual, Decimal("0"))
        url = reverse("inventario_catalogo_detalle", args=[self.tela.id])
        # (la tela de las pruebas es un producto "antiguo" sin ancho ni composición: la edición los pide)
        edit = {"stock_actual": "5", "color": "Negro", "ancho_util": "1.55", "composicion": "100% algodón"}
        self.assertEqual(self.api.patch(url, edit, format="json").status_code, 200)
        self.tela.refresh_from_db()
        self.assertEqual((self.tela.stock_actual, self.tela.color), (Decimal("1000"), "Negro"))

    def test_prefijos_por_categoria(self):
        cases = {
            ("HILO", "kg", "100% poliéster"): "HIL-", ("CIERRE", "unidad", ""): "CIE-",
            ("BOTON_REMACHE", "unidad", ""): "BOT-", ("ETIQUETA_EMPAQUE", "caja", ""): "ETQ-",
            ("QUIMICO", "l", ""): "QUI-", ("OTRO_INSUMO", "kg", ""): "INS-",
        }
        for (category, unit, composition), prefix in cases.items():
            body = self.new_product(
                nombre=f"Producto {category}", categoria=category, unidad=unit, composicion=composition,
                ancho_util=None,
            ).json()
            self.assertTrue(body["codigo"].startswith(prefix), (category, body))

    def test_tela_exige_ancho_util_entre_0_y_5_metros(self):
        for bad in (None, "0", "-1", "5.01"):
            response = self.new_product(ancho_util=bad)
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("ancho_util", response.json())
        self.assertEqual(self.new_product(ancho_util="5").status_code, 201)

    def test_solo_las_telas_llevan_ancho_util(self):
        body = self.new_product(nombre="Remache dorado", categoria="BOTON_REMACHE", unidad="unidad",
                                composicion="", ancho_util="1.5").json()
        self.assertIsNone(body["ancho_util"])

    def test_composicion_de_telas_e_hilos(self):
        ok = ["100% algodón", "80% algodón y 20% nilon", "98,5% algodón / 1,5% elastano", "60%poliéster+40%algodón"]
        for index, text in enumerate(ok):
            self.assertEqual(self.new_product(nombre=f"T{index}", composicion=text).status_code, 201, text)
        bad = ["", "algodón", "80% algodón / 30% nylon", "50% algodón"]
        for text in bad:
            response = self.new_product(nombre="X", composicion=text)
            self.assertEqual(response.status_code, 400, text)
            self.assertIn("composicion", response.json())
        thread = self.new_product(nombre="Hilo", categoria="HILO", unidad="kg", ancho_util=None, composicion="")
        self.assertEqual(thread.status_code, 400)  # el hilo también la exige
        button = self.new_product(nombre="Remache dorado", categoria="BOTON_REMACHE", unidad="unidad",
                                  ancho_util=None, composicion="")
        self.assertEqual(button.status_code, 201)  # los demás insumos no

    def test_unidad_compatible_con_la_categoria(self):
        for category, unit in (("TELA", "kg"), ("TELA", "unidad"), ("CIERRE", "m"), ("HILO", "m"), ("QUIMICO", "unidad")):
            response = self.new_product(nombre=f"{category}{unit}", categoria=category, unidad=unit,
                                        composicion="100% algodón")
            self.assertEqual(response.status_code, 400, (category, unit))
            self.assertIn("unidad", response.json())
        self.assertEqual(self.new_product(nombre="En rollos", unidad="rollo").status_code, 201)

    def test_pantalones_solo_en_unidades(self):
        for category in ("PANTALON_GENERICO", "PRODUCTO_TERMINADO"):
            bad = self.new_product(nombre=category, categoria=category, unidad="m", ancho_util=None, composicion="")
            self.assertEqual(bad.status_code, 400)
        ok = self.new_product(nombre="MOD-SLIM", categoria="PRODUCTO_TERMINADO", unidad="unidad", ancho_util=None,
                              composicion="").json()
        self.assertEqual((ok["tipo"], ok["codigo"][:3]), ("TERMINADO", "PT-"))

    def test_nombre_repetido_en_la_misma_categoria(self):
        self.assertEqual(self.new_product().status_code, 201)
        self.assertEqual(self.new_product(nombre="DENIM RÍGIDO AZUL 14OZ").status_code, 400)
        # El mismo nombre en otra categoría es otro producto
        other = self.new_product(categoria="HILO", unidad="kg", ancho_util=None, composicion="100% algodón")
        self.assertEqual(other.status_code, 201)

    def test_campos_basicos(self):
        self.assertEqual(self.new_product(nombre="   ").status_code, 400)
        self.assertEqual(self.new_product(nombre="A", categoria="INEXISTENTE").status_code, 400)
        self.assertEqual(self.new_product(nombre="B", stock_minimo="-1").status_code, 400)
        self.assertEqual(self.new_product(nombre="C", stock_minimo="1.555").status_code, 400)
        self.assertEqual(Producto.objects.filter(nombre__in=["A", "B", "C"]).count(), 0)


class CatalogEditTests(CatalogBase):
    def test_editar_minimo_color_y_composicion(self):
        created = self.new_product().json()
        url = reverse("inventario_catalogo_detalle", args=[created["id"]])
        response = self.api.patch(url, {"stock_minimo": "250", "color": "Negro", "composicion": "100% algodón"},
                                  format="json")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["stock_minimo"], body["color"], body["composicion"]), ("250.00", "Negro", "100% algodón"))
        self.assertEqual(body["ancho_util"], "1.60")  # lo que no se envió no se toca

    def test_la_edicion_tambien_valida(self):
        created = self.new_product().json()
        url = reverse("inventario_catalogo_detalle", args=[created["id"]])
        self.assertEqual(self.api.patch(url, {"composicion": "90% algodón"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"ancho_util": "9"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"nombre": " "}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"stock_minimo": "-3"}, format="json").status_code, 400)

    def test_categoria_y_unidad_solo_cambian_sin_movimientos(self):
        created = self.new_product(nombre="Sin uso").json()
        url = reverse("inventario_catalogo_detalle", args=[created["id"]])
        self.assertEqual(self.api.patch(url, {"unidad": "rollo"}, format="json").status_code, 200)
        # Con movimientos, no
        used = reverse("inventario_catalogo_detalle", args=[self.tela.id])
        Movimiento.objects.create(
            producto=self.tela, tipo="INGRESO", motivo="COMPRA", cantidad=1, stock_antes=0, stock_despues=1,
            fecha=today(),
        )
        self.tela.categoria = "TELA"
        self.tela.save()
        response = self.api.patch(used, {"unidad": "rollo"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("categoria", response.json())

    def test_el_nombre_no_puede_chocar_con_otro_al_editar(self):
        self.new_product(nombre="Uno")
        two = self.new_product(nombre="Dos").json()
        url = reverse("inventario_catalogo_detalle", args=[two["id"]])
        self.assertEqual(self.api.patch(url, {"nombre": "uno"}, format="json").status_code, 400)
        self.assertEqual(self.api.patch(url, {"nombre": "Dos"}, format="json").status_code, 200)

    def test_eliminar_solo_sin_existencias(self):
        self.assertEqual(self.api.delete(reverse("inventario_catalogo_detalle", args=[self.tela.id])).status_code, 400)
        url = reverse("inventario_catalogo_detalle", args=[self.generico.id])
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.assertTrue(Producto.all_objects.get(pk=self.generico.id).is_deleted)
        self.assertNotIn(self.generico.id, [p["id"] for p in self.api.get(reverse("inventario_catalogo")).json()])
        self.assertNotIn(self.generico.id, [p["id"] for p in self.api.get(reverse("inventario_productos")).json()])

    def test_no_se_elimina_un_producto_que_una_orden_en_proceso_va_a_producir(self):
        self.production_order()
        self.assertEqual(self.api.delete(reverse("inventario_catalogo_detalle", args=[self.generico.id])).status_code, 400)

    def test_listado_por_categoria_y_busqueda(self):
        self.new_product()
        url = reverse("inventario_catalogo")
        names = lambda params: {p["nombre"] for p in self.api.get(url, params).json()}  # noqa: E731
        self.assertEqual(names({"categoria": "CIERRE"}), {"Cierre"})
        self.assertEqual(names({"categoria": "TELA,CIERRE"}), {"Tela denim", "Cierre", "Denim Rígido Azul 14oz"})
        self.assertEqual(names({"q": "rígido"}), {"Denim Rígido Azul 14oz"})
        self.assertEqual(names({"q": "índigo"}), {"Denim Rígido Azul 14oz"})  # también por color
        self.assertEqual(names({"q": "TEL-0001"}), {"Denim Rígido Azul 14oz"})  # o por código

    def test_permisos(self):
        url = reverse("inventario_catalogo")
        production = client_for(make_user("jefe@t.co", "PRODUCCION"))
        self.assertEqual(production.get(url).status_code, 200)
        self.assertEqual(production.post(url, {}, format="json").status_code, 403)
        detail = reverse("inventario_catalogo_detalle", args=[self.tela.id])
        self.assertEqual(production.patch(detail, {"color": "X"}, format="json").status_code, 403)
        self.assertEqual(production.delete(detail).status_code, 403)
        self.assertEqual(client_for(make_user("vendedor@t.co", "VENDEDOR")).get(url).status_code, 403)


class CatalogImageTests(CatalogBase):
    def setUp(self):
        super().setUp()
        self.product_id = self.new_product().json()["id"]
        self.url = reverse("inventario_catalogo_imagen", args=[self.product_id])

    def upload(self, name="tela.png", content=PNG, content_type="image/png", client=None):
        return (client or self.api).post(
            self.url, {"imagen": SimpleUploadedFile(name, content, content_type)}, format="multipart"
        )

    def test_sube_y_sirve_la_imagen(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["tiene_imagen"])
        self.assertEqual(response.json()["imagen_version"], 1)
        image = self.api.get(self.url)
        self.assertEqual((image.status_code, image["Content-Type"]), (200, "image/png"))
        self.assertEqual(image.content, PNG)
        self.assertEqual(self.api.get(self.url, HTTP_IF_NONE_MATCH=image["ETag"]).status_code, 304)

    def test_reemplazar_y_quitar_cambian_la_version(self):
        self.upload()
        again = self.upload(content=b"\xff\xd8\xff" + b"0" * 20, content_type="image/jpeg", name="t.jpg")
        self.assertEqual(again.json()["imagen_version"], 2)
        self.assertEqual(self.api.get(self.url)["Content-Type"], "image/jpeg")
        removed = self.api.delete(self.url)
        self.assertEqual((removed.status_code, removed.json()["tiene_imagen"]), (200, False))
        self.assertEqual(self.api.get(self.url).status_code, 404)

    def test_el_tipo_lo_decide_el_contenido(self):
        self.assertEqual(self.upload(content=b"<script>alert(1)</script>").status_code, 400)
        self.assertEqual(self.upload(content=b"%PDF-1.4 algo", content_type="application/pdf").status_code, 400)
        self.assertEqual(self.api.get(self.url).status_code, 404)

    def test_limite_de_tamano_y_archivo_obligatorio(self):
        self.assertEqual(self.upload(content=PNG + b"0" * catalog.IMAGE_MAX_BYTES).status_code, 400)
        self.assertEqual(self.api.post(self.url, {}, format="multipart").status_code, 400)

    def test_sin_imagen_responde_404(self):
        self.assertEqual(self.api.get(self.url).status_code, 404)

    def test_permisos_de_la_imagen(self):
        self.upload()
        production = client_for(make_user("jefe@t.co", "PRODUCCION"))
        self.assertEqual(production.get(self.url).status_code, 200)
        self.assertEqual(self.upload(client=production).status_code, 403)
        self.assertEqual(production.delete(self.url).status_code, 403)
        self.assertEqual(client_for(make_user("vendedor@t.co", "VENDEDOR")).get(self.url).status_code, 403)

    def test_la_imagen_no_se_carga_en_los_listados(self):
        self.upload()
        self.assertIn("imagen", Producto.objects.get(pk=self.product_id).get_deferred_fields())
        listed = next(p for p in self.api.get(reverse("inventario_catalogo")).json() if p["id"] == self.product_id)
        self.assertNotIn("imagen", listed)
        self.assertTrue(listed["tiene_imagen"])


class InventoryViewTests(CatalogBase):
    def test_inventario_es_de_solo_lectura_para_productos(self):
        url = reverse("inventario_productos")
        self.assertEqual(self.api.get(url).status_code, 200)
        self.assertEqual(self.api.post(url, {"nombre": "X"}, format="json").status_code, 405)

    def test_inventario_si_muestra_existencias_y_categoria(self):
        tela = next(p for p in self.api.get(reverse("inventario_productos")).json() if p["id"] == self.tela.id)
        self.assertEqual((tela["stock_actual"], tela["categoria"]), ("1000.00", "TELA"))
        self.assertTrue(tela["stock_minimo"])


class ClassifyExistingProductsTests(InventoryBase):
    """La migración 0003 da categoría a lo creado antes del catálogo."""

    def test_categoria_para(self):
        cases = [
            ("GENERICO", "Pantalón genérico", "PANTALON_GENERICO"),
            ("TERMINADO", "MOD-SKINNY", "PRODUCTO_TERMINADO"),
            ("MATERIA_PRIMA", "Tela denim 12 oz", "TELA"),
            ("MATERIA_PRIMA", "Hilo poliéster", "HILO"),
            ("MATERIA_PRIMA", "Hilaza de algodón", "HILO"),
            ("INSUMO", "Cierre metálico", "CIERRE"),
            ("INSUMO", "Cremallera YKK", "CIERRE"),
            ("INSUMO", "Botón metálico", "BOTON_REMACHE"),
            ("INSUMO", "Remache", "BOTON_REMACHE"),
            ("INSUMO", "Etiqueta de marca", "ETIQUETA_EMPAQUE"),
            ("INSUMO", "Bolsa de empaque", "ETIQUETA_EMPAQUE"),
            ("INSUMO", "Químico suavizante", "QUIMICO"),
            ("INSUMO", "Cinta", "OTRO_INSUMO"),
        ]
        for tipo, name, expected in cases:
            self.assertEqual(classify.categoria_para(tipo, name), expected, name)

    def test_todas_las_categorias_existen_y_son_coherentes_con_el_tipo(self):
        for code, data in catalog.CATEGORIES.items():
            self.assertIn(data["tipo"], dict(catalog.PRODUCT_TYPES), code)
            self.assertTrue(data["units"], code)
            self.assertTrue(set(data["units"]) <= {u for u, _ in catalog.UNITS}, code)


class MetadataTests(CatalogBase):
    def test_metadatos_describen_categorias_y_reglas(self):
        body = self.api.get(reverse("inventario_metadatos")).json()
        by_code = {c["codigo"]: c for c in body["categorias"]}
        self.assertEqual(set(by_code), set(catalog.CATEGORIES))
        self.assertTrue(by_code["TELA"]["requiere_ancho_util"] and by_code["TELA"]["requiere_composicion"])
        self.assertTrue(by_code["HILO"]["requiere_composicion"] and not by_code["HILO"]["requiere_ancho_util"])
        self.assertEqual(by_code["TELA"]["unidades"], ["m", "rollo"])
        self.assertTrue(by_code["TELA"]["compra"] and not by_code["PANTALON_GENERICO"]["compra"])
        self.assertIn({"codigo": "unidad", "nombre": "Unidades", "entera": True}, body["unidades"])

    def test_metadatos_exigen_permiso(self):
        seller = client_for(make_user("vendedor@t.co", "VENDEDOR"))
        self.assertEqual(seller.get(reverse("inventario_metadatos")).status_code, 403)


@override_settings(DEBUG=True)
class DemoSeedTests(InventoryBase):
    """El comando de datos de demostración usa las reglas reales y se puede repetir."""

    def snapshot(self):
        return (
            Producto.objects.count(), Movimiento.objects.count(), OrdenSalida.objects.count(), Proveedor.objects.count(),
        )

    def test_carga_datos_coherentes_y_es_idempotente(self):
        call_command("seed_demo_inventario", verbosity=0)
        first = self.snapshot()
        self.assertGreater(first[0], 35)  # catálogo amplio
        self.assertGreater(first[2], 4)  # varias órdenes
        call_command("seed_demo_inventario", verbosity=0)
        self.assertEqual(self.snapshot(), first)

        # Cada saldo coincide con el último movimiento del kardex de ese producto
        for product in Producto.objects.all():
            last = product.movimientos.first()
            if last:
                self.assertEqual(product.stock_actual, last.stock_despues, product.nombre)
            self.assertGreaterEqual(product.stock_actual, 0)

        states = set(OrdenSalida.objects.values_list("estado", flat=True))
        self.assertEqual(states, {"COMPLETADA", "EN_PROCESO", "ANULADA"})
        self.assertTrue(self.api.get(reverse("inventario_alertas")).json()["count"] > 0)
        # Las compras quedan ligadas a proveedores reales de la lista
        linked = {p["razon_social"]: p["insumos_vinculados"] for p in self.api.get(reverse("inventario_proveedores")).json()}
        self.assertGreater(len([v for v in linked.values() if v]), 8)
        # Las telas llevan foto de referencia
        tela = next(p for p in self.api.get(reverse("inventario_catalogo"), {"categoria": "TELA"}).json() if p["tiene_imagen"])
        self.assertEqual(self.api.get(reverse("inventario_catalogo_imagen", args=[tela["id"]]))["Content-Type"], "image/png")

    def test_solo_funciona_en_desarrollo(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(Exception):
                call_command("seed_demo_inventario", verbosity=0)
