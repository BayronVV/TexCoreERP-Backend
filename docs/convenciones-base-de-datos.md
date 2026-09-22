# Convenciones de base de datos — TexCore

Aplican a todas las tablas de negocio desde el Sprint 1.

## 1. Borrado lógico (soft delete)

En TexCore **nada de negocio se borra físicamente**. La trazabilidad
(lotes, órdenes, movimientos de inventario, auditoría de cuadres) exige que
lo "eliminado" quede oculto pero siga existiendo.

| Columna      | Tipo                     | Regla                                   |
|--------------|--------------------------|-----------------------------------------|
| `created_at` | `timestamptz NOT NULL`   | Se llena al crear.                      |
| `updated_at` | `timestamptz NOT NULL`   | Se actualiza en cada guardado.          |
| `deleted_at` | `timestamptz NULL`, indexada | `NULL` = activo. Con fecha = eliminado. |

Se prefiere `deleted_at` sobre un booleano `is_deleted` porque además dice
**cuándo** se eliminó, y `deleted_at IS NULL` sirve igual de filtro.

### Cómo usarlo en Django

Todo modelo de negocio hereda de `apps.core.models.BaseModel`:

```python
from apps.core.models import BaseModel

class Proveedor(BaseModel):
    nit = models.CharField(max_length=20)
    razon_social = models.CharField(max_length=200)
```

| Operación                        | Efecto                                      |
|----------------------------------|---------------------------------------------|
| `Proveedor.objects.all()`        | Solo activos (`deleted_at IS NULL`).        |
| `Proveedor.all_objects.all()`    | Todos, incluidos los eliminados.            |
| `proveedor.delete()`             | Borrado lógico: llena `deleted_at`.         |
| `Proveedor.objects.filter(...).delete()` | Borrado lógico masivo.              |
| `proveedor.restore()`            | Reactiva el registro.                       |
| `proveedor.hard_delete()`        | Borrado físico. Solo para datos de prueba.  |

### Reglas complementarias

- **Unicidad**: una restricción única (p. ej. NIT de proveedor) debe ignorar
  los eliminados, con un índice único parcial:
  `models.UniqueConstraint(fields=["nit"], condition=Q(deleted_at__isnull=True), name="uq_proveedor_nit_activo")`.
- **Claves foráneas**: usar `on_delete=models.PROTECT`; como no hay borrado
  físico, `CASCADE` no debe dispararse nunca.
- **Consultas SQL a mano** (reportes): agregar siempre `WHERE deleted_at IS NULL`.

## 2. Nombres

- Tablas y columnas en `snake_case`, en español, siguiendo el modelo
  entidad-relación (`orden_produccion`, `materia_prima`, ...).
- Claves primarias `id` (bigint autoincremental); foráneas `<entidad>_id`.

## 3. Migraciones

- El esquema se gestiona **solo** con migraciones de Django
  (`python manage.py makemigrations` / `migrate`), nunca editando tablas a
  mano en el panel de Supabase.
- Primero se aplica en **texcore-dev** y, cuando está probado en `pruebas`,
  en **texcore-prod**.
- La primera migración se hará en Sprint 1, **después** de definir el modelo
  de usuario personalizado (Django no permite cambiarlo después de migrar).

## 4. Seguridad en Supabase

Solo el backend accede a la base de datos. Supabase publica automáticamente
el esquema `public` a través de su API REST (Data API) usando la *anon key*.
Para que nadie lea las tablas saltándose el backend:

- Desactivar la Data API (Project Settings → Data API) **o**
- Activar RLS sin políticas en cada tabla nueva
  (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY;`).
