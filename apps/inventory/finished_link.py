"""Vínculo vivo entre `Producto` (PRODUCTO_TERMINADO) y `Referencia` (HU 6.5 / TE-170).

La fuente única de existencias de producto terminado es `terminado_stock`.
"""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce

from apps.finished.models import StockTerminado
from apps.references import catalog as reference_catalog

from . import catalog
from .models import Consecutivo, Producto

STOCK_PLACES = Decimal("0.01")


def finished_product_name(reference) -> str:
    """Nombre del producto terminado derivado de su referencia (`REF-0001 · Nombre`)."""
    return f"{reference.codigo} · {reference.nombre}"[:150]


def finished_totals_by_reference(reference_ids) -> dict[int, Decimal]:
    """Suma en una sola consulta las prendas de primera calidad en `StockTerminado` por referencia."""
    clean_ids = sorted({int(rid) for rid in reference_ids if rid is not None})
    if not clean_ids:
        return {}
    rows = (
        StockTerminado.objects.filter(
            variante__referencia_id__in=clean_ids,
            variante__deleted_at__isnull=True,
        )
        .values("variante__referencia_id")
        .annotate(total=Coalesce(Sum("cantidad"), 0))
    )
    totals = {rid: Decimal("0.00") for rid in clean_ids}
    for row in rows:
        totals[row["variante__referencia_id"]] = Decimal(row["total"]).quantize(STOCK_PLACES)
    return totals


def annotate_products_with_live_stock(products) -> list[Producto]:
    """Anota `_live_stock` en una lista de productos con una sola consulta agregada sobre `StockTerminado`."""
    items = list(products)
    linked_ref_ids = [p.referencia_id for p in items if p.es_terminado_enlazado]
    totals = finished_totals_by_reference(linked_ref_ids)
    for product in items:
        if product.es_terminado_enlazado:
            product._live_stock = totals.get(product.referencia_id, Decimal("0.00"))
        else:
            product._live_stock = product.stock_actual
    return items


def is_alertable_product(product: Producto) -> bool:
    """Los productos heredados y los PT de referencias borrador/descontinuadas no disparan alertas."""
    if product.heredado:
        return False
    if product.es_terminado_enlazado:
        return bool(product.referencia and product.referencia.estado == reference_catalog.ACTIVE)
    return True


def _sync_pt_counter(ConsecutivoModel, ProductoModel):
    """Asegura que el consecutivo PT no choque con códigos PT-NNNN existentes (activos o archivados)."""
    prefix = f"{catalog.CATEGORIES[catalog.CAT_FINISHED]['prefix']}-"
    max_num = 0
    manager = getattr(ProductoModel, "all_objects", ProductoModel.objects)
    for code in manager.filter(codigo__startswith=prefix).values_list("codigo", flat=True):
        tail = code[len(prefix) :]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    counter, _ = ConsecutivoModel.objects.select_for_update().get_or_create(clave=catalog.CATEGORIES[catalog.CAT_FINISHED]["prefix"])
    if counter.ultimo < max_num:
        counter.ultimo = max_num
        counter.save(update_fields=["ultimo"])
    return counter


@transaction.atomic
def ensure_finished_product_for_reference(reference, *, min_stock=None) -> Producto:
    """Garantiza un `Producto` PT activo y único para una referencia con variantes o activa."""
    existing = Producto.objects.select_for_update().filter(referencia=reference).first()
    target_name = finished_product_name(reference)
    if existing is not None:
        if existing.nombre != target_name:
            existing.nombre = target_name
            existing.save(update_fields=["nombre", "updated_at"])
        return existing

    archived = Producto.all_objects.select_for_update().filter(
        referencia=reference, deleted_at__isnull=False
    ).first()
    if archived is not None:
        archived.deleted_at = None
        archived.nombre = target_name
        archived.heredado = False
        archived.save(update_fields=["deleted_at", "nombre", "heredado", "updated_at"])
        return archived

    counter = _sync_pt_counter(Consecutivo, Producto)
    counter.ultimo += 1
    counter.save(update_fields=["ultimo"])
    prefix = catalog.CATEGORIES[catalog.CAT_FINISHED]["prefix"]
    stock_min = catalog.DEFAULT_FINISHED_MIN_STOCK if min_stock is None else Decimal(min_stock)
    try:
        with transaction.atomic():
            return Producto.objects.create(
                codigo=f"{prefix}-{counter.ultimo:04d}",
                nombre=target_name,
                tipo=catalog.FINISHED_PANTS,
                categoria=catalog.CAT_FINISHED,
                unidad="unidad",
                stock_actual=Decimal("0.00"),
                stock_minimo=stock_min,
                referencia=reference,
                heredado=False,
            )
    except IntegrityError:
        return Producto.objects.get(referencia=reference)


def unify_existing_finished_products(ProductoModel, ConsecutivoModel, ReferenciaModel, VarianteModel):
    """Migración de datos TE-170:
    1. Marca los PT anteriores sin referencia como `heredado=True` sin tocar saldos, kardex ni órdenes.
    2. Crea el PT enlazado (`stock_minimo=30`) para toda referencia activa o con variantes que no lo tenga.
    """
    ProductoModel.objects.filter(
        tipo=catalog.FINISHED_PANTS,
        referencia_id__isnull=True,
        deleted_at__isnull=True,
    ).update(heredado=True)

    refs_with_variants = set(
        VarianteModel.objects.filter(deleted_at__isnull=True).values_list("referencia_id", flat=True)
    )
    linked_ref_ids = set(
        ProductoModel.objects.filter(
            referencia_id__isnull=False,
            deleted_at__isnull=True,
        ).values_list("referencia_id", flat=True)
    )

    counter = _sync_pt_counter(ConsecutivoModel, ProductoModel)
    prefix = catalog.CATEGORIES[catalog.CAT_FINISHED]["prefix"]
    candidates = ReferenciaModel.objects.filter(deleted_at__isnull=True).order_by("id")
    for ref in candidates:
        if ref.id in linked_ref_ids:
            continue
        if ref.estado != reference_catalog.ACTIVE and ref.id not in refs_with_variants:
            continue
        counter.ultimo += 1
        counter.save(update_fields=["ultimo"])
        ProductoModel.objects.create(
            codigo=f"{prefix}-{counter.ultimo:04d}",
            nombre=finished_product_name(ref),
            tipo=catalog.FINISHED_PANTS,
            categoria=catalog.CAT_FINISHED,
            unidad="unidad",
            stock_actual=Decimal("0.00"),
            stock_minimo=catalog.DEFAULT_FINISHED_MIN_STOCK,
            referencia_id=ref.id,
            heredado=False,
        )
