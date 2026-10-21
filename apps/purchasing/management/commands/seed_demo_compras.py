"""Órdenes de compra de demostración: una en borrador, una aprobada y una con recepción parcial.

    python manage.py seed_demo_compras     # requiere antes seed_demo_inventario (proveedores y productos)

Pasa por las mismas reglas que usa la aplicación (`services.create_order`, `approve_order` y `receive_goods`), así que los
códigos son consecutivos y la recepción suma al stock, al costo promedio y al kardex. Quien crea la orden es un usuario con
rol Producción, quien la aprueba un Gerente (o Administrador) y quien recibe un Almacenista; si falta alguno de esos roles
se usa un usuario cualquiera para crear y aprobar, pero la recepción exige a alguien distinto del que creó la orden.
Es idempotente: una orden ya sembrada no se repite (se reconoce por sus notas). Solo con DJANGO_DEBUG=true.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from apps.inventory import catalog as inventory_catalog
from apps.inventory.management.commands.seed_demo_inventario import demo_cost
from apps.inventory.models import Producto, Proveedor

from ... import services
from ...models import OrdenCompra

ORDERS = [
    {
        "key": "OC-DEMO-BORRADOR", "categorias": [inventory_catalog.CAT_FABRIC], "estado": "BORRADOR",
        "condiciones": "Pago a 30 días", "cantidad": "120",
    },
    {
        "key": "OC-DEMO-APROBADA", "categorias": [inventory_catalog.CAT_THREAD, inventory_catalog.CAT_BUTTON], "estado": "APROBADA",
        "condiciones": "Contra entrega", "cantidad": "60",
    },
    {
        "key": "OC-DEMO-PARCIAL", "categorias": [inventory_catalog.CAT_ZIPPER, inventory_catalog.CAT_BUTTON], "estado": "RECIBIDA_PARCIAL",
        "condiciones": "Pago a 15 días", "cantidad": "200", "recibir": "0.5",
    },
]


class Command(BaseCommand):
    """Comando de gestión: siembra órdenes de compra de demostración (solo con `DJANGO_DEBUG=true`)."""
    help = "Crea órdenes de compra de demostración: borrador, aprobada y con recepción parcial (solo con DJANGO_DEBUG=true)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Este comando solo se permite con DJANGO_DEBUG=true.")
        users = get_user_model().objects.filter(is_active=True)
        creator = users.filter(role_id="PRODUCCION").first() or users.first()
        approver = users.filter(role_id__in=["GERENTE", "ADMIN"]).first() or creator
        receiver = users.filter(role_id="ALMACENISTA").exclude(pk=creator.pk if creator else None).first()
        if creator is None:
            raise CommandError("No hay usuarios: crea uno primero (por ejemplo con seed_admin).")
        created = sum(self._order(spec, creator, approver, receiver) for spec in ORDERS)
        self.stdout.write(self.style.SUCCESS(f"Órdenes de compra nuevas: {created}."))

    def _order(self, spec, creator, approver, receiver):
        marker = f"Orden de compra de demostración {spec['key']}"
        if OrdenCompra.all_objects.filter(notas=marker).exists():
            return 0
        products = []
        for category in spec["categorias"]:
            products += list(Producto.objects.filter(categoria=category).order_by("id")[:2])
        supplier = Proveedor.objects.filter(categoria__in=spec["categorias"]).order_by("id").first() or Proveedor.objects.order_by("id").first()
        if not products or supplier is None:
            self.stdout.write(f"Omitida {spec['key']}: faltan proveedores o productos (corre seed_demo_inventario).")
            return 0
        lines = []
        for product in products:
            price = demo_cost(product.categoria, product.unidad, 0)
            line = {"producto": product.id, "cantidad": spec["cantidad"]}
            if price is not None:
                line["precio_pactado"] = str(price)
            lines.append(line)
        try:
            order = services.create_order(
                user=creator, data={"proveedor": supplier.id, "lineas": lines, "condiciones_pago": spec["condiciones"], "notas": marker},
            )
            if spec["estado"] != "BORRADOR":
                services.approve_order(user=approver, order_id=order.id)
            if spec.get("recibir"):
                self._receive(order, spec, receiver)
        except ValidationError as error:
            self.stdout.write(f"Omitida {spec['key']}: {error.detail}")
            return 0
        return 1

    def _receive(self, order, spec, receiver):
        if receiver is None:
            self.stdout.write(f"{order.codigo} queda aprobada: no hay un almacenista distinto de quien la creó para recibirla.")
            return
        rows = []
        for line in order.lineas.select_related("producto"):
            quantity = (line.cantidad_pedida * Decimal(spec["recibir"])).quantize(Decimal(1))
            rows.append({
                "linea": line.id, "cantidad": str(quantity), "lote": f"DEMO-{order.codigo}",
                "costo_unitario": None if line.precio_pactado is None else str(line.precio_pactado),
            })
        services.receive_goods(user=receiver, data={"orden": order.id, "documento": f"REM-{order.codigo}", "lineas": rows})
