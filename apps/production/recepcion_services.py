"""Servicios de Recepción y Cotejo de Lavandería Externa (TE-58).

Reglas de negocio:
1. Permite cotejar las cantidades enviadas vs devueltas por lote.
2. Exige campos obligatorios para registrar mermas (extravíos) o daños ocurridos en la lavandería.
3. Vincula el reingreso a la remisión / factura de salida original (RemisionLavanderia).
4. Devuelve las prendas recibidas al estado interno de la planta (estado_inventario = PLANTA).
5. Liquida y registra financieramente las pérdidas por mermas y daños ocasionados por terceros.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.inventory.models import Consecutivo
from apps.inventory.services import fail
from apps.production import catalog
from apps.production.models import (
    Lote,
    RecepcionLavanderia,
    RecepcionLote,
    RemisionLavanderia,
    RemisionLote,
)


DEFAULT_GARMENT_COST = Decimal("35000.00")  # Costo estimado de fabricación estándar en TexCore


def next_reception_code():
    """Genera el código consecutivo oficial del acta de recepción: REC-LAV-YYYY-0001..."""
    year = timezone.now().year
    counter, _ = Consecutivo.objects.select_for_update().get_or_create(clave="REC-LAV")
    counter.ultimo += 1
    counter.save(update_fields=["ultimo"])
    return f"REC-LAV-{year}-{counter.ultimo:04d}"


def serialize_reception_detail(recepcion):
    """Formatea la recepción completa para consumo de la API, frontend y modal de impresión."""
    rem = recepcion.remision
    prov = rem.lavanderia

    lotes_detalle = []
    for dl in recepcion.lotes_detalle.select_related("lote__orden__referencia", "remision_lote__receta").all():
        lote = dl.lote
        ref = lote.orden.referencia if lote.orden and lote.orden.referencia else None
        receta = dl.remision_lote.receta if dl.remision_lote else None

        lotes_detalle.append({
            "id": dl.id,
            "recepcion_id": recepcion.id,
            "remision_lote_id": dl.remision_lote_id,
            "lote_id": lote.id,
            "codigo_lote": lote.codigo,
            "op_codigo": lote.orden.codigo if lote.orden else "",
            "referencia": ref.nombre if ref else "",
            "ficha_tecnica": f"FT-{ref.codigo}" if ref else "",
            "receta_nombre": dl.remision_lote.receta_nombre or (receta.nombre if receta else "Lavado Industrial"),
            "cantidad_enviada": dl.cantidad_enviada,
            "cantidad_recibida_conforme": dl.cantidad_recibida_conforme,
            "cantidad_merma": dl.cantidad_merma,
            "cantidad_danada": dl.cantidad_danada,
            "motivo_merma": dl.motivo_merma,
            "tipo_dano": dl.tipo_dano,
            "costo_unitario_prenda": float(dl.costo_unitario_prenda),
            "costo_perdida": float(dl.costo_perdida),
            "observaciones": dl.observaciones,
        })

    responsable_str = "Coordinador de Calidad y Planta"
    if recepcion.responsable:
        responsable_str = recepcion.responsable.get_full_name() or recepcion.responsable.email

    return {
        "id": recepcion.id,
        "codigo": recepcion.codigo,
        "remision_id": rem.id,
        "remision_codigo": rem.codigo,
        "remision_fecha_emision": rem.fecha_emision.isoformat(),
        "factura_remision_externa": recepcion.factura_remision_externa,
        "fecha_recepcion": recepcion.fecha_recepcion.isoformat(),
        "lavanderia_id": prov.id if prov else None,
        "lavanderia_nombre": prov.razon_social if prov else "Lavandería Externa",
        "lavanderia_nit": f"{prov.nit}-{prov.nit_dv}" if prov and prov.nit_dv else (prov.nit if prov else ""),
        "lavanderia_contacto": prov.contacto if prov else "",
        "total_enviado": recepcion.total_enviado,
        "total_recibido_conforme": recepcion.total_recibido_conforme,
        "total_merma": recepcion.total_merma,
        "total_danadas": recepcion.total_danadas,
        "costo_total_perdida": float(recepcion.costo_total_perdida),
        "costo_servicio_lavado": float(recepcion.costo_servicio_lavado),
        "estado": recepcion.estado,
        "responsable": responsable_str,
        "observaciones": recepcion.observaciones,
        "lotes_detalle": lotes_detalle,
    }


def get_pending_remissions_for_reception():
    """Devuelve las remisiones que se encuentran en tránsito o en lavandería, pendientes de recepción."""
    remisiones = (
        RemisionLavanderia.objects.filter(
            deleted_at__isnull=True,
            estado__in=[catalog.REMISSION_IN_TRANSIT, catalog.REMISSION_IN_LAUNDRY],
        )
        .select_related("lavanderia", "responsable")
        .prefetch_related(
            "lotes_detalle__lote__orden__referencia",
            "lotes_detalle__receta",
        )
        .order_by("-fecha_emision", "-id")
    )

    today = timezone.localdate()
    result = []
    for rem in remisiones:
        prov = rem.lavanderia
        dias_proceso = (today - rem.fecha_emision).days if rem.fecha_emision else 0

        lotes = []
        for dl in rem.lotes_detalle.all():
            lote = dl.lote
            ref = lote.orden.referencia if lote.orden and lote.orden.referencia else None
            receta = dl.receta

            tarifa = dl.receta.tarifa_sugerida if dl.receta else Decimal("3500.00")

            lotes.append({
                "remision_lote_id": dl.id,
                "lote_id": lote.id,
                "codigo_lote": lote.codigo,
                "lote_codigo": lote.codigo,
                "op_codigo": lote.orden.codigo if lote.orden else "",
                "referencia": ref.nombre if ref else "",
                "receta_id": receta.codigo if receta else "",
                "receta_nombre": dl.receta_nombre or (receta.nombre if receta else "Lavado Estándar"),
                "tarifa_lavado": float(tarifa),
                "cantidad_enviada": dl.cantidad,
                "costo_unitario_estimado": float(DEFAULT_GARMENT_COST),
            })

        total_prendas = sum(item["cantidad_enviada"] for item in lotes)

        result.append({
            "remision_id": rem.id,
            "codigo": rem.codigo,
            "fecha_emision": rem.fecha_emision.isoformat(),
            "fecha_entrega_estimada": rem.fecha_entrega_estimada.isoformat() if rem.fecha_entrega_estimada else "",
            "dias_en_proceso": max(0, dias_proceso),
            "lavanderia_id": prov.id if prov else None,
            "lavanderia_nombre": prov.razon_social if prov else "Lavandería Externa",
            "lavanderia_contacto": prov.contacto if prov else "",
            "transportador_nombre": rem.transportador_nombre,
            "vehiculo_placa": rem.vehiculo_placa,
            "total_lotes": len(lotes),
            "total_prendas": total_prendas,
            "estado": rem.estado,
            "lotes": lotes,
        })

    return result


@transaction.atomic
def create_laundry_reception(
    *,
    user,
    remision_id,
    fecha_recepcion,
    factura_remision_externa="",
    lotes_recibidos,
    observaciones="",
):
    """Asienta el reingreso de prendas de lavandería externa, coteja cantidades y liquida pérdidas (TE-58).

    Reglas de negocio:
    1. Vincula el registro a la factura/remisión de salida original.
    2. Coteja que para cada lote: conformes + mermas + dañadas == cantidad enviada.
    3. Exige campos obligatorios para registrar mermas (motivo_merma) o daños (tipo_dano).
    4. Devuelve los lotes al estado interno de la planta (estado_inventario = PLANTA).
    5. Actualiza la cantidad disponible del lote con las unidades conformes devueltas.
    6. Liquida y registra financieramente las pérdidas por procesos de terceros:
       costo_perdida = (cantidad_merma + cantidad_danada) * costo_unitario_prenda.
    7. Marca la remisión original como RETORNADA.
    """
    if not lotes_recibidos:
        fail("Debes incluir el detalle de lotes a cotejar en la recepción.", "lotes")

    # Bloquear y validar la remisión original
    remision = (
        RemisionLavanderia.objects.select_for_update()
        .filter(pk=remision_id, deleted_at__isnull=True)
        .first()
    )
    if remision is None:
        fail("La remisión de salida indicada no existe o fue eliminada.", "remision_id")

    if remision.estado == catalog.REMISSION_RETURNED:
        fail(f"La remisión {remision.codigo} ya fue retornada y recibida previamente.", "remision_id")

    if remision.estado == catalog.REMISSION_CANCELLED:
        fail(f"La remisión {remision.codigo} está anulada y no puede recibir prendas.", "remision_id")

    # Cargar y bloquear los detalles de lote de la remisión
    remision_lotes = {
        rl.id: rl
        for rl in RemisionLote.objects.select_for_update(of=("self",))
        .select_related("lote", "receta")
        .filter(remision=remision, deleted_at__isnull=True)
    }

    # Bloquear los lotes de producción para actualizar su estado y unidades
    lot_ids = [rl.lote_id for rl in remision_lotes.values()]
    locked_lots = {
        l.id: l for l in Lote.objects.select_for_update().filter(id__in=lot_ids).order_by("id")
    }

    # Mapa de items recibidos por remision_lote_id o lote_id
    received_map = {}
    for item in lotes_recibidos:
        rl_id = item.get("remision_lote_id")
        lote_id = item.get("lote_id")

        key = None
        if rl_id and int(rl_id) in remision_lotes:
            key = int(rl_id)
        elif lote_id:
            for rl in remision_lotes.values():
                if rl.lote_id == int(lote_id):
                    key = rl.id
                    break

        if key is None:
            fail("Uno de los lotes recibidos no pertenece a esta remisión.", "lotes")
        if key in received_map:
            fail("No puedes enviar el mismo lote más de una vez en el cotejo.", "lotes")
        received_map[key] = item

    # Validar que todos los lotes de la remisión estén incluidos en la recepción
    missing_rl_ids = set(remision_lotes.keys()) - set(received_map.keys())
    if missing_rl_ids:
        missing_names = [remision_lotes[rid].lote.codigo for rid in missing_rl_ids]
        fail(f"Faltan lotes de la remisión por cotejar: {', '.join(missing_names)}.", "lotes")

    total_enviado = 0
    total_conforme = 0
    total_merma = 0
    total_danadas = 0
    costo_total_perdida = Decimal("0.00")
    costo_servicio_lavado = Decimal("0.00")

    filas_a_crear = []

    for rl_id, rl in remision_lotes.items():
        item = received_map[rl_id]
        lote = locked_lots[rl.lote_id]
        enviada = rl.cantidad

        conforme = int(item.get("cantidad_recibida_conforme", 0))
        merma = int(item.get("cantidad_merma", 0))
        danada = int(item.get("cantidad_danada", 0))

        if conforme < 0 or merma < 0 or danada < 0:
            fail(f"Las cantidades no pueden ser negativas en el lote {lote.codigo}.", "cantidades")

        # Regla 1: Cotejo exacto
        if (conforme + merma + danada) != enviada:
            fail(
                f"El cotejo para el lote {lote.codigo} no coincide: "
                f"{conforme} conformes + {merma} merma + {danada} dañadas = {conforme + merma + danada} und "
                f"(deben sumar exactamente las {enviada} und enviadas).",
                "cantidades",
            )

        # Regla 2: Campos obligatorios para mermas o daños ocurridos en la lavandería
        motivo_merma = item.get("motivo_merma", "").strip()
        if merma > 0 and not motivo_merma:
            fail(
                f"El campo 'motivo_merma' es obligatorio para el lote {lote.codigo} al registrar {merma} prendas de merma.",
                "motivo_merma",
            )

        tipo_dano = item.get("tipo_dano", "").strip()
        if danada > 0 and not tipo_dano:
            fail(
                f"El campo 'tipo_dano' es obligatorio para el lote {lote.codigo} al registrar {danada} prendas con defectos de lavandería.",
                "tipo_dano",
            )

        # Costo unitario y cálculo de pérdida financiera
        costo_unitario = Decimal(str(item.get("costo_unitario_prenda") or DEFAULT_GARMENT_COST))
        perdida_lote = (Decimal(merma) + Decimal(danada)) * costo_unitario

        # Costo de servicio de lavado de este lote (solo prendas conformes/procesadas)
        tarifa_receta = rl.receta.tarifa_sugerida if rl.receta else Decimal("3500.00")
        servicio_lote = Decimal(conforme) * tarifa_receta

        total_enviado += enviada
        total_conforme += conforme
        total_merma += merma
        total_danadas += danada
        costo_total_perdida += perdida_lote
        costo_servicio_lavado += servicio_lote

        filas_a_crear.append({
            "remision_lote": rl,
            "lote": lote,
            "cantidad_enviada": enviada,
            "cantidad_recibida_conforme": conforme,
            "cantidad_merma": merma,
            "cantidad_danada": danada,
            "motivo_merma": motivo_merma,
            "tipo_dano": tipo_dano,
            "costo_unitario_prenda": costo_unitario,
            "costo_perdida": perdida_lote,
            "observaciones": item.get("observaciones", "").strip(),
        })

    # Generar código consecutivo de recepción
    consecutivo = next_reception_code()

    # Crear encabezado de recepción
    recepcion = RecepcionLavanderia.objects.create(
        codigo=consecutivo,
        remision=remision,
        factura_remision_externa=factura_remision_externa.strip(),
        fecha_recepcion=fecha_recepcion,
        total_enviado=total_enviado,
        total_recibido_conforme=total_conforme,
        total_merma=total_merma,
        total_danadas=total_danadas,
        costo_total_perdida=costo_total_perdida,
        costo_servicio_lavado=costo_servicio_lavado,
        estado=catalog.RECEPTION_COMPLETE,
        observaciones=observaciones.strip(),
        responsable=user,
        creado_por=user,
    )

    # Crear líneas de detalle y devolver prendas al estado interno de planta
    for fila in filas_a_crear:
        RecepcionLote.objects.create(
            recepcion=recepcion,
            remision_lote=fila["remision_lote"],
            lote=fila["lote"],
            cantidad_enviada=fila["cantidad_enviada"],
            cantidad_recibida_conforme=fila["cantidad_recibida_conforme"],
            cantidad_merma=fila["cantidad_merma"],
            cantidad_danada=fila["cantidad_danada"],
            motivo_merma=fila["motivo_merma"],
            tipo_dano=fila["tipo_dano"],
            costo_unitario_prenda=fila["costo_unitario_prenda"],
            costo_perdida=fila["costo_perdida"],
            observaciones=fila["observaciones"],
        )

        # DEVOLVER AL ESTADO INTERNO DE PLANTA (LOT_INV_INTERNAL = "PLANTA")
        lote = fila["lote"]
        lote.estado_inventario = catalog.LOT_INV_INTERNAL
        # Si hubo mermas o prendas dañadas no recuperables, ajustar la cantidad disponible del lote
        lote.cantidad = fila["cantidad_recibida_conforme"]
        lote.save(update_fields=["estado_inventario", "cantidad", "updated_at"])

    # Actualizar estado de la remisión a RETORNADA
    remision.estado = catalog.REMISSION_RETURNED
    remision.save(update_fields=["estado", "updated_at"])

    return serialize_reception_detail(recepcion)


def list_laundry_receptions():
    """Lista el historial de actas de recepción de lavandería ordenadas cronológicamente."""
    recepciones = (
        RecepcionLavanderia.objects.filter(deleted_at__isnull=True)
        .select_related("remision__lavanderia", "responsable")
        .prefetch_related(
            "lotes_detalle__lote__orden__referencia",
            "lotes_detalle__remision_lote__receta",
        )
        .order_by("-fecha_recepcion", "-id")
    )
    return [serialize_reception_detail(r) for r in recepciones]


def get_laundry_reception_detail(pk):
    """Obtiene el detalle completo de un acta de recepción por su ID."""
    recepcion = (
        RecepcionLavanderia.objects.filter(pk=pk, deleted_at__isnull=True)
        .select_related("remision__lavanderia", "responsable")
        .prefetch_related(
            "lotes_detalle__lote__orden__referencia",
            "lotes_detalle__remision_lote__receta",
        )
        .first()
    )
    if not recepcion:
        fail("El acta de recepción solicitada no existe.", "id")
    return serialize_reception_detail(recepcion)
