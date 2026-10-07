"""
Genera la documentación del modelo de datos a partir de los modelos de Django.

    python manage.py generar_erd                    # imprime el Markdown
    python manage.py generar_erd --salida docs/modelo-de-datos.md

El diagrama entidad-relación sale en Mermaid (GitHub y MkDocs lo dibujan solos),
así que no hace falta instalar Graphviz. Ejecútalo de nuevo cuando cambie un modelo.
"""
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import models

PROJECT_APPS = ("core", "users", "inventory")
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


class Command(BaseCommand):
    help = "Genera el modelo de datos (diagrama Mermaid y tablas de campos) en Markdown."

    def add_arguments(self, parser):
        parser.add_argument("--salida", help="Archivo .md de destino; sin él se imprime.")

    def handle(self, *args, **options):
        text = self.render(project_models())
        target = options.get("salida")
        if target:
            Path(target).write_text(text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Modelo de datos escrito en {target}"))
        else:
            self.stdout.write(text)

    def render(self, models_):
        lines = [
            "# Modelo de datos",
            "",
            "> Generado automáticamente con `python manage.py generar_erd --salida docs/modelo-de-datos.md`.",
            "> No lo edites a mano: vuelve a generarlo cuando cambie un modelo.",
            "",
            "Todas las tablas de negocio heredan de `BaseModel` y por eso incluyen además "
            "`created_at`, `updated_at` y `deleted_at` (borrado lógico; ver "
            "[convenciones de base de datos](convenciones-base-de-datos.md)). Esas columnas no se repiten abajo.",
            "",
            "## Diagrama entidad-relación",
            "",
            "```mermaid",
            "erDiagram",
        ]
        relations = []
        for model in models_:
            lines.append(f"    {model.__name__} {{")
            for field in own_fields(model):
                marks = " ".join(constraints(field))
                lines.append(f"        {mermaid_type(field)} {field.name}" + (f" {marks}" if marks else ""))
            lines.append("    }")
            for field in model._meta.concrete_fields:
                if isinstance(field, models.ForeignKey) and field.related_model in models_:
                    left = "|o" if field.null else "||"
                    relations.append(
                        f"    {field.related_model.__name__} {left}--o{{ {model.__name__} : \"{field.name}\""
                    )
        lines += sorted(set(relations))
        lines += ["```", "", "## Tablas", ""]
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
