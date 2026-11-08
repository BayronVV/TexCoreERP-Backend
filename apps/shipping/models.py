"""
Guías de envío y relaciones de despacho (HU 7.2). Nombres de tabla en español y borrado lógico en todo.

- Guia: el paquete de una factura con una transportadora. Una factura tiene una sola guía vigente; si se cambia el número o la
  transportadora, la anterior pasa a ANULADA y se crea otra. `FacturaVenta.transportadora` y `numero_guia` son un espejo de la guía vigente.
- EventoGuia: historial de cambios de estado. Solo inserción: no se edita ni se borra.
- RelacionDespacho: la «relación de despacho» de la empresa: los paquetes que una transportadora recoge juntos en un día.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from . import catalog


class RelacionDespacho(BaseModel):
    """Paquetes que una transportadora recoge juntos. Al crearla, todas sus guías pasan a EN_TRANSITO."""
    codigo = models.CharField(max_length=20)
    transportadora = models.CharField(max_length=16, choices=catalog.CARRIERS)
    fecha = models.DateField()
    responsable = models.CharField(max_length=120, blank=True)
    observaciones = models.CharField(max_length=255, blank=True)
    token = models.UUIDField(help_text="Identificador único del formulario: evita crear la relación dos veces")
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "envios_relacion"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["codigo"], name="uq_envios_relacion_codigo"),
            models.UniqueConstraint(fields=["token"], name="uq_envios_relacion_token"),
        ]

    def __str__(self):
        return self.codigo


class Guia(BaseModel):
    """Guía de envío de una factura."""
    factura = models.ForeignKey("sales.FacturaVenta", on_delete=models.PROTECT, related_name="guias")
    transportadora = models.CharField(max_length=16, choices=catalog.CARRIERS)
    numero_guia = models.CharField(max_length=catalog.MAX_GUIDE_LENGTH)
    estado = models.CharField(max_length=14, choices=catalog.GUIDE_STATES, default=catalog.PENDING)
    vigente = models.BooleanField(default=True, help_text="La guía actual de la factura; las reemplazadas quedan anuladas")
    relacion = models.ForeignKey(RelacionDespacho, on_delete=models.PROTECT, null=True, blank=True, related_name="guias")
    novedad = models.CharField(max_length=255, blank=True, help_text="Qué pasó, mientras la guía está con novedad o devuelta")
    valor_flete = models.BigIntegerField(null=True, blank=True, help_text="Costo del flete en pesos enteros")
    flete_vendedor = models.BigIntegerField(default=0, help_text="Flete de una devolución, a cargo del vendedor (solo se registra y reporta)")
    despachada_en = models.DateTimeField(null=True, blank=True)
    entregada_en = models.DateTimeField(null=True, blank=True)
    devuelta_en = models.DateTimeField(null=True, blank=True)
    # --- Rastreo con Track123 ---
    rastreo_registrado = models.BooleanField(default=False, help_text="Ya se inscribió en Track123 (cada registro gasta cuota)")
    rastreo_estado = models.CharField(max_length=20, blank=True, help_text="transitStatus de Track123")
    rastreo_subestado = models.CharField(max_length=30, blank=True, help_text="transitSubStatus de Track123")
    rastreo_consultado_en = models.DateTimeField(null=True, blank=True)
    rastreo_proxima_consulta = models.DateTimeField(null=True, blank=True, help_text="Enfriamiento: no se consulta antes de esta hora")
    rastreo_respuesta = models.JSONField(null=True, blank=True, help_text="Última respuesta de Track123, para mostrarla sin volver a llamar")
    rastreo_sintetico = models.BooleanField(default=False, help_text="Datos de demostración que no vienen de la transportadora")

    class Meta:
        db_table = "envios_guia"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["factura"], condition=Q(vigente=True, deleted_at__isnull=True), name="uq_envios_guia_vigente_factura"),
            models.UniqueConstraint(
                fields=["transportadora", "numero_guia"], condition=Q(vigente=True, deleted_at__isnull=True), name="uq_envios_guia_numero",
            ),
            models.CheckConstraint(condition=Q(valor_flete__isnull=True) | Q(valor_flete__gte=0), name="ck_envios_guia_flete"),
            models.CheckConstraint(condition=Q(flete_vendedor__gte=0), name="ck_envios_guia_flete_vendedor"),
            models.CheckConstraint(condition=~Q(numero_guia=""), name="ck_envios_guia_numero"),
        ]
        indexes = [models.Index(fields=["estado"], name="ix_envios_guia_estado")]

    def __str__(self):
        return f"{self.numero_guia} ({self.estado})"


class EventoGuia(BaseModel):
    """Historial de una guía. Solo inserción."""
    guia = models.ForeignKey(Guia, on_delete=models.PROTECT, related_name="eventos")
    estado_antes = models.CharField(max_length=14, blank=True)
    estado_despues = models.CharField(max_length=14)
    nota = models.CharField(max_length=255, blank=True)
    origen = models.CharField(max_length=10, choices=catalog.ORIGINS, default=catalog.ORIGIN_MANUAL)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "envios_evento"
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("El historial de una guía no se edita.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.guia_id}: {self.estado_antes} → {self.estado_despues}"
