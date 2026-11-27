"""
Una sola caja (HU 7.5): si existieran varias filas activas de saldo financiero con el mismo nombre, se suman en la más antigua y las
demás quedan con borrado lógico (no se pierde dinero). Después, una restricción única impide que vuelvan a duplicarse.
"""
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def merge_boxes(apps, schema_editor):
    SaldoFinanciero = apps.get_model("sales", "SaldoFinanciero")
    names = SaldoFinanciero.objects.filter(deleted_at__isnull=True).values_list("nombre", flat=True).distinct()
    for name in list(names):
        boxes = list(SaldoFinanciero.objects.filter(nombre=name, deleted_at__isnull=True).order_by("id"))
        if len(boxes) < 2:
            continue
        keep, extra = boxes[0], boxes[1:]
        keep.saldo_actual += sum(box.saldo_actual for box in extra)
        keep.save(update_fields=["saldo_actual"])
        SaldoFinanciero.objects.filter(pk__in=[box.pk for box in extra]).update(deleted_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0003_historial_precio_referencia"),
    ]

    operations = [
        migrations.RunPython(merge_boxes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="saldofinanciero",
            constraint=models.UniqueConstraint(fields=("nombre",), condition=Q(deleted_at__isnull=True), name="uq_ventas_saldo_nombre"),
        ),
    ]
