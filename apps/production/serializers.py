from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory import catalog as inventory_catalog
from apps.references.ficha_serializers import ConsumoLineaSerializer

from . import catalog, monitor, tracking
from .models import EtapaLote, EventoEtapa, Lote, LoteTalla, OrdenProduccion


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
    producto = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    unidad = serializers.CharField()
    disponible = serializers.DecimalField(max_digits=14, decimal_places=2)
    maximo = serializers.IntegerField(help_text="Prendas que alcanzan con este material")


class LoteSimuladoSerializer(serializers.Serializer):
    numero = serializers.IntegerField()
    cantidad = serializers.IntegerField()
    acumulado = serializers.IntegerField(help_text="Prendas de los lotes 1..n juntos")
    cubierto = serializers.BooleanField(help_text="Alcanza el stock para los lotes 1..n juntos")
    faltantes = serializers.ListField(child=serializers.CharField(), help_text="Materiales que no alcanzan")


class SimulacionSalidaSerializer(serializers.Serializer):
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
    class Meta:
        model = LoteTalla
        fields = ["variante", "talla", "color", "cantidad"]


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

    class Meta:
        model = EtapaLote
        fields = [
            "id", "etapa", "etapa_nombre", "secuencia", "estado", "estado_nombre", "inicio_at", "fin_at",
            "en_curso_desde", "tiempo_neto_segundos", "responsable_nombre",
        ]

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
    estado = serializers.CharField()
    nombre = serializers.CharField()
    total = serializers.IntegerField(help_text="Lotes en esa columna, aunque solo se devuelvan `limite` tarjetas")
    lotes = TarjetaLoteSerializer(many=True)


class MonitorSerializer(serializers.Serializer):
    generado_at = serializers.DateTimeField()
    limite = serializers.IntegerField()
    terminadas_dias = serializers.IntegerField(help_text="La columna Terminada solo muestra los lotes de los últimos N días")
    alertas = serializers.DictField(
        child=serializers.IntegerField(), help_text="Lotes activos detenidos: `atencion` (desde 2 h) y `critica` (desde 8 h)"
    )
    columnas = ColumnaMonitorSerializer(many=True)
