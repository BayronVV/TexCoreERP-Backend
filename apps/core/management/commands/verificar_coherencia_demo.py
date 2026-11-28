"""Comprueba que los datos de demostración cuenten una sola historia coherente (TE-183).

    python manage.py verificar_coherencia_demo

Solo lee. Revisa los libros de inventario, producto terminado y cartera, que Inventario muestre lo mismo que Producto Terminado por referencia,
los registros huérfanos y que la trazabilidad de la HU 7.6 llegue completa (ver `apps/core/demo_integrity.py`). Termina con error (código de salida distinto de cero) si algo no cuadra, para
poder usarlo en la integración continua y en la sustentación.
"""
from django.core.management.base import BaseCommand, CommandError

from ... import demo_integrity


class Command(BaseCommand):
    """Comando de gestión: comprobación de coherencia de los datos de demostración (solo lectura)."""
    help = "Comprueba los libros, los huérfanos y la trazabilidad de los datos de demostración; falla si algo no cuadra."

    def handle(self, *args, **options):
        failed = report(self.stdout, self.style)
        if failed:
            raise CommandError(f"La comprobación de coherencia encontró {failed} problema(s).")
        self.stdout.write(self.style.SUCCESS("Los datos de demostración son coherentes."))


def report(stdout, style):
    """Imprime cada comprobación con su resultado y devuelve cuántos problemas hubo."""
    failed = 0
    for name, problems in demo_integrity.run_checks():
        if problems:
            stdout.write(style.ERROR(f"  ✗ {name}"))
            for problem in problems[:20]:
                stdout.write(f"      {problem}")
            if len(problems) > 20:
                stdout.write(f"      … y {len(problems) - 20} más.")
            failed += len(problems)
        else:
            stdout.write(f"  ✓ {name}")
    return failed
