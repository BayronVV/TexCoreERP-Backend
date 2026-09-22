"""
Modelos base compartidos. Son abstractos: no crean tablas por sí mismos.

Convención de borrado lógico (ver docs/convenciones-base-de-datos.md):
toda tabla de negocio hereda de `BaseModel`. "Eliminar" llena `deleted_at`
en lugar de borrar la fila, y las consultas normales la ocultan.
"""
from django.db import models
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
