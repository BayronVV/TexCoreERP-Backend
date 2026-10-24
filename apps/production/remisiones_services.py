from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory import catalog as inv_catalog
from apps.inventory.models import Consecutivo, Proveedor
from apps.inventory.services import fail
from apps.production import catalog
from apps.production.models import Lote, RecetaLavado, RemisionLavanderia, RemisionLote


def next_remission_code():
    """Genera el código consecutivo oficial del documento de salida: REM-LAV-YYYY-0001..."""
    year = timezone.now().year
    counter, _ = Consecutivo.objects.select_for_update().get_or_create(clave="REM-LAV")
    counter.ultimo += 1
    counter.save(update_fields=["ultimo"])
    return f"REM-LAV-{year}-{counter.ultimo:04d}"


def get_available_lots_for_washing():
    """Devuelve los lotes ensamblados que están en la planta interna (estado_inventario = PLANTA).

    Cuando un lote se remite a lavandería, se descuenta de la planta pasando su estado a EN_TRANSITO
    y ya no aparece en esta lista.
    """
    lotes = (
        Lote.objects.filter(
            estado_inventario=catalog.LOT_INV_INTERNAL,
            deleted_at__isnull=True,
            orden__deleted_at__isnull=True,
        )
        .select_related("orden__orden_salida", "orden__referencia")
        .prefetch_related("tallas", "etapas")
        .order_by("orden_id", "numero")
    )

    receta_default = RecetaLavado.objects.filter(deleted_at__isnull=True).order_by("id").first()
    receta_default_id = receta_default.codigo if receta_default else "REC-SW-01"
    receta_default_nombre = receta_default.nombre if receta_default else "Stone Wash Medio + Bigotes 3D"

    data = []
    for lote in lotes:
        ref = lote.orden.referencia
        tallas_dict = {t.talla: t.cantidad for t in lote.tallas.all()}
        # Color y tela por defecto o de la referencia
        color_crudo = "Azul Índigo Crudo"
        if lote.tallas.exists() and lote.tallas.first().color:
            color_crudo = lote.tallas.first().color

        data.append(
            {
                "id": lote.id,
                "codigo_lote": lote.codigo,
                "op_codigo": lote.orden.codigo,
                "referencia": ref.nombre,
                "referencia_codigo": ref.codigo,
                "ficha_tecnica": f"FT-{ref.codigo}",
                "tela": f"Denim {ref.nombre}",
                "color_crudo": color_crudo,
                "unidades_ensambladas": lote.cantidad,
                "unidades_disponibles": lote.cantidad,
                "curva_tallas": tallas_dict,
                "taller_confeccion": "Planta TexCore - Módulo Ensamble",
                "fecha_ensamble": lote.created_at.date().isoformat(),
                "receta_sugerida": receta_default_id,
                "receta_sugerida_nombre": receta_default_nombre,
                "observacion_confeccion": "Lote ensamblado y verificado en planta interna.",
                "estado_inventario": lote.estado_inventario,
            }
        )
    return data


def get_laundry_providers():
    """Lista los proveedores de servicios de lavandería activos."""
    proveedores = Proveedor.objects.filter(
        categoria=inv_catalog.CAT_LAUNDRY,
        deleted_at__isnull=True,
    ).order_by("razon_social")

    # Si aún no hay con categoría LAVANDERIA, tomar todos los proveedores activos como fallback
    if not proveedores.exists():
        proveedores = Proveedor.objects.filter(deleted_at__isnull=True).order_by("razon_social")

    result = []
    for prov in proveedores:
        nit_completo = f"{prov.nit}-{prov.nit_dv}" if prov.nit_dv else prov.nit
        result.append(
            {
                "id": prov.id,
                "razon_social": prov.razon_social,
                "nit": nit_completo,
                "ciudad": prov.ciudad or "Medellín, Antioquia",
                "direccion": prov.direccion or "Zona Industrial",
                "contacto": prov.contacto or "Coordinador de Planta",
                "telefono": prov.telefono or "",
                "tarifa_base_unidad": 3500,
                "tiempo_promedio_dias": 3,
                "calificacion_calidad": "4.8 / 5.0 (Proveedor Homologado)",
            }
        )
    return result


def get_wash_recipes():
    """Lista las recetas técnicas de lavado registradas en la base de datos."""
    recetas = RecetaLavado.objects.filter(deleted_at__isnull=True).order_by("codigo")
    return [
        {
            "id": r.codigo,
            "db_id": r.id,
            "codigo": r.codigo,
            "nombre": r.nombre,
            "categoria": r.categoria,
            "descripcion": r.descripcion,
            "temperatura_proceso": r.temperatura_proceso,
            "duracion_horas": r.duracion_horas,
            "tarifa_sugerida": float(r.tarifa_sugerida),
        }
        for r in recetas
    ]


def serialize_remission_detail(remision):
    """Formatea una remisión para su consumo por el frontend y la vista de impresión del ticket."""
    lotes_detalle = []
    for dl in remision.lotes_detalle.all():
        lote = dl.lote
        ref = lote.orden.referencia if lote.orden and lote.orden.referencia else None
        lotes_detalle.append(
            {
                "id": lote.id,
                "codigo_lote": lote.codigo,
                "op_codigo": lote.orden.codigo if lote.orden else "",
                "referencia": ref.nombre if ref else "",
                "ficha_tecnica": f"FT-{ref.codigo}" if ref else "",
                "color_crudo": "Índigo Base",
                "cantidad_a_enviar": dl.cantidad,
                "receta_id": dl.receta.codigo if dl.receta else "",
                "receta_nombre": dl.receta_nombre or (dl.receta.nombre if dl.receta else "Lavado Estándar"),
                "instrucciones_especiales": dl.instrucciones_especiales,
            }
        )

    prov = remision.lavanderia
    contacto_lav = prov.contacto if prov else ""
    nombre_lav = prov.razon_social if prov else "Lavandería Externa"

    responsable_str = "Carlos E. Restrepo (Jefe de Producción)"
    if remision.responsable:
        responsable_str = f"{remision.responsable.get_full_name() or remision.responsable.email}"

    total_prendas = sum(d["cantidad_a_enviar"] for d in lotes_detalle)
    lotes_nombres = [f"{d['codigo_lote']} ({d['referencia']})" for d in lotes_detalle]

    return {
        "id": remision.id,
        "codigo": remision.codigo,
        "fecha_emision": remision.fecha_emision.isoformat(),
        "fecha_entrega_estimada": (
            remision.fecha_entrega_estimada.isoformat() if remision.fecha_entrega_estimada else ""
        ),
        "lavanderia_id": prov.id if prov else None,
        "lavanderia_nombre": nombre_lav,
        "contacto_lavanderia": contacto_lav,
        "lotes_nombres": lotes_nombres,
        "lotes_detalle": lotes_detalle,
        "total_lotes": len(lotes_detalle),
        "total_prendas": total_prendas,
        "receta_nombre": lotes_detalle[0]["receta_nombre"] if lotes_detalle else "Lavado Industrial",
        "costo_estimado": float(remision.costo_estimado),
        "transportador_nombre": remision.transportador_nombre,
        "vehiculo_placa": remision.vehiculo_placa,
        "tulas_bultos": remision.tulas_bultos,
        "peso_kg": float(remision.peso_kg),
        "estado": remision.estado,
        "responsable_despacho": responsable_str,
        "observaciones": remision.observaciones,
    }


@transaction.atomic
def create_laundry_remission(
    *,
    user,
    lavanderia_id,
    lotes_seleccionados,
    fecha_emision,
    fecha_entrega_estimada=None,
    transportador_nombre="",
    vehiculo_placa="",
    tulas_bultos=1,
    peso_kg=0,
    observaciones="",
):
    """Crea la remisión oficial de salida a lavandería (HU TE-57 / TE-131).

    Reglas de negocio:
    1. Genera el código consecutivo oficial del documento de salida (REM-LAV-YYYY-0001).
    2. Bloquea los lotes para evitar concurrencia y valida que estén en la planta interna (PLANTA).
    3. Descuenta los lotes de la planta interna cambiando su estado de inventario a EN_TRANSITO.
    4. Guarda el documento de remisión y sus líneas asociadas.
    5. Devuelve la remisión estructurada lista para el ticket de impresión.
    """
    if not lotes_seleccionados:
        fail("Debes seleccionar al menos un lote para generar la remisión.", "lotes")

    prov = Proveedor.objects.filter(pk=lavanderia_id, deleted_at__isnull=True).first()
    if prov is None:
        fail("El proveedor de lavandería seleccionado no existe o está inactivo.", "lavanderia")

    lot_ids = [item["lote_id"] for item in lotes_seleccionados]
    if len(lot_ids) != len(set(lot_ids)):
        fail("No puedes seleccionar el mismo lote más de una vez en la remisión.", "lotes")

    # Bloquear lotes en orden de ID
    locked_lots = {
        l.id: l for l in Lote.objects.select_for_update().filter(id__in=lot_ids).order_by("id")
    }

    missing_ids = set(lot_ids) - set(locked_lots.keys())
    if missing_ids:
        fail(f"Los lotes con IDs {missing_ids} no existen.", "lotes")

    # Validar estado de planta de cada lote
    for item in lotes_seleccionados:
        lote = locked_lots[item["lote_id"]]
        if lote.estado_inventario != catalog.LOT_INV_INTERNAL:
            fail(
                f"El lote {lote.codigo} ya no está en la planta interna (estado actual: {lote.get_estado_inventario_display()}).",
                "lotes",
            )
        qty = int(item.get("cantidad", 0))
        if qty <= 0:
            fail(f"La cantidad enviada del lote {lote.codigo} debe ser mayor a cero.", "cantidad")
        if qty > lote.cantidad:
            fail(
                f"La cantidad solicitada ({qty}) supera las unidades del lote {lote.codigo} ({lote.cantidad}).",
                "cantidad",
            )

    # Generar código consecutivo oficial
    consecutivo = next_remission_code()

    # Calcular costo estimado total
    recetas_cache = {r.codigo: r for r in RecetaLavado.objects.filter(deleted_at__isnull=True)}
    costo_total = Decimal("0.00")
    tarifa_base_defecto = Decimal("3500.00")

    for item in lotes_seleccionados:
        qty = Decimal(str(item.get("cantidad", 0)))
        receta_code = item.get("receta_id")
        receta_obj = recetas_cache.get(receta_code)
        tarifa = receta_obj.tarifa_sugerida if receta_obj else tarifa_base_defecto
        costo_total += qty * tarifa

    # Crear la Remisión de Salida
    remision = RemisionLavanderia.objects.create(
        codigo=consecutivo,
        fecha_emision=fecha_emision,
        fecha_entrega_estimada=fecha_entrega_estimada,
        lavanderia=prov,
        transportador_nombre=transportador_nombre.strip(),
        vehiculo_placa=vehiculo_placa.strip(),
        tulas_bultos=int(tulas_bultos or 1),
        peso_kg=Decimal(str(peso_kg or 0)),
        costo_estimado=costo_total,
        estado=catalog.REMISSION_IN_TRANSIT,
        observaciones=observaciones.strip(),
        responsable=user,
        creado_por=user,
    )

    # Crear líneas y descontar lotes de la planta interna
    for item in lotes_seleccionados:
        lote = locked_lots[item["lote_id"]]
        receta_code = item.get("receta_id")
        receta_obj = recetas_cache.get(receta_code)
        receta_nombre = item.get("receta_nombre") or (receta_obj.nombre if receta_obj else "")

        RemisionLote.objects.create(
            remision=remision,
            lote=lote,
            cantidad=int(item["cantidad"]),
            receta=receta_obj,
            receta_nombre=receta_nombre,
            instrucciones_especiales=item.get("instrucciones_especiales", "").strip(),
        )

        # DESCONTAR DE PLANTA INTERNA -> ESTADO EN TRÁNSITO / EXTERNO
        lote.estado_inventario = catalog.LOT_INV_IN_TRANSIT
        lote.save(update_fields=["estado_inventario", "updated_at"])

    # Traer con relaciones prefetched para serializar
    remision_full = (
        RemisionLavanderia.objects.select_related("lavanderia", "responsable")
        .prefetch_related(
            "lotes_detalle__lote__orden__referencia",
            "lotes_detalle__receta",
        )
        .get(pk=remision.pk)
    )

    return serialize_remission_detail(remision_full)


def list_laundry_remissions():
    """Lista el historial de remisiones a lavandería ordenadas de la más reciente a la más antigua."""
    remisiones = (
        RemisionLavanderia.objects.filter(deleted_at__isnull=True)
        .select_related("lavanderia", "responsable")
        .prefetch_related(
            "lotes_detalle__lote__orden__referencia",
            "lotes_detalle__receta",
        )
        .order_by("-fecha_emision", "-id")
    )
    return [serialize_remission_detail(r) for r in remisiones]
