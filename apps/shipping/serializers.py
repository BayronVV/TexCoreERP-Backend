"""Serializers de envíos: guías con su semáforo y su rastreo, relaciones de despacho, facturas sin guía y los datos que la pantalla necesita."""
from django.conf import settings
from rest_framework import serializers

from apps.sales.serializers import _name

from . import catalog, services, tracking
from .models import EventoGuia, Guia, RelacionDespacho


class EventoGuiaSerializer(serializers.ModelSerializer):
    estado_antes_nombre = serializers.SerializerMethodField()
    estado_despues_nombre = serializers.SerializerMethodField()
    usuario_nombre = serializers.SerializerMethodField()

    class Meta:
        model = EventoGuia
        fields = ["id", "estado_antes", "estado_antes_nombre", "estado_despues", "estado_despues_nombre", "nota", "origen", "usuario_nombre", "created_at"]
        read_only_fields = fields

    def get_estado_antes_nombre(self, obj) -> str:
        return catalog.STATE_NAMES.get(obj.estado_antes, "")

    def get_estado_despues_nombre(self, obj) -> str:
        return catalog.STATE_NAMES.get(obj.estado_despues, obj.estado_despues)

    def get_usuario_nombre(self, obj) -> str:
        return _name(obj.usuario) if obj.usuario else ("Track123" if obj.origen == catalog.ORIGIN_TRACK123 else "Sistema")


class GuiaSerializer(serializers.ModelSerializer):
    """Guía de envío con su estado, su color de semáforo y el resumen del rastreo."""
    factura_numero = serializers.CharField(source="factura.numero", read_only=True)
    factura_total = serializers.IntegerField(source="factura.total", read_only=True)
    estado_cobro = serializers.CharField(source="factura.estado_cobro", read_only=True)
    cliente_nombre = serializers.CharField(source="factura.cliente_nombre", read_only=True)
    cliente_ciudad = serializers.CharField(source="factura.cliente_ciudad", read_only=True)
    vendedor_nombre = serializers.SerializerMethodField()
    transportadora_nombre = serializers.SerializerMethodField()
    estado_nombre = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    relacion_codigo = serializers.SerializerMethodField()
    acciones = serializers.SerializerMethodField(help_text="Estados a los que se puede pasar a mano desde el actual")
    rastreo = serializers.SerializerMethodField()
    aviso_formato = serializers.SerializerMethodField()

    class Meta:
        model = Guia
        fields = [
            "id", "factura", "factura_numero", "factura_total", "estado_cobro", "cliente_nombre", "cliente_ciudad", "vendedor_nombre",
            "transportadora", "transportadora_nombre", "numero_guia", "estado", "estado_nombre", "color", "vigente", "relacion", "relacion_codigo",
            "novedad", "valor_flete", "flete_vendedor", "despachada_en", "entregada_en", "devuelta_en", "acciones", "rastreo", "aviso_formato",
            "created_at",
        ]
        read_only_fields = fields

    def get_vendedor_nombre(self, obj) -> str:
        return _name(obj.factura.vendedor)

    def get_transportadora_nombre(self, obj) -> str:
        return catalog.CARRIER_NAMES.get(obj.transportadora, obj.transportadora)

    def get_estado_nombre(self, obj) -> str:
        return catalog.STATE_NAMES.get(obj.estado, obj.estado)

    def get_color(self, obj) -> str:
        return catalog.STATE_COLORS.get(obj.estado, "gris")

    def get_relacion_codigo(self, obj) -> str:
        return obj.relacion.codigo if obj.relacion_id else ""

    def get_acciones(self, obj) -> list:
        if not obj.vigente:
            return []
        return sorted(catalog.TRANSITIONS.get(obj.estado, set()))

    def get_aviso_formato(self, obj) -> str:
        return services.format_warning(obj.transportadora, obj.numero_guia)

    def get_rastreo(self, obj) -> dict:
        response = obj.rastreo_respuesta or {}
        return {
            "soportado": tracking.supports_tracking(obj),
            "registrado": obj.rastreo_registrado,
            "estado": obj.rastreo_estado,
            "subestado": obj.rastreo_subestado,
            "descripcion": tracking.describe(response) if response else "",
            "consultado_en": obj.rastreo_consultado_en,
            "proxima_consulta": obj.rastreo_proxima_consulta,
            "sintetico": obj.rastreo_sintetico,
        }


class GuiaDetailSerializer(GuiaSerializer):
    """Detalle: añade el historial propio y la línea de tiempo que reportó la transportadora (guardada, sin volver a llamar a la API)."""
    eventos = EventoGuiaSerializer(many=True, read_only=True)
    rastreo_eventos = serializers.SerializerMethodField()

    class Meta(GuiaSerializer.Meta):
        fields = GuiaSerializer.Meta.fields + ["eventos", "rastreo_eventos"]
        read_only_fields = fields

    def get_rastreo_eventos(self, obj) -> list:
        details = ((obj.rastreo_respuesta or {}).get("localLogisticsInfo") or {}).get("trackingDetails") or []
        return [
            {"fecha": d.get("eventTime", ""), "lugar": d.get("address", ""), "detalle": d.get("eventDetail", ""),
             "subestado": d.get("transitSubStatus", "") or "", "subestado_nombre": catalog.TRACK_SUB_NAMES.get(d.get("transitSubStatus", ""), "")}
            for d in details
        ]


class FacturaSinGuiaSerializer(serializers.Serializer):
    """Factura emitida a la que todavía le falta anotar la guía."""
    id = serializers.IntegerField()
    numero = serializers.CharField()
    fecha = serializers.DateField()
    created_at = serializers.DateTimeField()
    cliente_nombre = serializers.CharField()
    cliente_ciudad = serializers.CharField()
    total = serializers.IntegerField()
    vendedor_nombre = serializers.SerializerMethodField()
    horas_sin_guia = serializers.SerializerMethodField()
    urgencia = serializers.SerializerMethodField(help_text="normal, atencion (desde 4 h) o vencida (desde 24 h)")

    def get_vendedor_nombre(self, obj) -> str:
        return _name(obj.vendedor)

    def get_horas_sin_guia(self, obj) -> int:
        return services.hours_without_guide(obj)

    def get_urgencia(self, obj) -> str:
        return services.urgency(services.hours_without_guide(obj))


class RelacionSerializer(serializers.ModelSerializer):
    transportadora_nombre = serializers.SerializerMethodField()
    creada_por_nombre = serializers.SerializerMethodField()
    total_guias = serializers.SerializerMethodField()

    class Meta:
        model = RelacionDespacho
        fields = ["id", "codigo", "transportadora", "transportadora_nombre", "fecha", "responsable", "observaciones", "creada_por_nombre", "total_guias", "created_at"]
        read_only_fields = fields

    def get_transportadora_nombre(self, obj) -> str:
        return catalog.CARRIER_NAMES.get(obj.transportadora, obj.transportadora)

    def get_creada_por_nombre(self, obj) -> str:
        return _name(obj.creada_por)

    def get_total_guias(self, obj) -> int:
        return len(obj.guias.all())


class RelacionDetailSerializer(RelacionSerializer):
    guias = GuiaSerializer(many=True, read_only=True)

    class Meta(RelacionSerializer.Meta):
        fields = RelacionSerializer.Meta.fields + ["guias"]
        read_only_fields = fields


class AsignarGuiaInputSerializer(serializers.Serializer):
    transportadora = serializers.ChoiceField(choices=catalog.CARRIERS)
    numero_guia = serializers.CharField(max_length=60)


class EstadoGuiaInputSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=catalog.GUIDE_STATES)
    nota = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class FleteInputSerializer(serializers.Serializer):
    valor_flete = serializers.IntegerField(min_value=0)


class RastrearInputSerializer(serializers.Serializer):
    forzar = serializers.BooleanField(required=False, default=False)


class RelacionInputSerializer(serializers.Serializer):
    transportadora = serializers.ChoiceField(choices=catalog.CARRIERS)
    guias = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    token = serializers.UUIDField()
    fecha = serializers.DateField(required=False)
    responsable = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class OpcionEnvioSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    color = serializers.CharField(required=False)
    rastreable = serializers.BooleanField(required=False)


class MetadatosEnvioSerializer(serializers.Serializer):
    estados = OpcionEnvioSerializer(many=True)
    transportadoras = OpcionEnvioSerializer(many=True)
    transiciones = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
    estados_con_nota = serializers.ListField(child=serializers.CharField())
    nota_minima = serializers.IntegerField()
    horas_atencion = serializers.IntegerField()
    horas_vencida = serializers.IntegerField()
    rastreo_habilitado = serializers.BooleanField()


def metadata():
    return {
        "estados": [{"codigo": code, "nombre": name, "color": catalog.STATE_COLORS[code]} for code, name in catalog.GUIDE_STATES],
        "transportadoras": [{"codigo": code, "nombre": name, "rastreable": code in catalog.TRACKING_COURIERS} for code, name in catalog.CARRIERS],
        "transiciones": {state: sorted(targets) for state, targets in catalog.TRANSITIONS.items()},
        "estados_con_nota": sorted(catalog.NOTE_REQUIRED),
        "nota_minima": catalog.MIN_NOTE,
        "horas_atencion": catalog.ATTENTION_HOURS,
        "horas_vencida": catalog.OVERDUE_HOURS,
        "rastreo_habilitado": bool(settings.TRACK123_ENABLED and settings.TRACK123_API_KEY),
    }
