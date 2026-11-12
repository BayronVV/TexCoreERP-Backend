"""
Genera la documentación del modelo de datos a partir de los modelos de Django.

    python manage.py generar_erd                    # imprime el Markdown
    python manage.py generar_erd --salida docs/modelo-de-datos.md

Los diagramas del esquema físico (pata de gallo) salen en Mermaid (GitHub y MkDocs lo dibujan solos),
así que no hace falta instalar Graphviz. Ejecútalo de nuevo cuando cambie un modelo.

Cuatro niveles de lectura: MER en notación de Chen (lo genera `generar_mer`), mapa general,
diagrama físico de cada módulo (con columnas) y tablas de detalle por modelo; más las vistas materializadas de reportes.
Con --mermaid-dir se vuelcan los diagramas como archivos .mmd para convertirlos a imagen
(SVG/PNG) con mermaid-cli; el Markdown ya referencia esas imágenes en docs/img/.
"""
import importlib
import re
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models

from apps.reports import catalog

PROJECT_APPS = ("core", "users", "inventory", "references", "production", "purchasing", "quality", "finished", "sales", "shipping")
IMG_DIR = "img"  # relativo a docs/; ahí viven las imágenes del modelo gráfico

# (identificador, nombre en español, apps de Django que lo forman)
MODULES = [
    ("seguridad", "Usuarios y seguridad", ("core", "users")),
    ("inventario", "Inventario", ("inventory",)),
    ("compras", "Compras", ("purchasing",)),
    ("referencias", "Referencias", ("references",)),
    ("produccion", "Producción y lavandería", ("production",)),
    ("calidad", "Calidad", ("quality",)),
    ("terminado", "Producto terminado", ("finished",)),
    ("ventas", "Ventas y cartera", ("sales",)),
    ("envios", "Envíos", ("shipping",)),
]
REPORT_MIGRATION = "apps.reports.migrations.0001_vistas_materializadas"
REPORT_VIEWS = ((catalog.MV_PRODUCTION_SUMMARY, "PRODUCTION_QUERY"), (catalog.MV_SALES_BY_REFERENCE, "SALES_QUERY"))
USER_MODEL = "CustomUser"  # lo referencian casi todos los módulos (responsables); se omite en mapas y diagramas por módulo
AUDIT_FIELDS = {"created_at", "updated_at", "deleted_at"}  # los trae BaseModel

MERMAID_TYPES = {
    "AutoField": "int", "BigAutoField": "bigint", "IntegerField": "int", "BigIntegerField": "bigint",
    "PositiveIntegerField": "int", "SmallIntegerField": "smallint", "CharField": "varchar",
    "TextField": "text", "EmailField": "varchar", "BooleanField": "boolean",
    "DateField": "date", "DateTimeField": "timestamp", "DecimalField": "decimal",
    "BinaryField": "bytea", "FileField": "varchar", "ImageField": "varchar", "SlugField": "varchar",
    "UUIDField": "uuid", "GenericIPAddressField": "inet", "JSONField": "json", "FloatField": "float",
}


def project_models():
    found = []
    for label in PROJECT_APPS:
        config = apps.get_app_config(label)
        found += [m for m in config.get_models() if not m._meta.auto_created]
    return found


def column_type(field):
    if isinstance(field, models.ForeignKey):
        return column_type(field.target_field)
    name = type(field).__name__
    base = MERMAID_TYPES.get(name, name.replace("Field", "").lower() or "text")
    if isinstance(field, models.CharField) and field.max_length:
        return f"{base}({field.max_length})"
    if isinstance(field, models.DecimalField):
        return f"{base}({field.max_digits},{field.decimal_places})"
    return base


def mermaid_type(field):
    # En Mermaid el tipo no admite paréntesis ni comas.
    return column_type(field).replace("(", "_").replace(")", "").replace(",", "_")


def constraints(field):
    marks = []
    if field.primary_key:
        marks.append("PK")
    if isinstance(field, models.ForeignKey):
        marks.append("FK")
    if field.unique and not field.primary_key:
        marks.append("UK")
    return marks


def own_fields(model):
    for field in model._meta.concrete_fields:
        if field.name in AUDIT_FIELDS:
            continue
        yield field




def module_of(model):
    for key, _title, labels in MODULES:
        if model._meta.app_label in labels:
            return key
    return "otros"


def module_titles(models_):
    titles = {key: title for key, title, _labels in MODULES}
    if any(module_of(m) == "otros" for m in models_):
        titles["otros"] = "Otros"
    return titles


def foreign_keys(model, models_):
    """Claves foráneas de `model` hacia tablas del proyecto: (campo, modelo destino)."""
    for field in model._meta.concrete_fields:
        if isinstance(field, models.ForeignKey) and field.related_model in models_:
            yield field, field.related_model


def is_user_link(source, target):
    """Relación con el usuario (responsable, creador...) desde otro módulo: se omite de los mapas por legibilidad."""
    return USER_MODEL in (source.__name__, target.__name__) and module_of(source) != module_of(target)


def relation_line(field, target, source):
    left = "|o" if field.null else "||"
    return f'    {target.__name__} {left}--o{{ {source.__name__} : "{field.name}"'


def entity_block(model, only_pk=False):
    lines = [f"    {model.__name__} {{"]
    for field in own_fields(model):
        if only_pk and not field.primary_key:
            continue
        marks = ", ".join(constraints(field))
        lines.append(f"        {mermaid_type(field)} {field.name}" + (f" {marks}" if marks else ""))
    lines.append("    }")
    return lines


def full_erd(models_):
    lines = ["erDiagram"]
    relations = set()
    for model in models_:
        lines += entity_block(model)
        relations |= {relation_line(f, t, model) for f, t in foreign_keys(model, models_)}
    return lines + sorted(relations)


def module_map(models_):
    """Mapa de módulos: un nodo por módulo y una flecha por par con dependencia por clave foránea."""
    titles = module_titles(models_)
    counts = {}
    for model in models_:
        for _field, target in foreign_keys(model, models_):
            if module_of(target) != module_of(model) and not is_user_link(model, target):
                pair = (module_of(target), module_of(model))
                counts[pair] = counts.get(pair, 0) + 1
    lines = ["flowchart TB"]
    for key, title in titles.items():
        total = sum(1 for m in models_ if module_of(m) == key)
        lines.append(f'    m_{key}["{title}<br/>({total} tablas)"]')
    for (source, target), number in sorted(counts.items()):
        label = "1 relación" if number == 1 else f"{number} relaciones"
        lines.append(f'    m_{source} -->|"{label}"| m_{target}')
    return lines


def general_map(models_):
    """Mapa general: solo entidades y relaciones, agrupadas por módulo."""
    titles = module_titles(models_)
    lines = ["flowchart TB"]
    for key, title in titles.items():
        lines.append(f'    subgraph sg_{key}["{title}"]')
        lines += [f"        {m.__name__}" for m in models_ if module_of(m) == key]
        lines.append("    end")
    edges = set()
    for model in models_:
        for _field, target in foreign_keys(model, models_):
            if target is not model and not is_user_link(model, target):
                edges.add(f"    {target.__name__} --> {model.__name__}")
    return lines + sorted(edges)


def module_erd(key, models_):
    """Diagrama de un módulo: sus tablas con columnas y las externas (solo clave) con las que se relaciona."""
    own = [m for m in models_ if module_of(m) == key]
    relations, external = set(), []
    for model in models_:
        for field, target in foreign_keys(model, models_):
            if (module_of(model) != key and module_of(target) != key) or is_user_link(model, target):
                continue
            relations.add(relation_line(field, target, model))
            for other in (model, target):
                if module_of(other) != key and other not in external:
                    external.append(other)
    lines = ["erDiagram"]
    for model in own:
        lines += entity_block(model)
    for model in external:
        lines += entity_block(model, only_pk=True)
    return lines + sorted(relations), own, external


def report_views(models_):
    """Vistas materializadas de reportes: nombre, columnas (leídas del SQL de la migración) y tablas fuente."""
    migration = importlib.import_module(REPORT_MIGRATION)
    table_names = {m._meta.db_table: m.__name__ for m in models_}
    view_models = {m._meta.db_table: m for m in apps.get_app_config("reports").get_models()}
    result = []
    for view, query_name in REPORT_VIEWS:
        query = getattr(migration, query_name)
        columns = []
        for line in query.splitlines():
            if line.startswith("FROM"):
                break
            match = re.match(r"^ {4}\S.*\bAS (\w+),?$", line)
            if match:
                columns.append(match.group(1))
        sources = []
        for table in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", query):
            if table not in sources:
                sources.append(table)
        view_model = view_models.get(view)
        types = {}
        if view_model:
            types = {f.name: column_type(f) for f in view_model._meta.concrete_fields}
        doc = (view_model.__doc__ or "").strip().splitlines()[0] if view_model and view_model.__doc__ else ""
        result.append({
            "name": view,
            "doc": doc,
            "columns": [(c, types.get(c, "")) for c in columns],
            "sources": [(t, table_names.get(t, "")) for t in sources],
        })
    return result


def views_diagram(views):
    lines = ["flowchart LR"]
    for number, view in enumerate(views):
        lines.append(f'    v{number}[("{view["name"]}")]')
        for table, model in view["sources"]:
            lines.append(f'    t_{table}["{model or table}"] --> v{number}')
    return lines


class Command(BaseCommand):
    """Comando de gestión: genera el modelo de datos (mapa general, diagramas por módulo, vistas de reportes y tablas) en Markdown."""
    help = "Genera el modelo de datos (diagramas Mermaid y tablas de campos) en Markdown."

    def add_arguments(self, parser):
        parser.add_argument("--salida", help="Archivo .md de destino; sin él se imprime.")
        parser.add_argument(
            "--mermaid-dir",
            help="Carpeta donde volcar cada diagrama como .mmd (para convertirlo a SVG/PNG con mermaid-cli).",
        )

    def handle(self, *args, **options):
        models_ = project_models()
        text = self.render(models_)
        target = options.get("salida")
        if target:
            Path(target).write_text(text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Modelo de datos escrito en {target}"))
        else:
            self.stdout.write(text)
        folder = options.get("mermaid_dir")
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            for name, lines in self.diagrams(models_).items():
                (Path(folder) / f"{name}.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Diagramas Mermaid escritos en {folder}"))

    def diagrams(self, models_):
        """Diagramas que tienen imagen: {nombre de archivo sin extensión: líneas Mermaid}."""
        found = {"mapa-modulos": module_map(models_), "mapa-general": general_map(models_)}
        for key in module_titles(models_):
            found[f"modulo-{key}"] = module_erd(key, models_)[0]
        return found

    def render(self, models_):
        titles = module_titles(models_)
        lines = [
            "# Modelo de datos",
            "",
            "> Generado automáticamente con `python manage.py generar_erd --salida docs/modelo-de-datos.md`.",
            "> No lo edites a mano: vuelve a generarlo cuando cambie un modelo.",
            "",
            f"El modelo tiene **{len(models_)} tablas** de negocio en {len(titles)} módulos, más dos vistas "
            "materializadas de reportes. Todas las tablas de negocio heredan de `BaseModel` y por eso incluyen además "
            "`created_at`, `updated_at` y `deleted_at` (borrado lógico; ver "
            "[convenciones de base de datos](convenciones-base-de-datos.md)). Esas columnas no se repiten abajo.",
            "",
            "## Cómo leer este modelo",
            "",
            "El modelo se presenta en cuatro niveles, de lo conceptual a lo físico:",
            "",
            "1. **[Modelo entidad-relación (notación de Chen)](#modelo-entidad-relacion-notacion-de-chen)**: "
            "el nivel conceptual, como en los libros de texto: entidades, relaciones con su cardinalidad y "
            "atributos principales. Es el que se usa para explicar el negocio.",
            "2. **[Mapa de módulos](#mapa-de-modulos)** y **[mapa general de tablas](#mapa-general-de-tablas)**: "
            "primero los módulos y sus dependencias; luego solo las tablas y sus claves foráneas, agrupadas por módulo.",
            "3. **[Esquema físico por módulo y completo](#esquema-fisico-por-modulo-notacion-pata-de-gallo)**: notación «pata de gallo» de las "
            "tablas de cada módulo con sus columnas, y las tablas de otros módulos con las que se relacionan.",
            "4. **[Detalle por tabla](#tablas)**: cada campo con su tipo, restricciones y relación.",
            "",
            "Además, la sección [Vistas materializadas de reportes](#vistas-materializadas-de-reportes) describe "
            "las vistas analíticas de la aplicación `reports`, que no son modelos de Django.",
            "",
            "Cada diagrama se publica como imagen (SVG, ampliable con clic). Los diagramas físicos también "
            "se incluyen como código Mermaid, que el sitio dibuja en el navegador. Para regenerarlos, desde `backend`:",
            "",
            "```bash",
            "python manage.py generar_erd --salida docs/modelo-de-datos.md --mermaid-dir <carpeta temporal>",
            "# imagen de cada diagrama físico (mermaid-cli):",
            "#   mmdc -i <carpeta>/mapa-modulos.mmd -o docs/img/mapa-modulos.svg",
            "```",
            "",
        ]
        lines += self.chen_section(models_)
        lines += [
            "## Mapa de módulos",
            "",
            "Un nodo por módulo y una flecha por cada par de módulos con dependencia por clave foránea; "
            "va del módulo referenciado al que guarda la clave y se rotula con el número de relaciones. "
            "Se excluyen las relaciones hacia `CustomUser` (seguridad), que casi todos los módulos usan "
            "para registrar responsables; por eso Usuarios y seguridad aparece sin flechas.",
            "",
        ]
        lines += self.figure("mapa-modulos", "Mapa de módulos del modelo de datos", module_map(models_))
        lines += [
            "## Mapa general de tablas",
            "",
            "Cada flecha va de la tabla referenciada a la tabla que guarda la clave foránea. Para que sea legible se "
            "omiten las relaciones con `CustomUser` (responsable, creador, etc.) que salen de casi todos los módulos; "
            "están en el detalle por tabla y en el diagrama completo.",
            "",
        ]
        lines += self.figure("mapa-general", "Mapa general de tablas del modelo de datos", general_map(models_))
        lines += ["## Esquema físico por módulo (notación pata de gallo)", "",
                  "Esquema relacional de la base: las tablas de cada módulo con sus columnas y llaves, y las "
                  "tablas de otros módulos con las que se relacionan (solo su clave).", ""]
        for key, title in titles.items():
            diagram, own, external = module_erd(key, models_)
            lines += [f"### {title}", "", "Tablas: " + ", ".join(f"`{m.__name__}`" for m in own) + ".", ""]
            if external:
                lines += ["Relaciones con otros módulos (solo clave): "
                          + ", ".join(f"`{m.__name__}` ({titles[module_of(m)]})" for m in external) + ".", ""]
            lines += self.figure(f"modulo-{key}", f"Esquema físico del módulo {title} (pata de gallo)", diagram)
        lines += [
            "## Esquema físico completo (notación pata de gallo)", "",
            "Es el **esquema relacional de la base de datos**: todas las tablas con sus columnas y llaves en un solo "
            "diagrama. Es muy grande y se lee mejor por módulo (sección anterior). El modelo conceptual, con entidades, "
            "relaciones y cardinalidades, está al inicio de este documento en notación de Chen.", "",
        ]
        lines += ["```mermaid"] + full_erd(models_) + ["```", ""]
        lines += ["## Vistas materializadas de reportes", ""]
        lines += [
            "La aplicación `reports` consulta dos vistas SQL creadas por la migración "
            "`0001_vistas_materializadas` (en PostgreSQL son `MATERIALIZED VIEW`; en SQLite, vistas estándar). "
            "Son de solo lectura y no tienen modelo de negocio. Las columnas se leen del SQL de la migración.",
            "",
        ]
        views = report_views(models_)
        lines += ["```mermaid"] + views_diagram(views) + ["```", ""]
        for view in views:
            lines += [f"### `{view['name']}`", ""]
            if view["doc"]:
                lines += [view["doc"], ""]
            lines += ["Se alimenta de: " + ", ".join(f"`{t}`" + (f" ({m})" if m else "") for t, m in view["sources"]) + ".", ""]
            lines += ["| Columna | Tipo |", "|---|---|"]
            lines += [f"| `{c}` | {t} |" for c, t in view["columns"]]
            lines.append("")
        lines += ["## Tablas", ""]
        for model in models_:
            meta = model._meta
            doc = (model.__doc__ or "").strip().splitlines()[0] if model.__doc__ else ""
            doc = "" if doc.startswith(model.__name__ + "(") else doc
            lines += [f"### {model.__name__} (`{meta.db_table}`)", ""]
            if doc:
                lines += [doc, ""]
            lines += ["| Campo | Tipo | Restricciones | Relación |", "|---|---|---|---|"]
            for field in own_fields(model):
                relation = f"→ `{field.related_model.__name__}`" if isinstance(field, models.ForeignKey) else ""
                extra = constraints(field)
                if field.null and not field.primary_key:
                    extra.append("nulo")
                lines.append(f"| `{field.name}` | {column_type(field)} | {', '.join(extra)} | {relation} |")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def chen_section(self, models_):
        """Sección del MER en notación de Chen (figuras generadas con `generar_mer`)."""
        from apps.core.management.commands.generar_mer import figures

        figs = figures(models_)
        lines = [
            "## Modelo entidad-relación (notación de Chen)",
            "",
            "Es el modelo **conceptual** del sistema, dibujado con la notación de Peter Chen. Se parte de las "
            f"{len(models_)} tablas reales, pero se leen como entidades y relaciones del negocio, no como tablas.",
            "",
            "| Símbolo | Significado |",
            "|---|---|",
            "| Rectángulo | **Entidad**: algo del negocio sobre lo que se guarda información (cliente, factura, lote). |",
            "| Rectángulo de doble borde | **Entidad débil**: no existe sin su entidad propietaria (una línea de factura sin la factura). |",
            "| Rombo | **Relación** entre entidades, nombrada con un verbo (Cliente *compra* Factura). |",
            "| Rombo de doble borde | **Relación identificadora** entre una entidad débil y su propietaria. |",
            "| Óvalo | **Atributo**; el identificador (llave primaria) va subrayado. |",
            "| `1`, `N`, `M`, `P` sobre la línea | **Cardinalidad**: `1` en el lado referenciado y `N` en el lado que guarda la "
            "clave foránea (1:N); `1` y `1` en una relación uno a uno; `N` y `M` en una relación muchos a muchos. |",
            "| Óvalos colgando de un rombo | Atributos **de la relación** (por ejemplo, la cantidad enviada de un lote en una remisión). |",
            "| Rectángulo gris | Entidad de **otro módulo** con la que se relaciona el módulo mostrado (sin atributos). |",
            "",
            "Las tablas puramente asociativas se dibujan como rombo muchos a muchos y no como rectángulo: "
            "`RolePermission` (Role–ModulePermission), `RemisionLote` (RemisionLavanderia–Lote, con la receta de lavado "
            "como tercera punta), `RecepcionLote` (RecepcionLavanderia–Lote) y `AsignacionEtapa` (EtapaLote–Operario–Maquina, "
            "relación ternaria N:M:P). Son entidades débiles las líneas y registros de detalle que no existen sin su "
            "cabecera: `OrdenLinea`, `FichaLinea`, `LoteTalla`, `EventoEtapa`, `LineaCompra`, `RecepcionLinea`, `MarraDetalle`, "
            "`IngresoLinea`, `AjusteLinea`, `DetalleVenta` y `EventoGuia`.",
            "",
            "Criterios de lectura:",
            "",
            "- Para que sea legible **no se dibujan las relaciones hacia `CustomUser`** ni hacia las entidades de seguridad "
            "desde otros módulos (quién creó, aprobó o registró algo): salen de casi todas las tablas y saturarían el dibujo. "
            "Sí se muestran las relaciones internas del módulo Usuarios y seguridad.",
            "- Los **atributos** son los principales (máximo 8 por entidad: identificador, códigos, nombre o descripción, "
            "estado, cantidades, montos y fechas). No incluyen claves foráneas ni columnas de auditoría. El detalle completo "
            "de cada tabla está en la sección [Tablas](#tablas).",
            "- Dos relaciones que dependen de un rombo (`RecepcionLote`, `RemisionLote`) no se repiten como línea aparte: "
            "la recepción ya enlaza la remisión y el lote, y la inspección se enlaza con el lote.",
            "- Los diagramas de «pata de gallo» de las secciones siguientes son el **esquema físico** de la base de datos "
            "(tablas, columnas y llaves); este modelo es su lectura conceptual.",
            "",
            "Las figuras se generan en dos pasos. Primero el comando emite texto DOT de Graphviz (determinista); luego se "
            "renderiza fuera del proyecto, porque Graphviz no es dependencia (por ejemplo con `@hpcc-js/wasm-graphviz`, "
            "Graphviz compilado a WebAssembly, y `@resvg/resvg-js` para el PNG):",
            "",
            "```bash",
            "python manage.py generar_mer --dot-dir <carpeta>      # un .dot por figura (la primera línea indica el motor: neato)",
            "# render (Node, ver backend/tools/mer/README.md): las figuras por módulo y la general con",
            "#   node tools/mer/render.mjs <carpeta> docs/img all 8000",
            "# y la general con atributos (coloca los óvalos alrededor de cada entidad) con",
            "#   node tools/mer/radial.mjs <carpeta>/mer-general-atributos.dot docs/img 1.8 0.22 8000",
            "```",
            "",
            "### MER general",
            "",
            "Todas las entidades y relaciones, sin atributos; el color indica el módulo de cada entidad.",
            "",
        ]
        lines += self.image_figure("mer-general", "Modelo entidad-relación general (Chen)")
        lines += [
            "### MER general con atributos principales",
            "",
            "Las mismas entidades y relaciones, con su llave (subrayada) y hasta 4 atributos principales por entidad; las claves "
            "foráneas no se repiten como atributos porque ya son relaciones. Es una figura grande: ábrela en SVG y amplía. "
            "Los atributos de cada módulo completos están en los MER de abajo.",
            "",
        ]
        lines += self.image_figure("mer-general-atributos", "Modelo entidad-relación general con atributos principales (Chen)")
        for key, title in module_titles(models_).items():
            mine = [f for f in figs if f["module"] == key]
            lines += [f"### MER de {title}", ""]
            for fig in mine:
                if len(mine) > 1:
                    lines += [f"**{fig['title'].split(': ', 1)[1]}**", ""]
                lines += self.image_figure(fig["name"], f"MER de {fig['title']} (Chen)")
        return lines

    def image_figure(self, name, alt):
        return [
            f"[![{alt}]({IMG_DIR}/{name}.svg)]({IMG_DIR}/{name}.svg){{ target=_blank }}",
            "",
            f"[Abrir imagen SVG]({IMG_DIR}/{name}.svg){{ target=_blank }} · [Descargar PNG]({IMG_DIR}/{name}.png)",
            "",
        ]

    def figure(self, name, alt, diagram):
        """Imagen enlazada (SVG) y, debajo, el mismo diagrama como Mermaid desplegable."""
        return [
            f"[![{alt}]({IMG_DIR}/{name}.svg)]({IMG_DIR}/{name}.svg){{ target=_blank }}",
            "",
            f"[Abrir imagen SVG]({IMG_DIR}/{name}.svg){{ target=_blank }} · [Descargar PNG]({IMG_DIR}/{name}.png)",
            "",
            '??? note "Ver como código Mermaid (se dibuja en el navegador)"',
            "",
            "    ```mermaid",
            *[f"    {line}" for line in diagram],
            "    ```",
            "",
        ]
