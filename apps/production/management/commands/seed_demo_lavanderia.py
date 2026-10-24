from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.inventory import catalog as inv_catalog
from apps.inventory.models import Proveedor
from apps.production import catalog
from apps.production.models import Lote, RecetaLavado, RemisionLavanderia, RemisionLote
from apps.users.models import CustomUser


class Command(BaseCommand):
    help = "Carga proveedores de lavandería, recetas de lavado y datos iniciales de procesos externos (TE-57)."

    def handle(self, *args, **options):
        self.stdout.write("--- Semilla Procesos Externos / Lavandería (TE-57) ---")

        # 1. Proveedores de lavandería
        proveedores_data = [
            {
                "nit": "900543210",
                "nit_dv": "4",
                "razon_social": "Lavandería Industrial El Cóndor S.A.S.",
                "categoria": inv_catalog.CAT_LAUNDRY,
                "contacto": "Ing. Gustavo Mejía (Director de Planta)",
                "telefono": "3114567890",
                "correo": "gmejia@elcondorlavados.com",
                "ciudad": "Itagüí, Antioquia",
                "direccion": "Cra. 52 # 28-40 (Zona Industrial)",
            },
            {
                "nit": "890987654",
                "nit_dv": "1",
                "razon_social": "Lavados Especiales Sol Denim Ltda.",
                "categoria": inv_catalog.CAT_LAUNDRY,
                "contacto": "Claudia Restrepo (Coordinadora de Cuentas)",
                "telefono": "3158901234",
                "correo": "crestrepo@soldenim.com",
                "ciudad": "Medellín, Antioquia",
                "direccion": "Calle 14 # 43B-12 (El Poblado Industrial)",
            },
            {
                "nit": "901123456",
                "nit_dv": "8",
                "razon_social": "Procesos Textiles y Lavandería La 70 S.A.S.",
                "categoria": inv_catalog.CAT_LAUNDRY,
                "contacto": "Darío Morales (Jefe de Producción Externa)",
                "telefono": "3002345678",
                "correo": "dmorales@la70lavanderia.com",
                "ciudad": "Medellín, Antioquia",
                "direccion": "Circular 4 # 70-19 (Laureles)",
            },
        ]

        proveedores_creados = 0
        for pdata in proveedores_data:
            prov, created = Proveedor.objects.get_or_create(
                nit=pdata["nit"],
                defaults=pdata,
            )
            if not created and prov.categoria != inv_catalog.CAT_LAUNDRY:
                prov.categoria = inv_catalog.CAT_LAUNDRY
                prov.save(update_fields=["categoria"])
            if created:
                proveedores_creados += 1

        self.stdout.write(f"Proveedores de lavandería verificados ({proveedores_creados} nuevos).")

        # 2. Recetas de lavado
        recetas_data = [
            {
                "codigo": "REC-SW-01",
                "nombre": "Stone Wash Medio + Bigotes 3D",
                "categoria": "Efectos Manuales & Lavado Enzimático",
                "descripcion": "Lavado con piedra pómez ecológica, bajada a tono medio uniforme, lijado manual de bigotes en frente y rozaduras en bota.",
                "temperatura_proceso": "60 °C",
                "duracion_horas": 48,
                "tarifa_sugerida": Decimal("3500.00"),
            },
            {
                "codigo": "REC-BK-04",
                "nombre": "Tintura Reactiva Negro Mate + Siliconado",
                "categoria": "Tintura & Acabado Químico",
                "descripcion": "Inmersión en colorante negro reactivo con fijador catiónico, neutralizado y suavizado térmico con elastómeros de silicona.",
                "temperatura_proceso": "75 °C",
                "duracion_horas": 36,
                "tarifa_sugerida": Decimal("4200.00"),
            },
            {
                "codigo": "REC-BL-02",
                "nombre": "Bleach Intenso + Desgaste Láser Vintage",
                "categoria": "Decolorado Químico & Láser",
                "descripcion": "Decolorado con hipoclorito neutralizado con bisulfito, diseño láser digital 3D de bigotes, desgastes y tacto ultrasuave.",
                "temperatura_proceso": "65 °C",
                "duracion_horas": 60,
                "tarifa_sugerida": Decimal("4500.00"),
            },
            {
                "codigo": "REC-DS-03",
                "nombre": "Eco-Wash Suavizado Enzimático Simple",
                "categoria": "Lavado Ecológico / Básico",
                "descripcion": "Proceso con microenzimas biodegradables para reducción de rigidez sin pérdida de índigo y neutralizado en frío.",
                "temperatura_proceso": "45 °C",
                "duracion_horas": 24,
                "tarifa_sugerida": Decimal("2800.00"),
            },
        ]

        recetas_creadas = 0
        for rdata in recetas_data:
            _, created = RecetaLavado.objects.get_or_create(
                codigo=rdata["codigo"],
                defaults=rdata,
            )
            if created:
                recetas_creadas += 1

        self.stdout.write(f"Recetas de lavado verificadas ({recetas_creadas} nuevas).")

        # 3. Lotes ensamblados disponibles en planta
        lotes_actualizados = Lote.objects.filter(estado_inventario=catalog.LOT_INV_INTERNAL).count()
        self.stdout.write(f"Lotes en planta interna: {lotes_actualizados}.")

        self.stdout.write(self.style.SUCCESS("Semilla de lavandería completada con éxito."))
