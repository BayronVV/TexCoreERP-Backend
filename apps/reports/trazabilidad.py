"""Trazabilidad de punta a punta (HU 7.6, TE-176): el recorrido de un lote y de una factura por todos los módulos.

Solo lectura y armada en vivo desde los registros de cada módulo: no hay tabla «traza» ni se recalculan costos o
saldos. Cada bloque se arma solo si el usuario tiene el permiso de consulta de su módulo; si no, el bloque es
`{"acceso": False}` sin datos, conteos ni códigos (el filtrado es del servidor, no de la pantalla).

Las consultas están acotadas: `select_related` y `Prefetch` por bloque, así que su número no crece con las filas.

Límites honestos:
- La salida de materiales de una orden no guarda el lote de compra (`Movimiento.lote` lleva el código de la
  referencia). Por material se muestran las últimas recepciones antes de la salida: compras previas, no la exacta.
- El producto terminado se lleva por talla y color, no por lote. De una factura se listan los lotes que ingresaron
  esa variante hasta la fecha de la factura, no «el lote de esta prenda».
"""
from django.db.models import Count, F, Prefetch, Window
from django.db.models.functions import RowNumber
from django.http import Http404

from apps.finished.models import IngresoLinea, IngresoTerminado, MovimientoTerminado
from apps.inventory import catalog as inventory_catalog
from apps.inventory.models import Movimiento, OrdenLinea
from apps.production import catalog as production_catalog
from apps.production import tracking
from apps.production.models import AsignacionEtapa, EtapaLote, Lote, OrdenProduccion, RecepcionLote, RemisionLote
from apps.quality.models import Inspeccion, MarraDetalle
from apps.references.models import FichaTecnica
from apps.sales.models import FacturaVenta, MovimientoCartera
from apps.shipping import catalog as shipping_catalog
from apps.shipping.models import EventoGuia, Guia, RelacionDespacho

from . import catalog

PREVIOUS_PURCHASES = 3  # recepciones previas que se muestran por material
SOURCE_LOTS = 10  # lotes que se muestran por variante vendida (con el total, para decir cuántos hay)

NO_ACCESS = {"acceso": False}
MERMA_NAMES = dict(production_catalog.MERMA_REASONS)  # texto libre si no es uno del catálogo
DAMAGE_NAMES = dict(production_catalog.DAMAGE_TYPES)
GUIDE_STATE_NAMES = dict(shipping_catalog.GUIDE_STATES)


def _person(user):
    return (user.get_full_name() or user.email) if user else ""


def _grant(user, block):
    return user.has_permission_code(catalog.TRACE_BLOCKS[block])


# ------------------------------------------------------------------------------------------------- búsqueda única


def search(code):
    """Resuelve un código exacto (sin distinguir mayúsculas) a lo que hay que mostrar.

    Devuelve `{"tipo": "lote"|"factura", "codigo": ...}` cuando lleva a una sola traza, `{"tipo": "orden"|"relacion",
    "codigo", "opciones": [...]}` cuando hay que elegir, o `{"tipo": None}` si no existe. Solo hay consultas exactas.
    """
    text = (code or "").strip()
    if not text:
        return {"tipo": None, "codigo": ""}

    lot = Lote.objects.filter(codigo__iexact=text).values("codigo").first()
    if lot:
        return {"tipo": "lote", "codigo": lot["codigo"]}
    order = OrdenProduccion.objects.filter(codigo__iexact=text).first()
    if order:
        lots = list(order.lotes.order_by("numero").values("codigo", "cantidad"))
        if len(lots) == 1:
            return {"tipo": "lote", "codigo": lots[0]["codigo"]}
        return {"tipo": "orden", "codigo": order.codigo, "opciones": [
            {"tipo": "lote", "codigo": row["codigo"], "detalle": f"{row['cantidad']} prendas"} for row in lots
        ]}
    invoice = FacturaVenta.objects.filter(numero__iexact=text).values("numero").first()
    if invoice:
        return {"tipo": "factura", "codigo": invoice["numero"]}
    inspection = Inspeccion.objects.filter(codigo__iexact=text).values("lote__codigo").first()
    if inspection:
        return {"tipo": "lote", "codigo": inspection["lote__codigo"]}
    entry = IngresoTerminado.objects.filter(codigo__iexact=text).values("lote__codigo").first()
    if entry:
        return {"tipo": "lote", "codigo": entry["lote__codigo"]}
    dispatch = RelacionDespacho.objects.filter(codigo__iexact=text).first()
    if dispatch:
        rows = Guia.objects.filter(relacion=dispatch).order_by("id").values("factura__numero", "numero_guia")
        return {"tipo": "relacion", "codigo": dispatch.codigo, "opciones": [
            {"tipo": "factura", "codigo": row["factura__numero"], "detalle": f"Guía {row['numero_guia']}"} for row in rows
        ]}
    guide = Guia.objects.filter(numero_guia__iexact=text).order_by("-vigente", "-id").values("factura__numero").first()
    if guide:
        return {"tipo": "factura", "codigo": guide["factura__numero"]}
    return {"tipo": None, "codigo": text}


# ---------------------------------------------------------------------------------------------------------- lote


def lot_trace(user, code):
    """Recorrido de un lote: referencia, orden y materiales, etapas, lavandería, calidad e ingreso a producto terminado."""
    lot = (
        Lote.objects.select_related("orden__referencia", "orden__orden_salida", "orden__creado_por")
        .filter(codigo__iexact=(code or "").strip()).first()
    )
    if lot is None:
        raise Http404("No encontramos ningún lote con ese código.")
    order = lot.orden
    reference = order.referencia

    data = {
        "tipo": "lote",
        "codigo": lot.codigo,
        "referencia_codigo": reference.codigo,
        "referencia_nombre": reference.nombre,
        "referencia": _reference_block(user, reference),
        "orden": NO_ACCESS,
        "materiales": NO_ACCESS,
        "etapas": NO_ACCESS,
        "lavanderia": NO_ACCESS,
        "calidad": NO_ACCESS,
        "ingreso": NO_ACCESS,
    }
    sent = received = explained_laundry = approved = explained_quality = entered = None

    if _grant(user, "orden"):
        stages = list(
            EtapaLote.objects.filter(lote=lot).select_related("responsable").order_by("secuencia")
            .prefetch_related(Prefetch(
                "asignaciones",
                queryset=AsignacionEtapa.objects.select_related("operario", "maquina").order_by("inicio_at", "id"),
                to_attr="trace_assignments",
            ))
        )
        cancelled = order.orden_salida.estado == inventory_catalog.STATUS_CANCELLED
        state = tracking.lot_state([stage.estado for stage in stages], cancelled=cancelled)
        data["orden"] = {
            "acceso": True,
            "codigo": order.codigo,
            "fecha": order.orden_salida.fecha_salida,
            "estado_orden": order.orden_salida.estado,
            "estado_orden_nombre": order.orden_salida.get_estado_display(),
            "cantidad_orden": order.cantidad,
            "cantidad_lote": lot.cantidad,
            "estado_lote": state,
            "estado_lote_nombre": production_catalog.STATE_NAMES.get(state, state),
            "creado_por": _person(order.creado_por),
            "tallas": [
                {"talla": row.talla, "color": row.color, "cantidad": row.cantidad}
                for row in lot.tallas.order_by("id")
            ],
        }
        data["etapas"] = {"acceso": True, "items": [_stage(stage) for stage in stages]}

    if _grant(user, "materiales"):
        data["materiales"] = _materials_block(user, order.orden_salida)

    if _grant(user, "lavanderia"):
        dispatches = list(
            RemisionLote.objects.filter(lote=lot).select_related("remision__lavanderia").order_by("remision__fecha_emision", "id")
        )
        receptions = list(
            RecepcionLote.objects.filter(lote=lot).select_related("recepcion").order_by("recepcion__fecha_recepcion", "id")
        )
        sent = sum(row.cantidad for row in dispatches) if dispatches else None
        if receptions:
            received = sum(row.cantidad_recibida_conforme for row in receptions)
            explained_laundry = sum(row.cantidad_merma + row.cantidad_danada for row in receptions)
        data["lavanderia"] = {
            "acceso": True,
            "remisiones": [{
                "codigo": row.remision.codigo,
                "fecha": row.remision.fecha_emision,
                "lavanderia": row.remision.lavanderia.razon_social,
                "receta": row.receta_nombre,
                "enviadas": row.cantidad,
                "estado": row.remision.estado,
                "estado_nombre": row.remision.get_estado_display(),
            } for row in dispatches],
            "recepciones": [{
                "codigo": row.recepcion.codigo,
                "fecha": row.recepcion.fecha_recepcion,
                "enviadas": row.cantidad_enviada,
                "recibidas_conformes": row.cantidad_recibida_conforme,
                "merma": row.cantidad_merma,
                "danadas": row.cantidad_danada,
                "motivo_merma": MERMA_NAMES.get(row.motivo_merma, row.motivo_merma),
                "tipo_dano": DAMAGE_NAMES.get(row.tipo_dano, row.tipo_dano),
            } for row in receptions],
        }

    if _grant(user, "calidad"):
        inspection = (
            Inspeccion.objects.filter(lote=lot).select_related("inspector")
            .prefetch_related(Prefetch("detalle", queryset=MarraDetalle.objects.order_by("id"), to_attr="trace_defects"))
            .first()
        )
        if inspection is not None:
            approved = inspection.aptas
            explained_quality = inspection.marras
        data["calidad"] = {"acceso": True, "inspeccion": None if inspection is None else {
            "codigo": inspection.codigo,
            "fecha": inspection.fecha,
            "inspector": _person(inspection.inspector),
            "recibidas": inspection.cantidad_recibida,
            "aptas": inspection.aptas,
            "marras": inspection.marras,
            "defectos": [{"defecto": row.defecto_nombre, "cantidad": row.cantidad} for row in inspection.trace_defects],
        }}

    if _grant(user, "ingreso"):
        entries = list(
            IngresoTerminado.objects.filter(lote=lot).select_related("recibido_por").order_by("fecha", "id")
            .prefetch_related(Prefetch("lineas", queryset=IngresoLinea.objects.order_by("id"), to_attr="trace_lines"))
        )
        if entries:
            entered = sum(row.cantidad for entry in entries for row in entry.trace_lines)
        data["ingreso"] = {"acceso": True, "items": [{
            "codigo": entry.codigo,
            "fecha": entry.fecha,
            "recibido_por": _person(entry.recibido_por),
            "ubicacion": entry.ubicacion,
            "lineas": [{"talla": row.talla, "color": row.color, "cantidad": row.cantidad} for row in entry.trace_lines],
        } for entry in entries]}

    planned = lot.cantidad if data["orden"]["acceso"] else None
    data["conciliacion"] = reconcile([
        ("PLANIFICADO", "Planificadas", data["orden"]["acceso"], planned, None),
        ("ENVIADO", "Enviadas a lavandería", data["lavanderia"]["acceso"], sent, None),
        ("RECIBIDO", "Recibidas conformes", data["lavanderia"]["acceso"], received, explained_laundry),
        ("APTAS", "Aptas en calidad", data["calidad"]["acceso"], approved, explained_quality),
        ("INGRESADO", "Ingresadas a producto terminado", data["ingreso"]["acceso"], entered, None),
    ])
    return data


def reconcile(steps):
    """Franja de conciliación: cada paso con su cantidad y la diferencia frente al anterior.

    `steps` es una lista de `(clave, etiqueta, acceso, cantidad, explicada)`, donde `explicada` son las prendas que un
    registro del paso justifica (merma y dañadas en la recepción, marras en calidad). Una diferencia es «sin justificar»
    cuando lo registrado no la explica. Sin acceso no hay cantidad; sin registro, el paso está pendiente.
    """
    rows, previous = [], None
    for key, label, access, quantity, explained in steps:
        row = {"paso": key, "etiqueta": label, "acceso": access}
        if not access:
            rows.append(row)
            previous = None
            continue
        row.update({"cantidad": quantity, "pendiente": quantity is None})
        if quantity is not None and previous is not None:
            difference = previous - quantity
            justified = min(max(difference, 0), explained or 0)
            row.update({
                "diferencia": difference,
                "porcentaje": round(difference * 100 / previous, 1) if previous else 0.0,
                "justificada": justified,
                "sin_justificar": difference - justified,
            })
        rows.append(row)
        previous = quantity
    return rows


def _reference_block(user, reference):
    if not _grant(user, "referencia"):
        return NO_ACCESS
    block = {"acceso": True, "id": reference.id, "codigo": reference.codigo, "nombre": reference.nombre, "ficha": NO_ACCESS}
    if _grant(user, "ficha"):
        sheet = FichaTecnica.objects.filter(referencia=reference).select_related("actualizado_por").order_by("-updated_at", "-id").first()
        block["ficha"] = {"acceso": True, "existe": sheet is not None} | ({} if sheet is None else {
            "lavado": sheet.get_lavado_display() if sheet.lavado else "",
            "notas": sheet.notas,
            "actualizada": sheet.updated_at,
            "actualizada_por": _person(sheet.actualizado_por),
        })
    return block


def _stage(stage):
    return {
        "etapa": stage.etapa,
        "etapa_nombre": production_catalog.STAGE_NAMES.get(stage.etapa, stage.etapa),
        "estado": stage.estado,
        "estado_nombre": production_catalog.STAGE_STATE_NAMES.get(stage.estado, stage.estado),
        "inicio": stage.inicio_at,
        "fin": stage.fin_at,
        "tiempo_neto_segundos": tracking.net_seconds(stage),
        "responsable": _person(stage.responsable),
        "asignaciones": [{
            "operario": row.operario.nombres if row.operario else "",
            "maquina": row.maquina.codigo if row.maquina else "",
            "desde": row.inicio_at,
            "hasta": row.fin_at,
        } for row in stage.trace_assignments],
    }


def _materials_block(user, exit_order):
    lines = list(OrdenLinea.objects.filter(orden=exit_order).select_related("producto").order_by("id"))
    purchases = {}
    show_purchases = _grant(user, "compras")
    if show_purchases and lines:
        # Ingresos por compra del material hasta la fecha de la salida: los de Compras (con su recepción y su orden)
        # y los registrados a mano en Inventario (proveedor, orden y lote escritos en el movimiento).
        rows = (
            Movimiento.objects
            .filter(producto_id__in=[line.producto_id for line in lines], tipo=inventory_catalog.ENTRY,
                    motivo=inventory_catalog.REASON_PURCHASE, fecha__lte=exit_order.fecha_salida)
            .select_related("proveedor", "recepcion_linea__recepcion__orden")
            .annotate(rank=Window(RowNumber(), partition_by=[F("producto_id")], order_by=[F("fecha").desc(), F("id").desc()]))
            .filter(rank__lte=PREVIOUS_PURCHASES)
            .order_by("producto_id", "rank")
        )
        for row in rows:
            reception = getattr(row, "recepcion_linea", None)
            reception = reception.recepcion if reception else None
            purchases.setdefault(row.producto_id, []).append({
                "fecha": row.fecha,
                "recepcion": reception.codigo if reception else "",
                "documento": reception.documento if reception else "",
                "orden_compra": (reception.orden.codigo if reception and reception.orden else row.orden_compra),
                "proveedor": row.proveedor.razon_social if row.proveedor else row.proveedor_nombre,
                "lote_proveedor": row.lote,
                "cantidad": row.cantidad,
            })
    return {
        "acceso": True,
        "orden_salida": exit_order.codigo,
        "fecha": exit_order.fecha_salida,
        "lineas": [{
            "producto_codigo": line.producto.codigo,
            "producto_nombre": line.producto.nombre,
            "unidad": line.producto.unidad,
            "cantidad": line.cantidad,
            "compras_previas": (
                {"acceso": True, "items": purchases.get(line.producto_id, [])} if show_purchases else NO_ACCESS
            ),
        } for line in lines],
    }


# ------------------------------------------------------------------------------------------------------- factura


def invoice_trace(user, number):
    """Recorrido de una factura: venta, movimientos de existencias y lotes de origen, guías con su historial y cobro."""
    invoice = FacturaVenta.objects.select_related("vendedor", "cobrado_por").filter(numero__iexact=(number or "").strip()).first()
    if invoice is None:
        raise Http404("No encontramos ninguna factura con ese número.")
    data = {
        "tipo": "factura",
        "numero": invoice.numero,
        "fecha": invoice.fecha,
        "venta": NO_ACCESS,
        "existencias": NO_ACCESS,
        "envio": NO_ACCESS,
        "cobro": NO_ACCESS,
    }
    lines = None
    if _grant(user, "venta") or _grant(user, "existencias"):
        lines = list(invoice.lineas.order_by("id"))

    if _grant(user, "venta"):
        data["venta"] = {
            "acceso": True,
            "cliente": invoice.cliente_nombre,
            "cliente_documento": invoice.cliente_documento,
            "cliente_ciudad": invoice.cliente_ciudad,
            "vendedor": _person(invoice.vendedor),
            "estado": invoice.estado,
            "estado_nombre": invoice.get_estado_display(),
            "modalidad_pago": invoice.get_modalidad_pago_display(),
            "total": invoice.total,
            "valor_a_recaudar": invoice.valor_a_recaudar,
            "lineas": [{
                "referencia_codigo": line.referencia_codigo,
                "referencia_nombre": line.referencia_nombre,
                "talla": line.talla,
                "color": line.color,
                "cantidad": line.cantidad,
                "total": line.total,
            } for line in lines],
        }
        ledger = list(MovimientoCartera.objects.filter(factura=invoice).select_related("usuario").order_by("created_at", "id"))
        data["cobro"] = {
            "acceso": True,
            "estado_cobro": invoice.estado_cobro,
            "estado_cobro_nombre": invoice.get_estado_cobro_display(),
            "fecha_cobro": invoice.fecha_cobro,
            "cobrado_por": _person(invoice.cobrado_por),
            "motivo_devolucion": invoice.motivo_devolucion,
            "movimientos": [{
                "tipo": row.tipo,
                "tipo_nombre": row.get_tipo_display(),
                "monto": row.monto,
                "fecha": row.created_at,
                "usuario": _person(row.usuario),
                "observaciones": row.observaciones,
            } for row in ledger],
        }

    if _grant(user, "existencias"):
        data["existencias"] = _stock_block(invoice, lines)

    if _grant(user, "envio"):
        guides = list(
            Guia.all_objects.filter(factura=invoice).select_related("relacion").order_by("-vigente", "-id")
            .prefetch_related(Prefetch("eventos", queryset=EventoGuia.objects.select_related("usuario").order_by("created_at", "id"),
                                       to_attr="trace_events"))
        )
        data["envio"] = {"acceso": True, "guias": [{
            "numero_guia": guide.numero_guia,
            "transportadora": guide.get_transportadora_display(),
            "estado": guide.estado,
            "estado_nombre": guide.get_estado_display(),
            "vigente": guide.vigente and guide.deleted_at is None,
            "relacion": guide.relacion.codigo if guide.relacion else "",
            "despachada_en": guide.despachada_en,
            "entregada_en": guide.entregada_en,
            "devuelta_en": guide.devuelta_en,
            "novedad": guide.novedad,
            "eventos": [{
                "fecha": event.created_at,
                "estado_antes": event.estado_antes,
                "estado_antes_nombre": GUIDE_STATE_NAMES.get(event.estado_antes, event.estado_antes),
                "estado_despues": event.estado_despues,
                "estado_despues_nombre": GUIDE_STATE_NAMES.get(event.estado_despues, event.estado_despues),
                "nota": event.nota,
                "origen": event.origen,
                "origen_nombre": event.get_origen_display(),
                "usuario": _person(event.usuario),
            } for event in guide.trace_events],
        } for guide in guides]}
    return data


def _stock_block(invoice, lines):
    movements = list(
        MovimientoTerminado.objects.filter(factura=invoice).select_related("variante__referencia", "usuario").order_by("created_at", "id")
    )
    variant_ids = [line.variante_id for line in lines]
    sources = {}
    totals = {}
    if variant_ids:
        rows = (
            IngresoLinea.objects
            .filter(variante_id__in=variant_ids, ingreso__fecha__lte=invoice.fecha)
            .select_related("ingreso__lote")
            .annotate(rank=Window(RowNumber(), partition_by=[F("variante_id")],
                                  order_by=[F("ingreso__fecha").desc(), F("id").desc()]),
                      total=Window(Count("id"), partition_by=[F("variante_id")]))
            .filter(rank__lte=SOURCE_LOTS)
            .order_by("variante_id", "rank")
        )
        for row in rows:
            totals[row.variante_id] = row.total
            sources.setdefault(row.variante_id, []).append({
                "lote": row.ingreso.lote.codigo,
                "ingreso": row.ingreso.codigo,
                "fecha": row.ingreso.fecha,
                "cantidad": row.cantidad,
            })
    return {
        "acceso": True,
        "movimientos": [{
            "tipo": row.tipo,
            "tipo_nombre": row.get_tipo_display(),
            "fecha": row.created_at,
            "referencia": row.variante.referencia.codigo,
            "talla": row.variante.talla,
            "color": row.variante.color,
            "cantidad": row.cantidad,
            "saldo_despues": row.saldo_despues,
            "usuario": _person(row.usuario),
            "motivo": row.motivo,
        } for row in movements],
        "lotes_de_origen": [{
            "referencia": line.referencia_codigo,
            "talla": line.talla,
            "color": line.color,
            "lotes": sources.get(line.variante_id, []),
            "total_lotes": totals.get(line.variante_id, 0),
        } for line in lines],
    }
