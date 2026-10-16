"""
Reglas de negocio del catálogo de referencias de jean (HU 3.1). Cada función es una
transacción: o se guarda todo (referencia, variantes, imágenes) o no se guarda nada.
"""
from django.db import IntegrityError, transaction

from apps.inventory.services import IMAGE_TYPES, detect_type, fail, next_code

from . import catalog
from .models import ImagenReferencia, Referencia, Variante


def clean_text(value):
    """Quita espacios sobrantes (inicio, final y repetidos dentro del texto)."""
    return " ".join(str(value or "").split())


def clean_variants(raw):
    """Normaliza la lista de variantes: talla en mayúsculas, color sin espacios de más.
    Rechaza vacías, repetidas (el color no distingue mayúsculas) y más de `MAX_VARIANTS`.
    Devuelve una lista de `(talla, color)`.
    """
    if len(raw) > catalog.MAX_VARIANTS:
        fail(f"Una referencia admite máximo {catalog.MAX_VARIANTS} combinaciones de talla y color.", "variantes")
    result, seen = [], set()
    for item in raw:
        size, color = clean_text(item.get("talla")).upper(), clean_text(item.get("color"))
        if not size or not color:
            fail("Cada variante necesita talla y color.", "variantes")
        key = (size, color.lower())
        if key in seen:
            fail(f"La combinación {size} / {color} está repetida.", "variantes")
        seen.add(key)
        result.append((size, color))
    return result


def ensure_unique_name(name, exclude_pk=None):
    """El nombre no se repite entre referencias activas (sin distinguir mayúsculas)."""
    clash = Referencia.objects.filter(nombre__iexact=name)
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        fail("Ya existe una referencia con ese nombre.", "nombre")


def sync_variants(reference, wanted):
    """Deja las variantes de la referencia igual a `wanted`: crea las nuevas y archiva las que ya no están."""
    current = {(v.talla, v.color.lower()): v for v in reference.variantes.all()}
    keep = {(size, color.lower()) for size, color in wanted}
    for key, variant in current.items():
        if key not in keep:
            variant.delete()
    for size, color in wanted:
        if (size, color.lower()) not in current:
            Variante.objects.create(referencia=reference, talla=size, color=color)


@transaction.atomic
def create_reference(*, user, data, variants):
    """Crea una referencia en borrador con su código REF-0001 y sus variantes."""
    name = clean_text(data["nombre"])
    ensure_unique_name(name)
    variants = clean_variants(variants)
    try:
        with transaction.atomic():
            reference = Referencia.objects.create(
                codigo=next_code(catalog.CODE_PREFIX), nombre=name,
                descripcion=clean_text(data.get("descripcion")), ajuste=data["ajuste"], creado_por=user,
            )
    except IntegrityError:
        fail("Ya existe una referencia con ese nombre.", "nombre")
    sync_variants(reference, variants)
    return reference


@transaction.atomic
def update_reference(reference, data, variants=None):
    """Edita los datos de la referencia. Si llega `variants`, esa lista reemplaza a la actual.
    Una referencia activa no puede quedarse sin variantes.
    """
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    if "nombre" in data:
        name = clean_text(data["nombre"])
        ensure_unique_name(name, exclude_pk=reference.pk)
        reference.nombre = name
    if "descripcion" in data:
        reference.descripcion = clean_text(data["descripcion"])
    if "ajuste" in data:
        reference.ajuste = data["ajuste"]
    if variants is not None:
        wanted = clean_variants(variants)
        if reference.estado == catalog.ACTIVE and not wanted:
            fail("Una referencia activa necesita al menos una talla y un color.", "variantes")
        sync_variants(reference, wanted)
    try:
        with transaction.atomic():
            reference.save()
    except IntegrityError:
        fail("Ya existe una referencia con ese nombre.", "nombre")
    return reference


@transaction.atomic
def change_state(reference, new_state):
    """Borrador -> activa -> descontinuada (y de descontinuada otra vez a activa).
    Para activarla se exige al menos una variante y una imagen del prototipo.
    """
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    if new_state not in catalog.STATE_TRANSITIONS.get(reference.estado, set()):
        fail(
            f"No se puede pasar de {reference.get_estado_display().lower()} "
            f"a {dict(catalog.STATES).get(new_state, new_state).lower()}.",
            "estado",
        )
    if new_state == catalog.ACTIVE:
        if not reference.variantes.exists():
            fail("Para activarla agrega al menos una talla y un color.", "estado")
        if not reference.imagenes.exists():
            fail("Para activarla sube al menos una imagen del prototipo.", "estado")
    reference.estado = new_state
    reference.save(update_fields=["estado", "updated_at"])
    return reference


@transaction.atomic
def archive_reference(reference):
    """Archiva la referencia con sus variantes e imágenes (borrado lógico). Una referencia activa
    primero se descontinúa, para no sacar del catálogo un modelo que se está fabricando.
    """
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    if reference.estado == catalog.ACTIVE:
        fail("Descontinúa la referencia antes de archivarla.", "estado")
    reference.variantes.all().delete()
    reference.imagenes.all().delete()
    reference.delete()


# --- Imágenes -----------------------------------------------------------------------

@transaction.atomic
def add_images(reference, uploads):
    """Guarda las fotos del prototipo (máx. `MAX_IMAGES` por referencia, 2 MB cada una; JPG, PNG o WEBP
    detectado por contenido). La primera que se sube queda como principal.
    """
    if not uploads:
        fail("Adjunta una imagen.", "imagen")
    reference = Referencia.objects.select_for_update().get(pk=reference.pk)
    if reference.imagenes.count() + len(uploads) > catalog.MAX_IMAGES:
        fail(f"Una referencia admite máximo {catalog.MAX_IMAGES} imágenes.", "imagen")
    prepared = []
    for upload in uploads:
        if upload.size > catalog.IMAGE_MAX_BYTES:
            fail(f"La imagen pesa más de {catalog.IMAGE_MAX_BYTES // (1024 * 1024)} MB.", "imagen")
        data = upload.read()
        content_type, _ = detect_type(data[:16])
        if content_type not in IMAGE_TYPES:
            fail("Solo se aceptan imágenes JPG, PNG o WEBP.", "imagen")
        prepared.append((data, content_type))
    has_main = reference.imagenes.filter(principal=True).exists()
    for data, content_type in prepared:
        ImagenReferencia.objects.create(referencia=reference, imagen=data, tipo=content_type, principal=not has_main)
        has_main = True
    return reference


@transaction.atomic
def set_main_image(image):
    """Marca la imagen como principal y quita la marca a la anterior."""
    reference = Referencia.objects.select_for_update().get(pk=image.referencia_id)
    reference.imagenes.filter(principal=True).exclude(pk=image.pk).update(principal=False)
    ImagenReferencia.objects.filter(pk=image.pk).update(principal=True)
    return reference


@transaction.atomic
def remove_image(image):
    """Quita una imagen. Si era la principal, la siguiente pasa a serlo. Una referencia activa
    no puede quedarse sin imágenes.
    """
    reference = Referencia.objects.select_for_update().get(pk=image.referencia_id)
    others = reference.imagenes.exclude(pk=image.pk)
    if reference.estado == catalog.ACTIVE and not others.exists():
        fail("Una referencia activa necesita al menos una imagen.", "imagen")
    was_main = image.principal
    image.delete()
    if was_main:
        first = others.first()
        if first:
            ImagenReferencia.objects.filter(pk=first.pk).update(principal=True)
    return reference
