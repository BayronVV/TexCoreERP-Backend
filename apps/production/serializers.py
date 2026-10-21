"""Serializers de producción: entrada y salida de la simulación, órdenes, lotes, etapas, monitor, costeo y recursos."""
from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory import catalog as inventory_catalog
from apps.references.ficha_serializers import ConsumoLineaSerializer

from . import catalog, monitor, resources, tracking
from .models import (
    AsignacionEtapa,
    EtapaLote,
    EventoEtapa,
    Lote,
    LoteTalla,
    Maquina,
    Operario,
    OrdenProduccion,
    TarifaManoObra,
)


class SimulacionInputSerializer(serializers.Serializer):
    """Qué se quiere producir. La cantidad y los lotes se validan en `services` para devolver los errores con el
    mismo formato que el resto de la API (`{campo: [mensaje]}`).
    """
    referencia = serializers.IntegerField()
    cantidad = serializers.JSONField(help_text="Prendas a producir: entero de 1 a 100000")
    lotes = serializers.JSONField(
        required=False, allow_null=True,
        help_text="Tamaño de cada lote, p. ej. [50, 50, 100]. Deben sumar exactamente la cantidad.",
    )


class CuelloDeBotellaSerializer(serializers.Serializer):
    """El material que limita cuántas prendas se pueden fabricar con el stock actual."""
    producto = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    unidad = serializers.CharField()
    disponible = serializers.DecimalField(max_digits=14, decimal_places=2)
    maximo = serializers.IntegerField(help_text="Prendas que alcanzan con este material")


class LoteSimuladoSerializer(serializers.Serializer):
    """Cobertura de un lote en la simulación: acumulado de prendas y si el stock alcanza."""
    numero = serializers.IntegerField()
    cantidad = serializers.IntegerField()
    acumulado = serializers.IntegerField(help_text="Prendas de los lotes 1..n juntos")
    cubierto = serializers.BooleanField(help_text="Alcanza el stock para los lotes 1..n juntos")
    faltantes = serializers.ListField(child=serializers.CharField(), help_text="Materiales que no alcanzan")


class SimulacionSalidaSerializer(serializers.Serializer):
    """Resultado de la simulación: viabilidad, líneas, faltantes, máximo producible y cobertura por lote."""
    referencia = serializers.DictField()
    cantidad = serializers.IntegerField()
    viable = serializers.BooleanField(help_text="Hay material para todo el total")
    lineas = ConsumoLineaSerializer(many=True)
    faltantes = ConsumoLineaSerializer(many=True)
    maximo_producible = serializers.IntegerField(help_text="Prendas que se pueden fabricar con el stock actual")
    cuello_de_botella = CuelloDeBotellaSerializer(help_text="El material que limita ese máximo")
    lotes = LoteSimuladoSerializer(many=True, allow_null=True)
    lotes_cubiertos = serializers.IntegerField(allow_null=True)


# --- Órdenes de producción y lotes (HU 4.2) ---

class OrdenProduccionInputSerializer(serializers.Serializer):
    """Datos para crear la orden. Las cantidades de material no se envían: salen de la ficha técnica."""
    referencia = serializers.IntegerField()
    cantidad = serializers.JSONField(help_text="Prendas a producir: entero de 1 a 100000")
    producto_resultado = serializers.IntegerField(help_text="Pantalón genérico que resulta de la producción")
    fecha_salida = serializers.DateField(required=False, allow_null=True, default=None)
    responsable = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    lotes = serializers.JSONField(
        required=False, allow_null=True,
        help_text="Lotes `[{cantidad, tallas: [{variante, cantidad}]}]`. Sin lotes se crea uno solo con todo el total.",
    )


class LoteTallaSerializer(serializers.ModelSerializer):
    """Prendas de una talla y color dentro de un lote."""
    class Meta:
        model = LoteTalla
        fields = ["variante", "talla", "color", "cantidad"]


class RecursoOperarioSerializer(serializers.Serializer):
    """Resumen de un operario (id, código y nombre) dentro de una asignación."""
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    nombres = serializers.CharField()


class RecursoMaquinaSerializer(serializers.Serializer):
    """Resumen de una máquina (id, código y tipo) dentro de una asignación."""
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    tipo = serializers.CharField()
    tipo_nombre = serializers.CharField()


class AsignacionActualSerializer(serializers.Serializer):
    """Quién y con qué máquina trabaja la etapa ahora."""
    id = serializers.IntegerField()
    operario = RecursoOperarioSerializer(allow_null=True)
    maquina = RecursoMaquinaSerializer(allow_null=True)
    desde = serializers.DateTimeField()


class EtapaLoteSerializer(serializers.ModelSerializer):
    """Una etapa del lote con su tiempo neto (sin pausas) hasta este momento."""
    etapa_nombre = serializers.CharField(source="get_etapa_display", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    en_curso_desde = serializers.DateTimeField(
        source="reanudada_at", read_only=True,
        help_text="Inicio del intervalo que está corriendo (vacío si no corre). Sirve para mostrar el reloj en vivo.",
    )
    tiempo_neto_segundos = serializers.SerializerMethodField()
    responsable_nombre = serializers.SerializerMethodField()
    asignacion = serializers.SerializerMethodField(help_text="Operario y máquina que la trabajan ahora (HU 4.4); vacío si no hay")

    class Meta:
        model = EtapaLote
        fields = [
            "id", "etapa", "etapa_nombre", "secuencia", "estado", "estado_nombre", "inicio_at", "fin_at",
            "en_curso_desde", "tiempo_neto_segundos", "responsable_nombre", "asignacion",
        ]

    @extend_schema_field(AsignacionActualSerializer(allow_null=True))
    def get_asignacion(self, obj):
        row = resources.open_assignment_of(obj)
        if row is None:
            return None
        return {
            "id": row.id,
            "operario": None if row.operario is None else {
                "id": row.operario_id, "codigo": row.operario.codigo, "nombres": row.operario.nombres,
            },
            "maquina": None if row.maquina is None else {
                "id": row.maquina_id, "codigo": row.maquina.codigo, "tipo": row.maquina.tipo,
                "tipo_nombre": row.maquina.get_tipo_display(),
            },
            "desde": row.inicio_at,
        }

    def get_tiempo_neto_segundos(self, obj) -> int:
        return tracking.net_seconds(obj)

    def get_responsable_nombre(self, obj) -> str:
        return (obj.responsable.get_full_name() or obj.responsable.email) if obj.responsable else ""


class LoteSerializer(serializers.ModelSerializer):
    """Lote con sus tallas, su estado derivado (RF15), sus etapas con tiempos (RF13) y las acciones que admite ahora."""
    tallas = LoteTallaSerializer(many=True, read_only=True)
    etapas = EtapaLoteSerializer(many=True, read_only=True)
    estado = serializers.SerializerMethodField()
    estado_nombre = serializers.SerializerMethodField()
    etapa_actual = serializers.SerializerMethodField()
    tiempo_neto_segundos = serializers.SerializerMethodField()
    acciones = serializers.SerializerMethodField()

    class Meta:
        model = Lote
        fields = [
            "id", "numero", "codigo", "cantidad", "tallas", "estado", "estado_nombre", "etapa_actual",
            "tiempo_neto_segundos", "acciones", "etapas",
        ]

    @staticmethod
    def _cancelled(obj):
        return obj.orden.orden_salida.estado == inventory_catalog.STATUS_CANCELLED

    @staticmethod
    def _states(obj):
        return [stage.estado for stage in obj.etapas.all()]

    def get_estado(self, obj) -> str:
        return tracking.lot_state(self._states(obj), self._cancelled(obj))

    def get_estado_nombre(self, obj) -> str:
        return catalog.STATE_NAMES[self.get_estado(obj)]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_etapa_actual(self, obj):
        stage = tracking.current_stage(list(obj.etapas.all()))
        return stage.etapa if stage else None

    def get_tiempo_neto_segundos(self, obj) -> int:
        return sum(tracking.net_seconds(stage) for stage in obj.etapas.all())

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_acciones(self, obj):
        return tracking.available_actions(self._states(obj), self._cancelled(obj))


class EventoEtapaSerializer(serializers.ModelSerializer):
    """Un evento del historial de una etapa: acción, usuario y momento."""
    etapa = serializers.CharField(source="etapa_lote.etapa", read_only=True)
    etapa_nombre = serializers.CharField(source="etapa_lote.get_etapa_display", read_only=True)
    accion_nombre = serializers.CharField(source="get_accion_display", read_only=True)
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = EventoEtapa
        fields = ["id", "etapa", "etapa_nombre", "accion", "accion_nombre", "de_estado", "a_estado", "momento",
                  "usuario_nombre", "nota"]

    def get_usuario_nombre(self, obj) -> str:
        return (obj.usuario.get_full_name() or obj.usuario.email) if obj.usuario else ""


class AccionLoteSerializer(serializers.Serializer):
    """Nota opcional que acompaña una acción sobre un lote."""
    nota = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class OrdenProduccionSerializer(serializers.ModelSerializer):
    """Orden con sus lotes y tallas. El estado y la anulación se leen de la salida de inventario."""
    estado = serializers.CharField(source="orden_salida.estado", read_only=True)
    estado_nombre = serializers.CharField(source="orden_salida.get_estado_display", read_only=True)
    fecha_salida = serializers.DateField(source="orden_salida.fecha_salida", read_only=True)
    responsable = serializers.CharField(source="orden_salida.responsable", read_only=True)
    observaciones = serializers.CharField(source="orden_salida.observaciones", read_only=True)
    producto_resultado = serializers.IntegerField(source="orden_salida.producto_resultado_id", read_only=True)
    producto_resultado_nombre = serializers.CharField(source="orden_salida.producto_resultado.nombre", read_only=True)
    motivo_anulacion = serializers.CharField(source="orden_salida.motivo_anulacion", read_only=True)
    anulada_at = serializers.DateTimeField(source="orden_salida.anulada_at", read_only=True)
    referencia_codigo = serializers.CharField(source="referencia.codigo", read_only=True)
    referencia_nombre = serializers.CharField(source="referencia.nombre", read_only=True)
    creado_por_nombre = serializers.SerializerMethodField()
    materiales = serializers.SerializerMethodField()
    lotes = LoteSerializer(many=True, read_only=True)
    estado_produccion = serializers.SerializerMethodField(help_text="Planeada, en proceso, en pausa, terminada o cancelada")
    estado_produccion_nombre = serializers.SerializerMethodField()
    tiempo_neto_segundos = serializers.SerializerMethodField()

    class Meta:
        model = OrdenProduccion
        fields = [
            "id", "codigo", "orden_salida", "estado", "estado_nombre", "referencia", "referencia_codigo",
            "referencia_nombre", "cantidad", "fecha_salida", "responsable", "observaciones", "producto_resultado",
            "producto_resultado_nombre", "motivo_anulacion", "anulada_at", "creado_por_nombre", "created_at",
            "materiales", "estado_produccion", "estado_produccion_nombre", "tiempo_neto_segundos", "lotes",
        ]

    def get_estado_produccion(self, obj) -> str:
        if obj.orden_salida.estado == inventory_catalog.STATUS_CANCELLED:
            return catalog.STATE_CANCELLED
        return tracking.order_state(
            tracking.lot_state([stage.estado for stage in lot.etapas.all()]) for lot in obj.lotes.all()
        )

    def get_estado_produccion_nombre(self, obj) -> str:
        return catalog.STATE_NAMES[self.get_estado_produccion(obj)]

    def get_tiempo_neto_segundos(self, obj) -> int:
        return sum(tracking.net_seconds(stage) for lot in obj.lotes.all() for stage in lot.etapas.all())

    def get_creado_por_nombre(self, obj) -> str:
        return (obj.creado_por.get_full_name() or obj.creado_por.email) if obj.creado_por else ""

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_materiales(self, obj):
        """Lo que se descontó del almacén por esta orden (las líneas de la salida)."""
        return [
            {"producto": line.producto_id, "codigo": line.producto.codigo, "nombre": line.producto.nombre,
             "unidad": line.producto.unidad, "cantidad": str(line.cantidad),
             "costo_unitario": None if line.costo_unitario is None else str(line.costo_unitario)}
            for line in obj.orden_salida.lineas.all()
        ]


class AnulacionProduccionSerializer(serializers.Serializer):
    """Motivo obligatorio para anular una orden de producción."""
    motivo = serializers.CharField(max_length=255)


class TarjetaLoteSerializer(serializers.Serializer):
    """Lote del tablero de estado: lo justo para mostrar una tarjeta y decidir qué acciones ofrecer."""
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    cantidad = serializers.IntegerField()
    orden = serializers.IntegerField(source="orden_id")
    orden_codigo = serializers.CharField(source="orden.codigo")
    referencia = serializers.IntegerField(source="orden.referencia_id")
    referencia_codigo = serializers.CharField(source="orden.referencia.codigo")
    referencia_nombre = serializers.CharField(source="orden.referencia.nombre")
    estado = serializers.SerializerMethodField()
    estado_nombre = serializers.SerializerMethodField()
    etapa_actual = serializers.SerializerMethodField()
    etapa_actual_nombre = serializers.SerializerMethodField()
    etapas_terminadas = serializers.SerializerMethodField()
    etapas_total = serializers.SerializerMethodField()
    termina_el_lote = serializers.SerializerMethodField(
        help_text="Terminar la etapa en curso deja el lote terminado (es la última etapa)"
    )
    tiempo_neto_segundos = serializers.SerializerMethodField()
    en_curso_desde = serializers.SerializerMethodField()
    responsable_nombre = serializers.SerializerMethodField()
    operario_nombre = serializers.SerializerMethodField(help_text="Operario asignado a la etapa en curso (HU 4.4); vacío si no hay")
    maquina_codigo = serializers.SerializerMethodField(help_text="Máquina asignada a la etapa en curso (HU 4.4); vacío si no hay")
    ultimo_movimiento = serializers.DateTimeField(allow_null=True)
    espera_segundos = serializers.SerializerMethodField(
        help_text="Segundos detenido (en pausa o entre etapas) desde su último movimiento; vacío si no está detenido"
    )
    alerta = serializers.SerializerMethodField(help_text="ATENCION desde 2 h detenido, CRITICA desde 8 h; vacío si no hay alerta")
    acciones = serializers.SerializerMethodField()

    @staticmethod
    def _stages(obj):
        return list(obj.etapas.all())

    @staticmethod
    def _cancelled(obj):
        return obj.orden.orden_salida.estado == inventory_catalog.STATUS_CANCELLED

    def _current(self, obj):
        return tracking.current_stage(self._stages(obj))

    def get_estado(self, obj) -> str:
        return tracking.lot_state([stage.estado for stage in self._stages(obj)], self._cancelled(obj))

    def get_estado_nombre(self, obj) -> str:
        return catalog.STATE_NAMES[self.get_estado(obj)]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_etapa_actual(self, obj):
        stage = self._current(obj)
        return stage.etapa if stage else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_etapa_actual_nombre(self, obj):
        stage = self._current(obj)
        return catalog.STAGE_NAMES[stage.etapa] if stage else None

    def get_etapas_terminadas(self, obj) -> int:
        return sum(1 for stage in self._stages(obj) if stage.estado == catalog.STAGE_DONE)

    def get_etapas_total(self, obj) -> int:
        return len(self._stages(obj))

    def get_termina_el_lote(self, obj) -> bool:
        stages = self._stages(obj)
        stage = tracking.current_stage(stages)
        in_course = stage is not None and stage.estado in (catalog.STAGE_RUNNING, catalog.STAGE_PAUSED)
        return not self._cancelled(obj) and in_course and all(
            other.estado == catalog.STAGE_DONE for other in stages if other is not stage
        )

    def get_tiempo_neto_segundos(self, obj) -> int:
        return sum(tracking.net_seconds(stage) for stage in self._stages(obj))

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_en_curso_desde(self, obj):
        return next((stage.reanudada_at for stage in self._stages(obj) if stage.reanudada_at), None)

    def get_responsable_nombre(self, obj) -> str:
        stage = self._current(obj)
        user = stage.responsable if stage else None
        return (user.get_full_name() or user.email) if user else ""

    def get_operario_nombre(self, obj) -> str:
        stage = self._current(obj)
        row = resources.open_assignment_of(stage) if stage else None
        return row.operario.nombres if row and row.operario else ""

    def get_maquina_codigo(self, obj) -> str:
        stage = self._current(obj)
        row = resources.open_assignment_of(stage) if stage else None
        return row.maquina.codigo if row and row.maquina else ""

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_espera_segundos(self, obj):
        if self._cancelled(obj):
            return None
        stage_states = [stage.estado for stage in self._stages(obj)]
        return monitor.stalled_seconds(
            tracking.lot_state(stage_states), stage_states, obj.ultimo_movimiento, self.context.get("now") or timezone.now()
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_alerta(self, obj):
        return monitor.alert_level(self.get_espera_segundos(obj))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_acciones(self, obj):
        return tracking.available_actions([stage.estado for stage in self._stages(obj)], self._cancelled(obj))


class ColumnaMonitorSerializer(serializers.Serializer):
    """Una columna del monitor: estado, total real y las tarjetas que se muestran."""
    estado = serializers.CharField()
    nombre = serializers.CharField()
    total = serializers.IntegerField(help_text="Lotes en esa columna, aunque solo se devuelvan `limite` tarjetas")
    lotes = TarjetaLoteSerializer(many=True)


class MonitorSerializer(serializers.Serializer):
    """Tablero completo del monitor: columnas, resumen de alertas, límite por columna y momento de generación."""
    generado_at = serializers.DateTimeField()
    limite = serializers.IntegerField()
    terminadas_dias = serializers.IntegerField(help_text="La columna Terminada solo muestra los lotes de los últimos N días")
    alertas = serializers.DictField(
        child=serializers.IntegerField(), help_text="Lotes activos detenidos: `atencion` (desde 2 h) y `critica` (desde 8 h)"
    )
    columnas = ColumnaMonitorSerializer(many=True)


# --- Tarifas de mano de obra y costos de producción (HU 4.6, TE-129 / TE-130) ---

class TarifaManoObraSerializer(serializers.ModelSerializer):
    """Tarifa de mano de obra por minuto para una etapa productiva."""
    etapa_nombre = serializers.CharField(source="get_etapa_display", read_only=True)
    costo_minuto = serializers.SerializerMethodField()
    creado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = TarifaManoObra
        fields = [
            "id", "etapa", "etapa_nombre", "costo_minuto", "vigente_desde",
            "creado_por", "creado_por_nombre", "created_at",
        ]
        read_only_fields = ["id", "etapa_nombre", "costo_minuto", "creado_por", "creado_por_nombre", "created_at"]

    def get_costo_minuto(self, obj) -> str:
        return f"{obj.costo_minuto:.4f}"

    def get_creado_por_nombre(self, obj) -> str:
        return (obj.creado_por.get_full_name() or obj.creado_por.email) if obj.creado_por else ""


class TarifaManoObraInputSerializer(serializers.Serializer):
    """Datos para registrar una nueva vigencia de tarifa de mano de obra."""
    etapa = serializers.ChoiceField(choices=catalog.STAGES)
    costo_minuto = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0.0001"),
        help_text="Costo por minuto en COP (mayor que cero, hasta 4 decimales)",
    )
    vigente_desde = serializers.DateField(
        required=False, allow_null=True, default=None,
        help_text="Fecha de vigencia (opcional, por defecto hoy)",
    )


class OrdenCostosInfoSerializer(serializers.Serializer):
    """Datos de cabecera de la orden en la liquidación."""
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    referencia_codigo = serializers.CharField()
    referencia_nombre = serializers.CharField()
    cantidad = serializers.IntegerField()
    estado_produccion = serializers.CharField()
    anulada = serializers.BooleanField()


class MaterialLineaCostoSerializer(serializers.Serializer):
    """Costo de una línea de material: cantidad, costo unitario y subtotal."""
    producto = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    unidad = serializers.CharField()
    cantidad = serializers.CharField()
    costo_unitario = serializers.CharField(allow_null=True)
    costo = serializers.CharField()
    sin_costo = serializers.BooleanField()


class MaterialesCostosSerializer(serializers.Serializer):
    """Costo total de materiales con el detalle por línea."""
    lineas = MaterialLineaCostoSerializer(many=True)
    total = serializers.CharField()


class EtapaLoteCostoSerializer(serializers.Serializer):
    """Costo de mano de obra de una etapa de un lote: tiempo neto, tarifa y costo."""
    etapa = serializers.CharField()
    etapa_nombre = serializers.CharField()
    estado = serializers.CharField()
    segundos_netos = serializers.IntegerField()
    tarifa_minuto = serializers.CharField(allow_null=True)
    costo = serializers.CharField()
    sin_tarifa = serializers.BooleanField()
    provisional = serializers.BooleanField()


class LoteCostoSerializer(serializers.Serializer):
    """Costo de un lote: materiales prorrateados, mano de obra por etapa y total."""
    lote = serializers.IntegerField()
    codigo = serializers.CharField()
    cantidad = serializers.IntegerField()
    materiales_asignados = serializers.CharField()
    etapas = EtapaLoteCostoSerializer(many=True)
    total = serializers.CharField()


class EtapaResumenCostoSerializer(serializers.Serializer):
    """Mano de obra acumulada de una etapa en toda la orden."""
    etapa = serializers.CharField()
    etapa_nombre = serializers.CharField()
    segundos_netos = serializers.IntegerField()
    costo = serializers.CharField()


class ManoObraCostosSerializer(serializers.Serializer):
    """Costo total de mano de obra, por lote y por etapa."""
    por_lote = LoteCostoSerializer(many=True)
    por_etapa = EtapaResumenCostoSerializer(many=True)
    total = serializers.CharField()


class TotalesCostosSerializer(serializers.Serializer):
    """Totales de la liquidación: materiales, mano de obra, total y costo por prenda."""
    materiales = serializers.CharField()
    mano_obra = serializers.CharField()
    total = serializers.CharField()
    costo_por_prenda = serializers.CharField()


class DistribucionCostosSerializer(serializers.Serializer):
    """Distribución porcentual entre materiales y mano de obra."""
    materiales_pct = serializers.CharField()
    mano_obra_pct = serializers.CharField()


class OrdenCostosRespuestaSerializer(serializers.Serializer):
    """Respuesta completa de la liquidación de una orden, con advertencias si el cálculo es parcial."""
    orden = OrdenCostosInfoSerializer()
    completo = serializers.BooleanField()
    advertencias = serializers.ListField(child=serializers.CharField())
    materiales = MaterialesCostosSerializer()
    mano_obra = ManoObraCostosSerializer()
    totales = TotalesCostosSerializer()
    distribucion = DistribucionCostosSerializer()



# --- Asignación de recursos (HU 4.4 / RF14) ---

class OperarioSerializer(serializers.ModelSerializer):
    """Operario con las etapas en las que puede trabajar y dónde está ocupado ahora."""
    tipo_pago_nombre = serializers.CharField(source="get_tipo_pago_display", read_only=True)
    ocupado_en = serializers.SerializerMethodField(help_text="Etapas en curso a las que está asignado, p. ej. `OP-0001-L01 · Corte`")

    class Meta:
        model = Operario
        fields = ["id", "codigo", "nombres", "documento", "etapas", "tipo_pago", "tipo_pago_nombre", "activo", "ocupado_en", "created_at"]

    def get_ocupado_en(self, obj) -> list[str]:
        busy = self.context.get("busy")
        if busy is None:
            busy = resources.busy_by_operator()
        return busy.get(obj.pk, [])


class OperarioInputSerializer(serializers.Serializer):
    """Datos de un operario. En `PATCH` solo se envía lo que cambia."""
    nombres = serializers.CharField(max_length=120)
    documento = serializers.RegexField(
        r"^\d{5,15}$", required=False, allow_blank=True, error_messages={"invalid": "El documento son de 5 a 15 dígitos."},
    )
    etapas = serializers.ListField(child=serializers.CharField(), help_text="Etapas en las que puede trabajar: CORTE, CONFECCION, TERMINACION")
    tipo_pago = serializers.ChoiceField(choices=catalog.PAY_TYPES, required=False)
    activo = serializers.BooleanField(required=False)


class MaquinaSerializer(serializers.ModelSerializer):
    """Máquina con su estado físico y dónde está ocupada ahora."""
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    asignable = serializers.SerializerMethodField(help_text="Está activa y disponible: se puede asignar a una etapa")
    ocupada_en = serializers.SerializerMethodField(help_text="Etapas en curso a las que está asignada, p. ej. `OP-0001-L01 · Confección`")

    class Meta:
        model = Maquina
        fields = [
            "id", "codigo", "tipo", "tipo_nombre", "marca_modelo", "serial", "ubicacion", "estado", "estado_nombre", "etapas",
            "observaciones", "activo", "asignable", "ocupada_en", "created_at",
        ]

    def get_asignable(self, obj) -> bool:
        return obj.activo and obj.estado == catalog.MACHINE_AVAILABLE

    def get_ocupada_en(self, obj) -> list[str]:
        busy = self.context.get("busy")
        if busy is None:
            busy = resources.busy_by_machine()
        return busy.get(obj.pk, [])


class MaquinaInputSerializer(serializers.Serializer):
    """Datos de una máquina. En `PATCH` solo se envía lo que cambia."""
    tipo = serializers.ChoiceField(choices=catalog.MACHINE_TYPES)
    marca_modelo = serializers.CharField(max_length=120, required=False, allow_blank=True)
    serial = serializers.CharField(max_length=60, required=False, allow_blank=True)
    ubicacion = serializers.CharField(max_length=80, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=catalog.MACHINE_STATES, required=False)
    etapas = serializers.ListField(child=serializers.CharField(), help_text="Etapas en las que se usa: CORTE, CONFECCION, TERMINACION")
    observaciones = serializers.CharField(max_length=255, required=False, allow_blank=True)
    activo = serializers.BooleanField(required=False)


class AsignarInputSerializer(serializers.Serializer):
    """Pone, cambia o quita el operario y la máquina de una etapa. La clave que no se envía se deja como está; `null` la quita."""
    etapa = serializers.CharField()
    operario = serializers.IntegerField(required=False, allow_null=True)
    maquina = serializers.IntegerField(required=False, allow_null=True)


class DesvincularInputSerializer(serializers.Serializer):
    """Etapa de la que se quita un recurso, y cuál: operario, máquina o ambos."""
    etapa = serializers.CharField()
    recurso = serializers.ChoiceField(choices=[catalog.RESOURCE_OPERATOR, catalog.RESOURCE_MACHINE, catalog.RESOURCE_BOTH])


class AsignacionRespuestaSerializer(serializers.Serializer):
    """El lote actualizado tras asignar o quitar recursos, con los avisos que no bloquean."""
    lote = LoteSerializer()
    advertencias = serializers.ListField(child=serializers.CharField(), help_text="Avisos que no bloquean (recurso ocupado en otra etapa)")


class RecursoGuardadoSerializer(serializers.Serializer):
    """Respuesta de crear o editar un operario o una máquina: el registro y los avisos que no bloquean."""
    advertencias = serializers.ListField(child=serializers.CharField())


class AsignacionHistorialSerializer(serializers.ModelSerializer):
    """Una fila del historial de asignaciones de una etapa."""
    etapa = serializers.CharField(source="etapa_lote.etapa", read_only=True)
    etapa_nombre = serializers.CharField(source="etapa_lote.get_etapa_display", read_only=True)
    operario_codigo = serializers.CharField(source="operario.codigo", default="", read_only=True)
    operario_nombre = serializers.CharField(source="operario.nombres", default="", read_only=True)
    maquina_codigo = serializers.CharField(source="maquina.codigo", default="", read_only=True)
    maquina_tipo_nombre = serializers.CharField(source="maquina.get_tipo_display", default="", read_only=True)
    asignada_por_nombre = serializers.SerializerMethodField()
    vigente = serializers.SerializerMethodField()

    class Meta:
        model = AsignacionEtapa
        fields = [
            "id", "etapa", "etapa_nombre", "operario_codigo", "operario_nombre", "maquina_codigo", "maquina_tipo_nombre",
            "inicio_at", "fin_at", "vigente", "asignada_por_nombre",
        ]

    def get_asignada_por_nombre(self, obj) -> str:
        return (obj.asignada_por.get_full_name() or obj.asignada_por.email) if obj.asignada_por else ""

    def get_vigente(self, obj) -> bool:
        return obj.fin_at is None
