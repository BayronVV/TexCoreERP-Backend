"""
Genera el Modelo Entidad-Relación (MER) en notación de Chen a partir de los modelos de Django.

    python manage.py generar_mer --dot-dir <carpeta>      # escribe un .dot por figura
    python manage.py generar_mer --figura mer-general     # imprime el DOT de una figura

Es el nivel conceptual del modelo de datos: entidades (rectángulos), relaciones (rombos),
atributos (óvalos, con el identificador subrayado) y cardinalidades 1 / N sobre las líneas.
Las entidades débiles llevan rectángulo de doble borde y su relación identificadora, rombo de
doble borde. Las tablas puramente asociativas se dibujan como rombo N:M con sus atributos
colgando del rombo. El esquema físico (columnas y llaves) lo genera `generar_erd`.

La salida es texto DOT determinista. Graphviz no es dependencia del proyecto: las imágenes
(SVG/PNG) se renderizan fuera, p. ej. con @hpcc-js/wasm-graphviz (ver `docs/modelo-de-datos.md`).
La primera línea de cada .dot (`// layout: <motor>`) indica el motor de Graphviz recomendado.
"""
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import models

from apps.core.management.commands.generar_erd import (
    MODULES, own_fields, module_of, module_titles, project_models,
)

USER_MODEL = "CustomUser"
SECURITY_MODULE = "seguridad"
MAX_ATTRS = 8

# Tablas puramente asociativas: se dibujan como rombo N:M (o ternario) entre las entidades que unen.
# modelo -> (verbo de la relación, {campo FK: cardinalidad en esa punta})
ASSOCIATIVE = {
    "RolePermission": ("Otorga", {"role": "N", "permission": "M"}),
    "RemisionLote": ("Se envía en", {"remision": "N", "lote": "M", "receta": "1"}),
    "RecepcionLote": ("Se recibe conforme en", {"recepcion": "N", "lote": "M"}),
    "AsignacionEtapa": ("Se asigna a", {"etapa_lote": "N", "operario": "M", "maquina": "P"}),
}
# Claves foráneas que ya no se dibujan porque su destino es un rombo (relación derivada de otra).
ABSORBED = {
    ("RecepcionLote", "remision_lote"): "RemisionLote es un rombo; la recepción ya enlaza remisión y lote",
    ("Inspeccion", "recepcion_lote"): "RecepcionLote es un rombo; la inspección se enlaza con el lote",
}
# Entidades débiles: no existen sin su cabecera. modelo -> campo FK de la entidad propietaria.
WEAK = {
    "OrdenLinea": "orden", "FichaLinea": "ficha", "LoteTalla": "lote", "EventoEtapa": "etapa_lote",
    "LineaCompra": "orden", "RecepcionLinea": "recepcion", "MarraDetalle": "inspeccion",
    "IngresoLinea": "ingreso", "AjusteLinea": "ajuste", "DetalleVenta": "factura", "EventoGuia": "guia",
}
# Nombre curado (verbo en español) de cada clave foránea entre entidades de negocio:
# (modelo que guarda la FK, campo) -> verbo. Cardinalidad: 1 en el lado referenciado, N en el que guarda la FK.
RELATION_NAMES = {
    ("CustomUser", "role"): "Agrupa",
    ("CustomUser", "requested_area"): "Es solicitado por",
    ("AccessLog", "user"): "Genera",
    ("PasswordResetToken", "user"): "Solicita",
    ("OrdenSalida", "referencia"): "Se prepara para",
    ("OrdenSalida", "producto_resultado"): "Resulta en",
    ("OrdenLinea", "orden"): "Detalla",
    ("OrdenLinea", "producto"): "Se consume en",
    ("Movimiento", "producto"): "Registra",
    ("Movimiento", "proveedor"): "Suministra",
    ("Movimiento", "orden"): "Descarga",
    ("Evidencia", "movimiento"): "Se soporta con",
    ("Evidencia", "orden"): "Se evidencia con",
    ("Variante", "referencia"): "Tiene",
    ("ImagenReferencia", "referencia"): "Se ilustra con",
    ("FichaTecnica", "referencia"): "Se describe en",
    ("FichaLinea", "ficha"): "Lista",
    ("FichaLinea", "producto"): "Se usa en",
    ("OrdenProduccion", "orden_salida"): "Abastece",
    ("OrdenProduccion", "referencia"): "Se fabrica en",
    ("Lote", "orden"): "Se divide en",
    ("LoteTalla", "lote"): "Se desglosa en",
    ("LoteTalla", "variante"): "Se cuenta en",
    ("EtapaLote", "lote"): "Pasa por",
    ("EventoEtapa", "etapa_lote"): "Registra",
    ("RemisionLavanderia", "lavanderia"): "Procesa",
    ("RecepcionLavanderia", "remision"): "Se recepciona en",
    ("OrdenCompra", "proveedor"): "Surte",
    ("LineaCompra", "orden"): "Pide",
    ("LineaCompra", "producto"): "Se pide en",
    ("Recepcion", "orden"): "Se recibe mediante",
    ("Recepcion", "proveedor"): "Entrega",
    ("RecepcionLinea", "recepcion"): "Contiene",
    ("RecepcionLinea", "linea_compra"): "Se cumple con",
    ("RecepcionLinea", "producto"): "Se recibe en",
    ("RecepcionLinea", "movimiento"): "Origina",
    ("Inspeccion", "lote"): "Se inspecciona en",
    ("MarraDetalle", "inspeccion"): "Detecta",
    ("MarraDetalle", "tipo_defecto"): "Clasifica",
    ("StockTerminado", "variante"): "Se almacena en",
    ("IngresoTerminado", "inspeccion"): "Aprueba",
    ("IngresoTerminado", "lote"): "Ingresa a bodega",
    ("IngresoLinea", "ingreso"): "Incluye",
    ("IngresoLinea", "variante"): "Ingresa en",
    ("AjusteLinea", "ajuste"): "Corrige",
    ("AjusteLinea", "variante"): "Se ajusta en",
    ("MovimientoTerminado", "variante"): "Se mueve en",
    ("MovimientoTerminado", "ingreso"): "Origina",
    ("MovimientoTerminado", "ajuste"): "Genera",
    ("MovimientoTerminado", "factura"): "Despacha",
    ("MovimientoTerminado", "lote"): "Rastrea",
    ("PrecioReferencia", "referencia"): "Tiene precio",
    ("FacturaVenta", "cliente"): "Compra",
    ("DetalleVenta", "factura"): "Contiene",
    ("DetalleVenta", "variante"): "Se vende en",
    ("MovimientoCartera", "factura"): "Afecta cartera",
    ("Guia", "factura"): "Se envía con",
    ("Guia", "relacion"): "Agrupa",
    ("EventoGuia", "guia"): "Registra",
}

# Figuras: (nombre de archivo, título, módulo, modelos propios o None = todo el módulo, motor de Graphviz)
SPLITS = {
    "produccion": [
        ("fabricacion", "Fabricación: órdenes, lotes, etapas y recursos",
         ("OrdenProduccion", "Lote", "LoteTalla", "EtapaLote", "EventoEtapa", "TarifaManoObra", "Operario",
          "Maquina", "AsignacionEtapa")),
        ("lavanderia", "Lavandería: recetas, remisiones y recepciones",
         ("RecetaLavado", "RemisionLavanderia", "RemisionLote", "RecepcionLavanderia", "RecepcionLote")),
    ],
}

# Atributos: prioridad por nombre (menor = antes). El resto va después, en el orden del modelo.
ATTR_BLACKLIST = {
    "password", "last_login", "is_superuser", "is_staff", "token_hash", "token", "forwarded", "user_agent",
    "rastreo_respuesta", "rastreo_sintetico", "rastreo_registrado", "rastreo_consultado_en",
    "rastreo_proxima_consulta", "imagen_tipo", "imagen_version", "documento_version", "documento_tamano",
    "documento_nombre", "content_type", "nombre_original", "tamano", "version", "requested_ip", "ip",
    "date_joined", "first_name", "last_name", "nit_dv", "dv", "ubicacion_x",
}
NAME_PRIORITY = [
    ("codigo", 1), ("numero", 1), ("nit", 1), ("username", 1), ("email", 1), ("correo", 3), ("documento", 3),
    ("document_id", 1), ("clave", 1), ("code", 1),
    ("nombre", 2), ("name", 2), ("razon_social", 2), ("nombres", 2), ("descripcion", 3), ("description", 3),
    ("talla", 3), ("color", 3), ("etapa", 3), ("tipo", 4), ("categoria", 4), ("event", 4), ("accion", 4),
    ("estado", 4), ("unidad", 5), ("purpose", 5),
    ("cantidad", 6), ("stock", 6), ("total", 6), ("subtotal", 6), ("monto", 6), ("costo", 6), ("precio", 6),
    ("saldo", 6), ("valor", 6), ("diferencia", 6), ("aptas", 6), ("marras", 6), ("peso", 6), ("ultimo", 6),
    ("fecha", 7), ("momento", 7), ("granted_at", 7), ("expires_at", 7), ("inicio", 7), ("fin", 7),
]


def _priority(name):
    for key, level in NAME_PRIORITY:
        if name == key:
            return level
    for key, level in NAME_PRIORITY:
        if name.startswith(key):
            return level + 0.5
    return 9


def main_attributes(model, limit=MAX_ATTRS):
    """Atributos principales: (nombre, es_llave). Sin FK ni columnas de auditoría; llave primaria primero."""
    plain = [f for f in own_fields(model) if not isinstance(f, models.ForeignKey) and f.name not in ATTR_BLACKLIST]
    ranked = sorted(enumerate(plain), key=lambda item: (0 if item[1].primary_key else _priority(item[1].name), item[0]))
    chosen = sorted(ranked[:limit], key=lambda item: item[0])  # se muestran en el orden del modelo
    return [(f.name, f.primary_key) for _i, f in chosen]


def assoc_attributes(model):
    """Atributos de un rombo N:M: todos los propios de negocio salvo `id` (máximo MAX_ATTRS)."""
    plain = [f for f in own_fields(model)
             if not isinstance(f, models.ForeignKey) and not f.primary_key and f.name not in ATTR_BLACKLIST]
    ranked = sorted(enumerate(plain), key=lambda item: (_priority(item[1].name), item[0]))
    return [f.name for _i, f in sorted(ranked[:MAX_ATTRS], key=lambda item: item[0])]


# ----------------------------------------------------------------------------------------- relaciones
def is_associative(model):
    return model.__name__ in ASSOCIATIVE


def keeps_link(source, target):
    """Una FK se dibuja salvo que apunte a seguridad desde otro módulo (quién creó/registró algo)."""
    return not (module_of(target) == SECURITY_MODULE and module_of(source) != SECURITY_MODULE)


def business_foreign_keys(model, models_):
    """FK de `model` que se dibujan: (campo, destino). Excluye usuario/seguridad ajenos y las absorbidas."""
    for field in model._meta.concrete_fields:
        if not isinstance(field, models.ForeignKey) or field.related_model not in models_:
            continue
        target = field.related_model
        if (model.__name__, field.name) in ABSORBED or not keeps_link(model, target):
            continue
        yield field, target


def relations(models_):
    """
    Relaciones del MER: lista de dicts {id, name, kind, ends, attrs, owner, identifying}.
    `ends` = [(entidad, cardinalidad)]. Las binarias 1:N salen de una FK; las asociativas, de la tabla.
    """
    found = []
    for model in models_:
        name = model.__name__
        if is_associative(model):
            verb, cards = ASSOCIATIVE[name]
            ends = [(f.related_model.__name__, cards[f.name]) for f in model._meta.concrete_fields
                    if isinstance(f, models.ForeignKey) and f.name in cards and keeps_link(model, f.related_model)]
            found.append({"id": f"r_{name}", "name": verb, "kind": "nm", "ends": ends,
                          "attrs": assoc_attributes(model), "owner": name, "identifying": False})
            continue
        for field, target in business_foreign_keys(model, models_):
            if is_associative(target):
                continue
            verb = RELATION_NAMES.get((name, field.name)) or derived_name(name, field.name)
            one_to_one = field.unique
            weak = WEAK.get(name) == field.name
            found.append({
                "id": f"r_{name}_{field.name}", "name": verb, "kind": "1n",
                "ends": [(target.__name__, "1"), (name, "1" if one_to_one else "N")],
                "attrs": [], "owner": name, "identifying": weak,
            })
    return found


def derived_name(model_name, field_name):
    """Respaldo cuando una FK no tiene nombre curado (la prueba avisa para que se agregue)."""
    return field_name.replace("_", " ").capitalize()


def entities(models_):
    return [m for m in models_ if not is_associative(m)]


# ----------------------------------------------------------------------------------------------- DOT
def esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def label_html(name, key=False):
    return f"<<U>{esc(name)}</U>>" if key else f'"{esc(name)}"'


NODE_DEFAULTS = 'fontname="Arial", fontsize=11'


MODULE_COLORS = {
    "seguridad": "#fecaca", "inventario": "#bfdbfe", "compras": "#fed7aa", "referencias": "#bbf7d0",
    "produccion": "#ddd6fe", "calidad": "#fde68a", "terminado": "#a5f3fc", "ventas": "#fbcfe8", "envios": "#d9f99d",
}


def entity_node(model, grey=False, by_module=False):
    name = model.__name__
    attrs = ['shape=box', 'style="filled"', f'label="{name}"', 'fontsize=13', 'penwidth=1.6']
    fill = MODULE_COLORS.get(module_of(model), "#dbeafe") if by_module else "#dbeafe"
    attrs.append('fillcolor="#e5e7eb"' if grey else f'fillcolor="{fill}"')
    if grey:
        attrs.append('color="#6b7280"')
        attrs.append('fontcolor="#4b5563"')
    else:
        attrs.append('color="#1d4ed8"')
    if name in WEAK:
        attrs.append("peripheries=2")
    return f'  e_{name} [{", ".join(attrs)}];'


def relation_node(rel):
    attrs = ["shape=diamond", 'style="filled"', 'fillcolor="#fef3c7"', 'color="#b45309"', f'label="{esc(rel["name"])}"',
             "fontsize=11", "penwidth=1.4"]
    if rel["identifying"]:
        attrs.append("peripheries=2")
    return f'  {rel["id"]} [{", ".join(attrs)}];'


def attribute_nodes(owner_id, owner_key, attrs, weak=False, length=1.15):
    lines = []
    for number, item in enumerate(attrs):
        name, key = item if isinstance(item, tuple) else (item, False)
        node = f"a_{owner_key}_{name}"
        shape = "ellipse"
        lines.append(f'  {node} [shape={shape}, style="filled", fillcolor="#ffffff", color="#475569", '
                     f'fontsize=9, margin="0.04,0.02", label={label_html(name, key)}];')
        lines.append(f'  {owner_id} -- {node} [color="#94a3b8", penwidth=0.8, len={length}];')
    return lines


def edge_lines(rel):
    """Líneas rombo-entidad con la cardinalidad escrita junto a la entidad."""
    width = "2.4" if rel["identifying"] else "1.2"
    return [f'  {rel["id"]} -- e_{entity} [headlabel="{card}", labeldistance=2.2, labelangle=20, fontsize=12, '
            f'fontcolor="#b91c1c", color="#334155", len=2.0, penwidth={width}];' for entity, card in rel["ends"]]


def build_dot(figure, models_):
    """DOT de una figura. figure = {"name", "title", "own": [modelos], "with_attrs": bool, "layout": motor}."""
    by_name = {m.__name__: m for m in models_}
    own = figure["own"]
    own_names = {m.__name__ for m in own}
    all_rel = relations(models_)
    rels = [r for r in all_rel if any(e in own_names or r["owner"] in own_names for e, _c in r["ends"])]
    if figure.get("own_only"):
        rels = [r for r in rels if r["owner"] in own_names or all(e in own_names for e, _c in r["ends"])]
    ent_names = []
    for r in rels:
        for e, _c in r["ends"]:
            if e not in ent_names:
                ent_names.append(e)
    for m in own:
        if m.__name__ not in ent_names and not is_associative(m):
            ent_names.append(m.__name__)
    order = {m.__name__: i for i, m in enumerate(models_)}
    ent_names.sort(key=lambda n: order[n])
    layout = figure["layout"]
    lines = [f"// layout: {layout}", f'graph "{figure["name"]}" {{',
             f'  layout={layout}; fontname="Arial"; bgcolor="white"; pad=0.4;',
             f'  node [{NODE_DEFAULTS}]; edge [fontname="Arial"];']
    for extra in figure.get("graph", []):
        lines.append(f"  {extra};")
    by_module = figure.get("by_module", False)
    for n in ent_names:
        lines.append(entity_node(by_name[n], grey=n not in own_names, by_module=by_module))
    if by_module:
        titles = module_titles(models_)
        rows = "".join(f'<TR><TD BGCOLOR="{MODULE_COLORS[k]}" WIDTH="22"> </TD><TD ALIGN="LEFT">{esc(t)}</TD></TR>'
                       for k, t in titles.items())
        lines.append(f'  leyenda [shape=plaintext, label=<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" '
                     f'CELLPADDING="6"><TR><TD COLSPAN="2"><B>Módulos</B></TD></TR>{rows}</TABLE>>];')
    for rel in rels:
        lines.append(relation_node(rel))
    for rel in rels:
        lines += edge_lines(rel)
    if figure["with_attrs"]:
        limit = figure.get("max_attrs", MAX_ATTRS)
        length = figure.get("attr_len", 1.15)
        for n in ent_names:
            if n in own_names:
                lines += attribute_nodes(f"e_{n}", n, main_attributes(by_name[n], limit), length=length)
        for rel in rels:
            if rel["kind"] == "nm" and rel["owner"] in own_names and rel["attrs"]:
                lines += attribute_nodes(rel["id"], rel["owner"], rel["attrs"][:limit], length=length)
    lines.append("}")
    return "\n".join(lines) + "\n"


def figures(models_):
    """Todas las figuras del MER: [{name, title, module, own, with_attrs, layout, ...}], en orden estable."""
    titles = module_titles(models_)
    result = [{"name": "mer-general", "title": "MER general (sin atributos)", "module": None,
               "own": list(models_), "with_attrs": False, "layout": "neato", "by_module": True,
               "graph": ["overlap=prism", "sep=\"+6\"", "splines=true"]},
              {"name": "mer-general-atributos", "title": "MER general con atributos principales", "module": None,
               "own": list(models_), "with_attrs": True, "layout": "neato", "by_module": True,
               "max_attrs": 4, "attr_len": 0.9,
               "graph": ["overlap=prism", "sep=\"+3\"", "splines=true"]}]
    for key, title in titles.items():
        in_module = [m for m in models_ if module_of(m) == key]
        parts = SPLITS.get(key)
        if parts:
            for suffix, part_title, names in parts:
                own = [m for m in in_module if m.__name__ in names]
                result.append(_module_figure(f"mer-{key}-{suffix}", f"{title}: {part_title}", key, own))
        else:
            result.append(_module_figure(f"mer-{key}", title, key, in_module))
    return result


def _module_figure(name, title, key, own):
    return {"name": name, "title": title, "module": key, "own": own, "with_attrs": True, "layout": "neato",
            "graph": ["overlap=prism", "sep=\"+14\"", "splines=true"]}


def all_dots(models_=None):
    models_ = models_ or project_models()
    return {fig["name"]: build_dot(fig, models_) for fig in figures(models_)}


class Command(BaseCommand):
    """Comando de gestión: emite el MER (notación de Chen) como texto DOT de Graphviz."""
    help = "Genera el Modelo Entidad-Relación en notación de Chen (DOT de Graphviz)."

    def add_arguments(self, parser):
        parser.add_argument("--dot-dir", help="Carpeta donde escribir un .dot por figura.")
        parser.add_argument("--figura", help="Nombre de una figura (p. ej. mer-general) para imprimir su DOT.")

    def handle(self, *args, **options):
        dots = all_dots()
        folder = options.get("dot_dir")
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            for name, text in dots.items():
                (Path(folder) / f"{name}.dot").write_text(text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"{len(dots)} figuras DOT escritas en {folder}"))
        elif options.get("figura"):
            self.stdout.write(dots[options["figura"]])
        else:
            self.stdout.write("Figuras disponibles: " + ", ".join(dots))
