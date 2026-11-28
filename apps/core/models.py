"""
Modelos base compartidos. Son abstractos: no crean tablas por sí mismos.

Convención de borrado lógico (ver docs/convenciones-base-de-datos.md):
toda tabla de negocio hereda de `BaseModel`. "Eliminar" llena `deleted_at`
en lugar de borrar la fila, y las consultas normales la ocultan.
"""
from django.db import IntegrityError, models
from django.utils import timezone


class ActiveQuerySet(models.QuerySet):
    def delete(self):
        """Borrado lógico masivo: marca las filas en vez de eliminarlas."""
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class ActiveManager(models.Manager.from_queryset(ActiveQuerySet)):
    """Manager por defecto: solo devuelve registros no eliminados."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ActiveManager()  # solo activos
    all_objects = models.Manager.from_queryset(ActiveQuerySet)()  # incluye eliminados

    class Meta:
        abstract = True

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)


# ------------------------------------------------------------------------------- libros de solo inserción (TE-188)
LEDGER_MESSAGE = "Los movimientos de un libro no se editan ni se borran: una corrección o reversión es un movimiento nuevo."


class LedgerIsAppendOnly(IntegrityError):
    """Se intentó editar o borrar un movimiento de un libro de solo inserción."""


class AppendOnlyQuerySet(ActiveQuerySet):
    """Consultas de un libro: se puede leer y crear, pero no actualizar ni borrar en bloque."""

    def update(self, **kwargs):
        raise LedgerIsAppendOnly(LEDGER_MESSAGE)

    def delete(self):
        raise LedgerIsAppendOnly(LEDGER_MESSAGE)

    def hard_delete(self):
        raise LedgerIsAppendOnly(LEDGER_MESSAGE)


class AppendOnlyManager(models.Manager.from_queryset(AppendOnlyQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AppendOnlyModel(BaseModel):
    """Movimiento de un libro (kardex de inventario, libro de producto terminado, libro de cartera): solo se inserta.

    Una fila guardada no se vuelve a guardar ni se borra (ni lógica ni físicamente); las anulaciones y devoluciones dejan un
    movimiento nuevo con el signo contrario. En PostgreSQL lo garantiza además un trigger en la base (migración
    `sales.0005`), que también frena `QuerySet.update()` y el SQL directo.
    """

    objects = AppendOnlyManager()
    all_objects = models.Manager.from_queryset(AppendOnlyQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise LedgerIsAppendOnly(LEDGER_MESSAGE)
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise LedgerIsAppendOnly(LEDGER_MESSAGE)

    def restore(self):
        raise LedgerIsAppendOnly(LEDGER_MESSAGE)

    def hard_delete(self, using=None, keep_parents=False):
        raise LedgerIsAppendOnly(LEDGER_MESSAGE)
