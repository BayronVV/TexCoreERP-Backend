"""Serializers de ventas: clientes, precios, facturas POS internas y los datos que la pantalla necesita."""
import re

from rest_framework import serializers

from apps.shipping import catalog as shipping_catalog

from . import catalog
from .models import Cliente, DetalleVenta, FacturaVenta


def _name(user):
    if user is None:
        return ""
    return (f"{user.first_name} {user.last_name}".strip()) or user.username


class ClienteSerializer(serializers.ModelSerializer):
    """Cliente al que se le vende. El código lo asigna el sistema; se desactiva, no se borra."""
    tipo_nombre = serializers.SerializerMethodField()
    descuento_maximo = serializers.SerializerMethodField(help_text="Descuento máximo (%) que el vendedor puede darle según su tipo")

    class Meta:
        model = Cliente
        fields = [
            "id", "codigo", "tipo_documento", "documento", "dv", "nombre", "tipo", "tipo_nombre", "descuento_maximo", "ciudad",
            "direccion", "telefono", "correo", "activo",
        ]
        read_only_fields = ["id", "codigo"]

    def get_tipo_nombre(self, obj) -> str:
        return catalog.CLIENT_TYPE_NAMES.get(obj.tipo, obj.tipo)

    def get_descuento_maximo(self, obj) -> int:
        return catalog.MAX_DISCOUNT.get(obj.tipo, 0)

    def validate_documento(self, value):
        value = value.strip()
        if not re.fullmatch(r"\d{5,15}", value):
            raise serializers.ValidationError("El documento debe tener entre 5 y 15 dígitos, sin puntos ni guiones.")
        return value

    def validate_dv(self, value):
        if value and not re.fullmatch(r"\d", value.strip()):
            raise serializers.ValidationError("El dígito de verificación es un solo número.")
        return value.strip()

    def validate_nombre(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("El nombre debe tener al menos 3 caracteres.")
        return value

    def validate_telefono(self, value):
        value = value.strip()
        if not re.fullmatch(r"[\d +()-]{7,20}", value):
            raise serializers.ValidationError("Escribe un teléfono válido (solo números, espacios, + - y paréntesis).")
        return value

    def validate(self, attrs):
        kind = attrs.get("tipo_documento", getattr(self.instance, "tipo_documento", None))
        number = attrs.get("documento", getattr(self.instance, "documento", None))
        dv = attrs.get("dv", getattr(self.instance, "dv", ""))
        if kind != catalog.DOC_NIT and dv:
            raise serializers.ValidationError({"dv": "El dígito de verificación solo aplica al NIT."})
        clash = Cliente.objects.filter(tipo_documento=kind, documento=number)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError({"documento": "Ya existe un cliente con ese documento."})
        return attrs


class PrecioReferenciaSerializer(serializers.Serializer):
    """Costo de fábrica y precios de una referencia (vacíos si todavía no se registran)."""
    referencia = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    estado = serializers.CharField()
    costo_fabrica = serializers.IntegerField(allow_null=True)
    precio_detal = serializers.IntegerField(allow_null=True)
    precio_mayorista = serializers.IntegerField(allow_null=True)


class PrecioInputSerializer(serializers.Serializer):
    """Precios de una referencia en pesos enteros, antes de IVA: costo de fábrica ≤ mayorista ≤ detal."""
    costo_fabrica = serializers.IntegerField(min_value=1, max_value=100_000_000)
    precio_detal = serializers.IntegerField(min_value=1, max_value=100_000_000)
    precio_mayorista = serializers.IntegerField(min_value=1, max_value=100_000_000)

    def validate(self, attrs):
        if attrs["precio_mayorista"] < attrs["costo_fabrica"]:
            raise serializers.ValidationError({"precio_mayorista": "El precio mayorista no puede ser menor al costo de fábrica."})
        if attrs["precio_detal"] < attrs["precio_mayorista"]:
            raise serializers.ValidationError({"precio_detal": "El precio de detal no puede ser menor al mayorista."})
        return attrs


class DetalleVentaSerializer(serializers.ModelSerializer):
    """Una línea de la factura, con el precio, el descuento y el IVA del momento de la venta."""

    class Meta:
        model = DetalleVenta
        fields = [
            "id", "variante", "referencia_codigo", "referencia_nombre", "talla", "color", "cantidad", "precio_unitario", "descuento_pct",
            "subtotal", "descuento", "base", "iva", "total",
        ]


class FacturaSerializer(serializers.ModelSerializer):
    """Factura POS interna (no es factura electrónica). Inalterable: solo se anula."""
    vendedor_nombre = serializers.SerializerMethodField()
    anulada_por_nombre = serializers.SerializerMethodField()
    cobrado_por_nombre = serializers.SerializerMethodField()
    cliente_tipo_nombre = serializers.SerializerMethodField()
    transportadora_nombre = serializers.SerializerMethodField()
    estado_cobro_nombre = serializers.SerializerMethodField()
    guia = serializers.SerializerMethodField(help_text="Guía vigente de la factura (HU 7.2): estado, color de semáforo y rastreo")
    unidades = serializers.SerializerMethodField()
    aviso = serializers.SerializerMethodField(help_text="Leyenda que acompaña a la factura")
    lineas = DetalleVentaSerializer(many=True, read_only=True)

    class Meta:
        model = FacturaVenta
        fields = [
            "id", "numero", "estado", "fecha", "cliente", "cliente_nombre", "cliente_documento", "cliente_tipo", "cliente_tipo_nombre",
            "cliente_ciudad", "cliente_direccion", "cliente_telefono", "vendedor_nombre", "modalidad_pago", "estado_cobro", "estado_cobro_nombre",
            "transportadora", "transportadora_nombre", "numero_guia", "observaciones", "subtotal", "descuento_total", "base_gravable",
            "iva_tarifa", "iva_total", "total", "valor_a_recaudar", "unidades", "motivo_anulacion", "anulada_por_nombre", "anulada_en",
            "fecha_cobro", "cobrado_por_nombre", "motivo_devolucion", "guia", "aviso", "lineas", "created_at",
        ]

    def get_vendedor_nombre(self, obj) -> str:
        return _name(obj.vendedor)

    def get_anulada_por_nombre(self, obj) -> str:
        return _name(obj.anulada_por) if obj.anulada_por else ""

    def get_cobrado_por_nombre(self, obj) -> str:
        return _name(obj.cobrado_por) if obj.cobrado_por else ""

    def get_cliente_tipo_nombre(self, obj) -> str:
        return catalog.CLIENT_TYPE_NAMES.get(obj.cliente_tipo, obj.cliente_tipo)

    def get_estado_cobro_nombre(self, obj) -> str:
        return catalog.COLLECT_STATE_NAMES.get(obj.estado_cobro, obj.estado_cobro)

    def get_guia(self, obj):
        guides = getattr(obj, "guia_vigente", None)
        if guides is None:  # fuera de `invoice_queryset` (sin precarga)
            guides = list(obj.guias.filter(vigente=True))
        if not guides:
            return None
        guide = guides[0]
        return {
            "id": guide.id, "estado": guide.estado, "estado_nombre": shipping_catalog.STATE_NAMES.get(guide.estado, guide.estado),
            "color": shipping_catalog.STATE_COLORS.get(guide.estado, "gris"), "rastreo_estado": guide.rastreo_estado,
            "consultada_en": guide.rastreo_consultado_en, "novedad": guide.novedad,
        }

    def get_transportadora_nombre(self, obj) -> str:
        return catalog.CARRIER_NAMES.get(obj.transportadora, "")

    def get_unidades(self, obj) -> int:
        return sum(line.cantidad for line in obj.lineas.all())

    def get_aviso(self, obj) -> str:
        return catalog.INVOICE_NOTICE


class LineaVentaInputSerializer(serializers.Serializer):
    """Una celda de la matriz: cuántas prendas de esa talla y color se venden y con qué descuento."""
    variante = serializers.IntegerField(help_text="Id de la variante (talla y color)")
    cantidad = serializers.IntegerField(min_value=1)
    descuento_pct = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0, help_text="Descuento que decide el vendedor")


class FacturaInputSerializer(serializers.Serializer):
    """Datos de la venta: cliente, líneas, transportadora y guía (opcionales) y el token único del formulario."""
    cliente = serializers.IntegerField()
    lineas = LineaVentaInputSerializer(many=True)
    transportadora = serializers.ChoiceField(choices=catalog.CARRIERS, required=False, allow_blank=True, default="")
    numero_guia = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    token = serializers.UUIDField(help_text="Identificador único del formulario: evita facturar dos veces con un doble clic")


class AnularInputSerializer(serializers.Serializer):
    motivo = serializers.CharField(max_length=255)


class ConciliarInputSerializer(serializers.Serializer):
    """Acción rápida para cambiar el estado de cartera: PAGADO o DEVOLUCION (HU 7.3)."""
    estado_cobro = serializers.ChoiceField(choices=[catalog.COLLECT_PAID, catalog.COLLECT_RETURNED])
    motivo = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    observaciones = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CarteraResumenSerializer(serializers.Serializer):
    """Resumen consolidado de cartera y saldo financiero de la empresa."""
    saldo_financiero = serializers.IntegerField()
    total_por_cobrar = serializers.IntegerField()
    conteo_por_cobrar = serializers.IntegerField()
    total_recaudado = serializers.IntegerField()
    conteo_pagadas = serializers.IntegerField()
    total_devoluciones = serializers.IntegerField()
    conteo_devoluciones = serializers.IntegerField()


class OpcionSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()


class TipoClienteSerializer(OpcionSerializer):
    lista_precios = serializers.CharField(help_text="`detal` o `mayorista`")
    descuento_maximo = serializers.IntegerField(help_text="Descuento máximo (%) que el vendedor puede dar")


class MetadatosVentaSerializer(serializers.Serializer):
    """Opciones y reglas de la venta que la pantalla necesita conocer."""
    tipos_cliente = TipoClienteSerializer(many=True)
    tipos_documento = OpcionSerializer(many=True)
    transportadoras = OpcionSerializer(many=True)
    estados_cobro = OpcionSerializer(many=True)
    iva_tarifa = serializers.IntegerField()
    aviso = serializers.CharField()
    motivo_anulacion_minimo = serializers.IntegerField()
