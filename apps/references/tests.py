"""Catálogo de referencias de jean (HU 3.1): registro, variantes, estados, imágenes y permisos."""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.inventory.tests import PNG, client_for, make_user
from apps.users.models import ModulePermission, Role

from . import catalog
from .models import ImagenReferencia, Referencia, Variante

JPG = b"\xff\xd8\xff\xe0" + b"1" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"2" * 32


def image(content=PNG, name="proto.png"):
    return SimpleUploadedFile(name, content, content_type="image/png")


class ReferenceBase(TestCase):
    def setUp(self):
        self.boss = make_user("produccion@t.co", "PRODUCCION")
        self.api = client_for(self.boss)

    def create(self, **overrides):
        body = {
            "nombre": "Skinny 5 bolsillos", "descripcion": "Tiro medio, tela con elastano",
            "ajuste": "SKINNY", "variantes": [{"talla": "30", "color": "Azul oscuro"}],
        }
        body.update(overrides)
        return self.api.post(reverse("referencias"), body, format="json")

    def new(self, **overrides):
        response = self.create(**overrides)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def upload(self, reference_id, *files, client=None):
        return (client or self.api).post(
            reverse("referencia_imagenes", args=[reference_id]), {"imagen": list(files)}, format="multipart"
        )

    def set_state(self, reference_id, state):
        return self.api.post(reverse("referencia_estado", args=[reference_id]), {"estado": state}, format="json")

    def activate(self, reference_id):
        self.assertEqual(self.upload(reference_id, image()).status_code, 201)
        response = self.set_state(reference_id, catalog.ACTIVE)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class CreateTests(ReferenceBase):
    def test_crea_en_borrador_con_codigo_automatico_y_autor(self):
        body = self.new()
        self.assertEqual(body["codigo"], "REF-0001")
        self.assertEqual((body["estado"], body["estado_nombre"]), ("BORRADOR", "Borrador"))
        self.assertEqual(body["ajuste_nombre"], "Skinny")
        self.assertEqual(body["creado_por_nombre"], "produccion@t.co")
        self.assertEqual(body["imagenes"], [])
        self.assertIsNone(body["imagen_principal"])
        self.assertEqual(self.new(nombre="Mom jean")["codigo"], "REF-0002")

    def test_normaliza_nombre_talla_y_color(self):
        body = self.new(nombre="  Slim   fit  ", variantes=[{"talla": " m ", "color": "  azul   claro "}])
        self.assertEqual(body["nombre"], "Slim fit")
        self.assertEqual([(v["talla"], v["color"]) for v in body["variantes"]], [("M", "azul claro")])

    def test_puede_nacer_sin_variantes_ni_descripcion(self):
        body = self.new(variantes=[], descripcion="")
        self.assertEqual(body["variantes"], [])
        body = self.api.post(reverse("referencias"), {"nombre": "Recto", "ajuste": "RECTO"}, format="json").json()
        self.assertEqual(body["variantes"], [])

    def test_datos_obligatorios_y_ajuste_valido(self):
        for bad in ({"nombre": ""}, {"nombre": "   "}, {"ajuste": "CUADRADO"}, {"ajuste": ""}):
            self.assertEqual(self.create(**bad).status_code, 400, bad)
        self.assertEqual(self.api.post(reverse("referencias"), {}, format="json").status_code, 400)
        self.assertEqual(Referencia.objects.count(), 0)

    def test_nombre_repetido_aunque_cambien_mayusculas_o_espacios(self):
        self.new()
        for same in ("skinny 5 bolsillos", "SKINNY 5 BOLSILLOS", "  Skinny  5  bolsillos "):
            response = self.create(nombre=same)
            self.assertEqual(response.status_code, 400, same)
            self.assertIn("nombre", response.json())
        self.assertEqual(Referencia.objects.count(), 1)

    def test_el_codigo_no_se_gasta_si_la_creacion_falla(self):
        self.new()
        self.assertEqual(self.create(variantes=[{"talla": "", "color": "Negro"}], nombre="Otra").status_code, 400)
        self.assertEqual(self.new(nombre="Tercera")["codigo"], "REF-0002")

    def test_variantes_invalidas(self):
        casos = {
            "sin talla": [{"talla": "", "color": "Negro"}],
            "sin color": [{"talla": "30", "color": ""}],
            "repetida": [{"talla": "30", "color": "Negro"}, {"talla": "30", "color": "negro"}],
            "repetida con espacios": [{"talla": "m", "color": "Negro"}, {"talla": " M ", "color": " NEGRO "}],
        }
        for name, variantes in casos.items():
            response = self.create(nombre=f"Ref {name}", variantes=variantes)
            self.assertEqual(response.status_code, 400, name)
            self.assertIn("variantes", response.json(), name)
        self.assertEqual(Referencia.objects.count(), 0)

    def test_misma_talla_con_distinto_color_es_valida(self):
        body = self.new(variantes=[{"talla": "30", "color": "Negro"}, {"talla": "30", "color": "Azul"}])
        self.assertEqual(len(body["variantes"]), 2)

    def test_limite_de_variantes(self):
        grande = [{"talla": str(n), "color": "Negro"} for n in range(catalog.MAX_VARIANTS + 1)]
        self.assertEqual(self.create(variantes=grande).status_code, 400)
        self.assertEqual(self.create(variantes=grande[:-1]).status_code, 201)

    def test_tallas_y_colores_resumidos(self):
        body = self.new(variantes=[
            {"talla": "32", "color": "Negro"}, {"talla": "8", "color": "azul"},
            {"talla": "30", "color": "Azul"}, {"talla": "M", "color": "Negro"},
        ])
        self.assertEqual(body["tallas"], ["8", "30", "32", "M"])  # numéricas por valor, luego letras
        self.assertEqual(body["colores"], ["azul", "Negro"])  # sin repetir azul/Azul


class ListTests(ReferenceBase):
    def setUp(self):
        super().setUp()
        self.skinny = self.new(nombre="Skinny clásico", variantes=[{"talla": "30", "color": "Azul oscuro"}])
        self.mom = self.new(nombre="Mom vintage", ajuste="MOM", descripcion="Tiro alto",
                            variantes=[{"talla": "28", "color": "Negro"}, {"talla": "30", "color": "Gris"}])
        self.activate(self.mom["id"])

    def names(self, **params):
        response = self.api.get(reverse("referencias"), params)
        self.assertEqual(response.status_code, 200)
        return sorted(r["nombre"] for r in response.json())

    def test_lista_todas(self):
        self.assertEqual(self.names(), ["Mom vintage", "Skinny clásico"])

    def test_filtra_por_estado_y_ajuste(self):
        self.assertEqual(self.names(estado="ACTIVA"), ["Mom vintage"])
        self.assertEqual(self.names(estado="BORRADOR,ACTIVA"), ["Mom vintage", "Skinny clásico"])
        self.assertEqual(self.names(ajuste="SKINNY"), ["Skinny clásico"])

    def test_filtra_por_talla_y_color_sin_repetir_filas(self):
        self.assertEqual(self.names(talla="30"), ["Mom vintage", "Skinny clásico"])
        self.assertEqual(self.names(talla="28"), ["Mom vintage"])
        self.assertEqual(self.names(color="oscuro"), ["Skinny clásico"])

    def test_busca_por_texto_codigo_descripcion_y_color(self):
        self.assertEqual(self.names(q="vintage"), ["Mom vintage"])
        self.assertEqual(self.names(q="REF-0001"), ["Skinny clásico"])
        self.assertEqual(self.names(q="tiro alto"), ["Mom vintage"])
        self.assertEqual(self.names(q="gris"), ["Mom vintage"])
        self.assertEqual(self.names(q="no existe"), [])

    def test_las_archivadas_no_aparecen(self):
        self.assertEqual(self.api.delete(reverse("referencia", args=[self.skinny["id"]])).status_code, 204)
        self.assertEqual(self.names(), ["Mom vintage"])

    def test_detalle(self):
        body = self.api.get(reverse("referencia", args=[self.mom["id"]])).json()
        self.assertEqual(body["nombre"], "Mom vintage")
        self.assertEqual(len(body["variantes"]), 2)
        self.assertEqual(self.api.get(reverse("referencia", args=[99999])).status_code, 404)


class UpdateTests(ReferenceBase):
    def test_edita_datos(self):
        ref = self.new()
        response = self.api.patch(
            reverse("referencia", args=[ref["id"]]),
            {"nombre": "Skinny 5B", "ajuste": "SLIM", "descripcion": "Nueva"}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["nombre"], body["ajuste"], body["descripcion"]), ("Skinny 5B", "SLIM", "Nueva"))
        self.assertEqual(body["codigo"], ref["codigo"])  # el código no cambia
        self.assertEqual(len(body["variantes"]), 1)  # sin `variantes` no se tocan

    def test_conservar_el_propio_nombre_no_es_duplicado(self):
        ref = self.new()
        response = self.api.patch(reverse("referencia", args=[ref["id"]]), {"nombre": "skinny 5 BOLSILLOS"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_no_puede_tomar_el_nombre_de_otra(self):
        self.new(nombre="Otra")
        ref = self.new()
        response = self.api.patch(reverse("referencia", args=[ref["id"]]), {"nombre": "otra"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("nombre", response.json())

    def test_la_lista_de_variantes_reemplaza_a_la_actual(self):
        ref = self.new(variantes=[{"talla": "30", "color": "Azul"}, {"talla": "32", "color": "Azul"}])
        kept = Variante.objects.get(talla="30").id
        response = self.api.patch(
            reverse("referencia", args=[ref["id"]]),
            {"variantes": [{"talla": "30", "color": "azul"}, {"talla": "34", "color": "Negro"}]}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        pairs = sorted((v["talla"], v["color"]) for v in response.json()["variantes"])
        self.assertEqual(pairs, [("30", "Azul"), ("34", "Negro")])
        self.assertTrue(Variante.objects.filter(pk=kept).exists())  # la que sigue no se recrea
        self.assertEqual(Variante.all_objects.filter(talla="32").get().is_deleted, True)

    def test_variante_quitada_se_puede_volver_a_agregar(self):
        ref = self.new()
        url = reverse("referencia", args=[ref["id"]])
        self.assertEqual(self.api.patch(url, {"variantes": []}, format="json").status_code, 200)
        response = self.api.patch(url, {"variantes": [{"talla": "30", "color": "Azul oscuro"}]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["variantes"]), 1)

    def test_variantes_invalidas_no_cambian_nada(self):
        ref = self.new()
        response = self.api.patch(
            reverse("referencia", args=[ref["id"]]),
            {"nombre": "Cambiado", "variantes": [{"talla": "30", "color": "A"}, {"talla": "30", "color": "a"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Referencia.objects.get().nombre, "Skinny 5 bolsillos")

    def test_una_referencia_activa_no_queda_sin_variantes(self):
        ref = self.new()
        self.activate(ref["id"])
        response = self.api.patch(reverse("referencia", args=[ref["id"]]), {"variantes": []}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("variantes", response.json())
        self.assertEqual(Variante.objects.count(), 1)

    def test_no_se_puede_cambiar_el_estado_por_patch(self):
        ref = self.new()
        self.api.patch(reverse("referencia", args=[ref["id"]]), {"estado": "ACTIVA"}, format="json")
        self.assertEqual(Referencia.objects.get().estado, catalog.DRAFT)


class StateTests(ReferenceBase):
    def test_activar_exige_variante_e_imagen(self):
        sin_variantes = self.new(nombre="Sin variantes", variantes=[])
        self.upload(sin_variantes["id"], image())
        response = self.set_state(sin_variantes["id"], catalog.ACTIVE)
        self.assertEqual(response.status_code, 400)
        self.assertIn("talla", response.json()["estado"][0])

        sin_imagen = self.new(nombre="Sin imagen")
        response = self.set_state(sin_imagen["id"], catalog.ACTIVE)
        self.assertEqual(response.status_code, 400)
        self.assertIn("imagen", response.json()["estado"][0])
        self.assertEqual(Referencia.objects.filter(estado=catalog.ACTIVE).count(), 0)

    def test_flujo_completo(self):
        ref = self.new()
        self.assertEqual(self.activate(ref["id"])["estado"], "ACTIVA")
        self.assertEqual(self.set_state(ref["id"], catalog.DISCONTINUED).json()["estado"], "DESCONTINUADA")
        self.assertEqual(self.set_state(ref["id"], catalog.ACTIVE).json()["estado"], "ACTIVA")

    def test_transiciones_no_permitidas(self):
        ref = self.new()
        for target in (catalog.DISCONTINUED, catalog.DRAFT):
            response = self.set_state(ref["id"], target)
            self.assertEqual(response.status_code, 400, target)
        self.activate(ref["id"])
        self.assertEqual(self.set_state(ref["id"], catalog.DRAFT).status_code, 400)
        self.assertEqual(self.set_state(ref["id"], catalog.ACTIVE).status_code, 400)  # ya está activa
        self.assertEqual(self.set_state(ref["id"], "INVENTADO").status_code, 400)

    def test_referencia_inexistente(self):
        self.assertEqual(self.set_state(999, catalog.ACTIVE).status_code, 404)


class ArchiveTests(ReferenceBase):
    def test_no_se_archiva_una_activa(self):
        ref = self.new()
        self.activate(ref["id"])
        response = self.api.delete(reverse("referencia", args=[ref["id"]]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Descontinúa", response.json()["estado"][0])
        self.assertTrue(Referencia.objects.filter(pk=ref["id"]).exists())

    def test_archivar_borrador_o_descontinuada_oculta_todo_y_libera_el_nombre(self):
        ref = self.new()
        self.upload(ref["id"], image())
        self.assertEqual(self.api.delete(reverse("referencia", args=[ref["id"]])).status_code, 204)
        self.assertFalse(Referencia.objects.exists())
        self.assertFalse(Variante.objects.exists())
        self.assertFalse(ImagenReferencia.objects.exists())
        self.assertEqual(Referencia.all_objects.count(), 1)  # borrado lógico, la fila sigue
        self.assertEqual(self.api.get(reverse("referencia", args=[ref["id"]])).status_code, 404)
        self.assertEqual(self.create().status_code, 201)  # el nombre quedó libre

        old = self.new(nombre="Vieja")
        self.activate(old["id"])
        self.set_state(old["id"], catalog.DISCONTINUED)
        self.assertEqual(self.api.delete(reverse("referencia", args=[old["id"]])).status_code, 204)


class ImageTests(ReferenceBase):
    def test_la_primera_queda_como_principal(self):
        ref = self.new()
        body = self.upload(ref["id"], image(), image(JPG, "b.jpg")).json()
        self.assertEqual(len(body["imagenes"]), 2)
        self.assertEqual([i["principal"] for i in body["imagenes"]], [True, False])
        self.assertEqual(body["imagen_principal"]["id"], body["imagenes"][0]["id"])
        self.assertEqual({i["tipo"] for i in body["imagenes"]}, {"image/png", "image/jpeg"})

    def test_acepta_webp_y_rechaza_otros_formatos_por_contenido(self):
        ref = self.new()
        self.assertEqual(self.upload(ref["id"], image(WEBP, "a.webp")).status_code, 201)
        for content, name in ((b"%PDF-1.4 hola", "x.pdf"), (b"texto plano", "falso.png"), (b"GIF89a....", "a.gif")):
            response = self.upload(ref["id"], image(content, name))
            self.assertEqual(response.status_code, 400, name)
            self.assertIn("JPG, PNG o WEBP", response.json()["imagen"][0])
        self.assertEqual(ImagenReferencia.objects.count(), 1)

    def test_rechaza_imagen_muy_pesada(self):
        ref = self.new()
        with mock.patch.object(catalog, "IMAGE_MAX_BYTES", 20):
            response = self.upload(ref["id"], image())
        self.assertEqual(response.status_code, 400)
        self.assertIn("pesa más de", response.json()["imagen"][0])

    def test_sin_archivo(self):
        ref = self.new()
        response = self.api.post(reverse("referencia_imagenes", args=[ref["id"]]), {}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("imagen", response.json())

    def test_maximo_de_imagenes(self):
        ref = self.new()
        self.assertEqual(self.upload(ref["id"], *[image() for _ in range(catalog.MAX_IMAGES)]).status_code, 201)
        response = self.upload(ref["id"], image())
        self.assertEqual(response.status_code, 400)
        self.assertIn("máximo", response.json()["imagen"][0])
        self.assertEqual(ImagenReferencia.objects.count(), catalog.MAX_IMAGES)

    def test_un_lote_que_se_pasa_del_maximo_no_guarda_ninguna(self):
        ref = self.new()
        self.upload(ref["id"], *[image() for _ in range(4)])
        self.assertEqual(self.upload(ref["id"], image(), image()).status_code, 400)
        self.assertEqual(ImagenReferencia.objects.count(), 4)

    def test_un_lote_con_un_archivo_malo_no_guarda_ninguna(self):
        ref = self.new()
        self.assertEqual(self.upload(ref["id"], image(), image(b"nada", "x.png")).status_code, 400)
        self.assertEqual(ImagenReferencia.objects.count(), 0)

    def test_cambiar_la_principal(self):
        ref = self.new()
        images = self.upload(ref["id"], image(), image(JPG, "b.jpg")).json()["imagenes"]
        second = images[1]["id"]
        body = self.api.post(reverse("referencia_imagen_principal", args=[second])).json()
        self.assertEqual(body["imagen_principal"]["id"], second)
        self.assertEqual(sum(i["principal"] for i in body["imagenes"]), 1)

    def test_quitar_la_principal_promueve_la_siguiente(self):
        ref = self.new()
        images = self.upload(ref["id"], image(), image(JPG, "b.jpg")).json()["imagenes"]
        body = self.api.delete(reverse("referencia_imagen", args=[images[0]["id"]])).json()
        self.assertEqual(len(body["imagenes"]), 1)
        self.assertEqual(body["imagen_principal"]["id"], images[1]["id"])
        self.assertTrue(body["imagenes"][0]["principal"])

    def test_quitar_una_secundaria_no_cambia_la_principal(self):
        ref = self.new()
        images = self.upload(ref["id"], image(), image(JPG, "b.jpg")).json()["imagenes"]
        body = self.api.delete(reverse("referencia_imagen", args=[images[1]["id"]])).json()
        self.assertEqual(body["imagen_principal"]["id"], images[0]["id"])

    def test_la_ultima_imagen_de_una_activa_no_se_quita(self):
        ref = self.new()
        self.activate(ref["id"])
        only = Referencia.objects.get().imagenes.get().id
        response = self.api.delete(reverse("referencia_imagen", args=[only]))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ImagenReferencia.objects.count(), 1)

    def test_si_borrador_puede_quedarse_sin_imagenes(self):
        ref = self.new()
        only = self.upload(ref["id"], image()).json()["imagenes"][0]["id"]
        self.assertEqual(self.api.delete(reverse("referencia_imagen", args=[only])).status_code, 200)

    def test_descarga_con_etag(self):
        ref = self.new()
        img = self.upload(ref["id"], image(JPG, "b.jpg")).json()["imagenes"][0]
        url = reverse("referencia_imagen", args=[img["id"]])
        response = self.api.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, JPG)
        self.assertEqual(self.api.get(url, HTTP_IF_NONE_MATCH=response["ETag"]).status_code, 304)

    def test_imagen_inexistente_o_quitada(self):
        ref = self.new()
        img = self.upload(ref["id"], image()).json()["imagenes"][0]["id"]
        self.api.delete(reverse("referencia_imagen", args=[img]))
        self.assertEqual(self.api.get(reverse("referencia_imagen", args=[img])).status_code, 404)
        self.assertEqual(self.upload(9999, image()).status_code, 404)


class PermissionTests(ReferenceBase):
    def test_sin_sesion(self):
        from rest_framework.test import APIClient

        anon = APIClient()
        self.assertEqual(anon.get(reverse("referencias")).status_code, 401)
        self.assertEqual(anon.post(reverse("referencias"), {}, format="json").status_code, 401)

    def test_quien_solo_consulta_no_modifica(self):
        ref = self.new()
        img = self.upload(ref["id"], image()).json()["imagenes"][0]["id"]
        seller = client_for(make_user("ventas@t.co", "VENDEDOR"))
        self.assertEqual(seller.get(reverse("referencias")).status_code, 200)
        self.assertEqual(seller.get(reverse("referencia", args=[ref["id"]])).status_code, 200)
        self.assertEqual(seller.get(reverse("referencia_imagen", args=[img])).status_code, 200)
        self.assertEqual(seller.get(reverse("referencias_metadatos")).status_code, 200)
        writes = [
            seller.post(reverse("referencias"), {"nombre": "X", "ajuste": "SLIM"}, format="json"),
            seller.patch(reverse("referencia", args=[ref["id"]]), {"nombre": "Y"}, format="json"),
            seller.delete(reverse("referencia", args=[ref["id"]])),
            seller.post(reverse("referencia_estado", args=[ref["id"]]), {"estado": "ACTIVA"}, format="json"),
            self.upload(ref["id"], image(), client=seller),
            seller.post(reverse("referencia_imagen_principal", args=[img])),
            seller.delete(reverse("referencia_imagen", args=[img])),
        ]
        self.assertEqual([r.status_code for r in writes], [403] * len(writes))
        self.assertEqual(Referencia.objects.get().nombre, "Skinny 5 bolsillos")

    def test_un_rol_sin_el_permiso_no_ve_el_catalogo(self):
        ref = self.new()
        finisher = client_for(make_user("terminacion@t.co", "TERMINACION"))
        self.assertEqual(finisher.get(reverse("referencias")).status_code, 403)
        self.assertEqual(finisher.get(reverse("referencia", args=[ref["id"]])).status_code, 403)

    def test_el_administrador_puede_todo(self):
        admin = client_for(make_user("admin@t.co", "ADMIN"))
        response = admin.post(reverse("referencias"), {"nombre": "Admin", "ajuste": "RECTO"}, format="json")
        self.assertEqual(response.status_code, 201)

    def test_permisos_iniciales_por_rol(self):
        def granted(role):
            return set(Role.objects.get(code=role).permissions.values_list("code", flat=True)) & {
                catalog.REFERENCES_VIEW, catalog.REFERENCES_MANAGE,
            }

        both = {catalog.REFERENCES_VIEW, catalog.REFERENCES_MANAGE}
        self.assertEqual(granted("PRODUCCION"), both)
        for role in ("GERENTE", "ALMACENISTA", "VENDEDOR"):
            self.assertEqual(granted(role), {catalog.REFERENCES_VIEW}, role)
        for role in ("TERMINACION", "SECRETARIA", "PENDING"):
            self.assertEqual(granted(role), set(), role)
        self.assertEqual(ModulePermission.objects.filter(module="referencias").count(), 2)


class MetadataTests(ReferenceBase):
    def test_entrega_los_valores_del_formulario(self):
        body = self.api.get(reverse("referencias_metadatos")).json()
        self.assertIn({"value": "SKINNY", "label": "Skinny"}, body["ajustes"])
        self.assertEqual([e["value"] for e in body["estados"]], ["BORRADOR", "ACTIVA", "DESCONTINUADA"])
        self.assertEqual(body["max_imagenes"], catalog.MAX_IMAGES)
        self.assertEqual(body["imagen_max_bytes"], catalog.IMAGE_MAX_BYTES)
        self.assertEqual(body["max_variantes"], catalog.MAX_VARIANTS)
