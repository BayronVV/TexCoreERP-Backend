"""
Convierte las guías que ya estaban escritas en las facturas (HU 7.1 / 7.3: `transportadora` y `numero_guia` en texto) en registros de guía.

Cada factura con número de guía recibe su guía vigente con un evento «Guía importada de la factura». El estado se deduce de lo que la
factura ya sabe: pagada → entregada; devuelta → devuelta; anulada → anulada; el resto → por despachar. Es idempotente (no repite una
factura que ya tiene guía) y no pisa un número que otra guía vigente ya usa. Los datos quedan congelados aquí a propósito.
"""
from django.db import migrations


def import_guides(apps, schema_editor):
    Invoice = apps.get_model("sales", "FacturaVenta")
    Guide = apps.get_model("shipping", "Guia")
    Event = apps.get_model("shipping", "EventoGuia")
    for invoice in Invoice.objects.exclude(numero_guia="").order_by("id"):
        if Guide.objects.filter(factura_id=invoice.id).exists():
            continue
        carrier = invoice.transportadora or "OTRA"
        if Guide.objects.filter(transportadora=carrier, numero_guia=invoice.numero_guia, vigente=True).exists():
            continue
        state, current = "POR_DESPACHAR", True
        if invoice.estado == "ANULADA":
            state, current = "ANULADA", False
        elif invoice.estado_cobro == "PAGADO":
            state = "ENTREGADA"
        elif invoice.estado_cobro == "DEVOLUCION":
            state = "DEVUELTA"
        guide = Guide.objects.create(
            factura_id=invoice.id, transportadora=carrier, numero_guia=invoice.numero_guia, estado=state, vigente=current,
            novedad=invoice.motivo_devolucion if state == "DEVUELTA" else "", rastreo_sintetico=False,
        )
        Event.objects.create(guia_id=guide.id, estado_antes="", estado_despues=state, nota="Guía importada de la factura", origen="SISTEMA")


class Migration(migrations.Migration):

    dependencies = [
        ("shipping", "0001_envios_guias_relaciones"),
        ("sales", "0002_cartera_conciliacion"),
    ]

    operations = [migrations.RunPython(import_guides, migrations.RunPython.noop)]
