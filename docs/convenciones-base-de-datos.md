# Convenciones de base de datos — TexCore

Aplican a todas las tablas de negocio desde el Sprint 1 y se siguen en los módulos del Sprint 2.

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
- Cada módulo antepone su prefijo al nombre de la tabla:

| Prefijo | Módulo (app) | Ejemplos |
|---|---|---|
| `seguridad_` | `users` | `seguridad_rol`, `seguridad_permiso`, `seguridad_rol_permiso`, `seguridad_token_recuperacion` |
| `inventario_` | `inventory` | `inventario_producto`, `inventario_movimiento`, `inventario_orden`, `inventario_orden_linea` |
| `referencias_` | `references` | `referencias_referencia`, `referencias_variante`, `referencias_ficha`, `referencias_ficha_linea` |
| `produccion_` | `production` | `produccion_orden`, `produccion_lote`, `produccion_etapa_lote`, `produccion_asignacion_etapa` |
| `compras_` | `purchasing` | `compras_orden`, `compras_linea`, `compras_recepcion`, `compras_recepcion_linea` |

La lista completa, con sus campos, está en el [modelo de datos](modelo-de-datos.md).

### Códigos consecutivos

Los identificadores legibles (`OP-0001`, `LV-0001`, `OC-0001`, `RC-0001`, `REF-0001`, `OPE-0001`, `MAQ-0001`, `TEL-0001`...)
salen de la tabla `inventario_consecutivo`, que se bloquea al asignar el número dentro de la transacción. Si la operación falla,
el número no se gasta. Los lotes derivan del código de su orden (`OP-0001-L01`).

### Dinero y cantidades

- Importes y costos son `Decimal`, nunca `float`. Los costos unitarios y tarifas guardan hasta 4 decimales; los importes se
  redondean a centavos solo al final del cálculo.
- Un dato que se puede derivar no se guarda: el estado de un lote, si una máquina está ocupada o cuánto se ha recibido de una
  línea de compra se calculan al consultar. Lo que sí se guarda es una **foto** cuando el valor puede cambiar después y el
  histórico debe conservarse (por ejemplo el costo unitario de cada línea de una orden de salida).
- Las tablas de historial (`produccion_evento_etapa`, `produccion_asignacion_etapa`, `produccion_tarifa_mano_obra`) solo reciben filas
  nuevas; un cambio cierra o reemplaza el registro vigente y abre otro.

## 3. Migraciones

- El esquema se gestiona **solo** con migraciones de Django
  (`python manage.py makemigrations` / `migrate`), nunca editando tablas a
  mano en el panel de Supabase.
- Primero se aplica en **texcore-dev** y, cuando está probado en `pruebas`,
  en **texcore-prod**.
- El modelo de usuario personalizado (`users.CustomUser`) se definió antes de la primera migración, porque Django no permite
  cambiarlo después de migrar.
- Cada app mantiene su cadena de migraciones (`apps/<app>/migrations/`). Las migraciones de datos que cargan catálogos
  (roles, permisos, clasificación de productos) congelan sus valores dentro del archivo: no importan constantes del código que
  puedan cambiar. Ejemplos: `users/0003_roles_y_permisos`, `0007_permisos_referencias` y `0008_permisos_compras`.
- Al desplegar, Render ejecuta `python manage.py migrate --noinput` en cada arranque (ver [despliegue](despliegue-render.md)),
  así que una migración nueva se aplica sola al fusionar en `main`. Si dos entornos comparten la base, el código viejo debe
  tolerar el esquema nuevo.

## 4. Seguridad en Supabase

Solo el backend accede a la base de datos. Supabase publica automáticamente
el esquema `public` a través de su API REST (Data API) usando la *anon key*.
Para que nadie lea las tablas saltándose el backend:

- Desactivar la Data API (Project Settings → Data API) **o**
- Activar RLS sin políticas en cada tabla nueva
  (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY;`).
- En TexCore esto es automático: al final de cada `python manage.py migrate`,
  `apps/core/db_security.py` activa RLS en todas las tablas de `public` y les
  quita los privilegios a `anon`/`authenticated` (también para tablas futuras).
  No hay que agregar nada a las migraciones nuevas.
