# Calidad continua y cobertura de pruebas

Documento técnico de calidad continua (TE-180). Reúne los tiempos medidos antes y después de optimizar la suite,
la cobertura real medida con `coverage`, el desglose por historia de usuario (H06), los flujos de integración continua
y las instrucciones para reproducir las pruebas críticas en PostgreSQL durante la sustentación.

## 1. Tiempos de ejecución (antes y después)

La auditoría del 08/11/2026 detectó que la suite del backend tardaba alrededor de **28 minutos** para 922 pruebas porque
Django utilizaba `PBKDF2PasswordHasher` (~0,45 s por cada usuario creado con `make_user`).

En [config/settings.py](https://github.com/BayronVV/TexCoreERP-Backend/blob/main/config/settings.py), cuando `RUNNING_TESTS`
es verdadero (`manage.py test`), se habilita `MD5PasswordHasher` **únicamente en memoria de pruebas** —en desarrollo
y producción se conserva PBKDF2 con validadores completos— y se centralizaron las utilidades compartidas en
`apps/core/testing.py`. **No se eliminó ninguna prueba**; por el contrario, se añadieron pruebas de concurrencia,
compatibilidad con PostgreSQL, validación de transiciones y cliente/rutas del frontend.

| Medición | Configuración | Pruebas | Tiempo medido |
|---|---|---|---|
| Subconjunto `apps.reports` (antes) | `PBKDF2PasswordHasher` | 6 | 54,26 s totales (43,26 s en pruebas) |
| Subconjunto `apps.reports` (después) | `MD5PasswordHasher` solo en test | 6 | **11,95 s** totales (**1,51 s** en pruebas · ~29× más rápido) |
| Suite completa backend (auditoría 08/11) | `PBKDF2PasswordHasher` (SQLite) | 922 | ~28 min |
| Suite completa backend con `coverage` (después) | `MD5PasswordHasher` (SQLite + cobertura) | **1061** | **328,87 s** (5 min 29 s) |
| Suite completa frontend (`npm test`) | `node --test` | **262** | **3,49 s** |

!!! tip "Por debajo del límite de 5 minutos en pruebas funcionales"
    Incluso ejecutando **1061 pruebas** secuenciales con instrumentación de `coverage` y pruebas de concurrencia con
    `TransactionTestCase` (`serialized_rollback = True`), la suite completa del backend finaliza cerca de los 5 minutos en máquina local.

---

## 2. Cobertura de código medida con `coverage` (Backend)

Medición obtenida sobre `apps/` (excluyendo migraciones, archivos de prueba y comandos `seed_*` / `generar_*` según
`pyproject.toml`):

| Módulo | Sentencias cubiertas / totales | Cobertura |
|---|---|---|
| `apps/core` | 214 / 244 | **87,7 %** |
| `apps/users` | 911 / 975 | **93,4 %** |
| `apps/inventory` | 1061 / 1118 | **94,9 %** |
| `apps/purchasing` | 549 / 556 | **98,7 %** |
| `apps/references` | 679 / 690 | **98,4 %** |
| `apps/production` | 2075 / 2161 | **96,0 %** |
| `apps/quality` | 343 / 364 | **94,2 %** |
| `apps/finished` | 572 / 604 | **94,7 %** |
| `apps/sales` | 936 / 981 | **95,4 %** |
| `apps/shipping` | 865 / 903 | **95,8 %** |
| `apps/reports` | 385 / 405 | **95,1 %** |
| **Total backend** | **8590 / 9001** | **95 %** |

---

## 3. Reporte de cobertura por Historia de Usuario (H06)

Convención de tipos de prueba en la tabla:

- **Lógica pura:** funciones deterministas sin base de datos ni navegador (`node --test` en frontend; cálculos de redondeo, estados y validaciones puras en backend).
- **Servicios / Componentes:** capa de servicios transaccionales (`services.py`, `tracking.py`, `invoicing.py`), modelos/restricciones DB, y contratos de componentes/guardas UI (`client.js`, `permissions.js`, `modules.js`).
- **E2E API (extremo a extremo por API REST):** flujos completos contra endpoints con autenticación JWT/rol, base de datos real (SQLite/PostgreSQL), migraciones y códigos HTTP reales (`200/201` y negativos `400/401/403/404/409`). *(Nota: la aplicación aún no incorpora una suite de navegador headless como Playwright/Cypress).*

| Historia / Área | Clave Jira | Backend (Total / Negativas) | Frontend (`node --test`) | Desglose por nivel | Verificación en PostgreSQL (`CI`) |
|---|---|---|---|---|---|
| Registro, login JWT, recuperación y seguridad | TE-78, TE-42, TE-43 | 31 / 20 | 10 *(cliente HTTP + guardas + menú)* | Servicios + E2E API + Lógica UI | Validado vía migraciones, `MaxLengthValidationTests` e índices únicos |
| Gestión de usuarios, roles y permisos | TE-44 | 32 / 18 | 2 *(`modules.test.js`)* | Servicios + E2E API + Contrato rutas | Semilla inicial (`0003`) y `serialized_rollback` en `TransactionTestCase` |
| Proveedores y catálogo de materias primas | TE-45, TE-46 | 46 / 28 | 7 *(`money.test.js`)* | Lógica pura + Servicios + E2E API | Bloqueo de producto en actualizaciones y límites `varchar` (`400` vs `DataError`) |
| Movimientos, órdenes de salida, kardex, alertas y costos | TE-47, TE-48 | 86 / 48 | 11 *(`orderLines.test.js`)* | Lógica pura + Servicios + E2E API | `SELECT ... FOR UPDATE` ordenado en `lock_products` |
| Compras: órdenes, aprobación independiente y recepción | TE-178 *(HU 2.5)* | 73 / 42 | 15 *(`purchasing.test.js`)* | Lógica pura + Servicios + E2E API | Transacciones, aprobación independiente y separación de funciones |
| Referencias de jean y ficha técnica | TE-49, TE-50 | 121 / 60 | 28 *(`variants` + `fichaRows`)* | Lógica pura + Servicios + E2E API | Restricciones de unicidad e integridad referencial |
| Simulación de material (producción) | TE-51 | 43 / 21 | — | Lógica pura + E2E API | Incluida en job `apps.production` en PostgreSQL |
| Órdenes de producción, lotes, concurrencia (H01) y modelos | TE-52 | 88 / 31 | 37 *(`lotSplit` + `lotSizes`)* | Lógica pura + Concurrencia multihilo + E2E API | **Sí (crítico):** concurrencia `H01` con 2 hilos + `Barrier(2)` sobre 500 m de tela |
| Control de tiempos por etapa | TE-53 | 56 / 14 | 11 *(`lotTracking.test.js`)* | Lógica pura + Servicios + E2E API | Incluida en job `apps.production` en PostgreSQL |
| Asignación de operarios y máquinas | TE-54 | 57 / 24 | 15 *(`resources.test.js`)* | Lógica pura + Servicios + E2E API | Incluida en job `apps.production` en PostgreSQL |
| Monitor Kanban y transición inválida API (H03) | TE-55 | 46 / 12 | 23 *(`monitorBoard.test.js`)* | Lógica pura + Reversión optimista UI + E2E API | Incluida en job `apps.production` en PostgreSQL |
| Liquidación y costeo de órdenes | TE-56 | 22 / 12 | 10 *(`costSettlement.test.js`)* | Lógica pura + Servicios + E2E API | Incluida en job `apps.production` en PostgreSQL |
| Remisión y recepción de lavandería externa confiable | TE-57, TE-58, TE-172 *(HU 5.4)* | 17 / 8 | 12 *(`laundryReception.test.js`)* | Lógica pura + Servicios + Contrato UI + E2E API | **Sí (crítico):** bloqueo `of=("self",)` con `receta=None` y recepción `0` conformes sin violar `CHECK (cantidad >= 1)` |
| Control de calidad e inspección de marras | TE-59 | 40 / 22 | 9 *(`quality.test.js`)* | Lógica pura + Servicios + E2E API | **Sí (crítico):** bloqueo `of=("self",)` sobre `Lote` con `select_related` |
| Producto terminado: ingreso y ajuste manual | TE-60, TE-61 | 50 / 31 | 16 *(`finished.test.js`)* | Lógica pura + Servicios + E2E API | **Sí (crítico):** bloqueo `of=("self",)` sobre `Inspeccion` en ingreso final |
| Facturación POS interna, clientes, precios y costo desde producción | TE-62, TE-174 *(HU 4.7)* | 45 / 27 | 23 *(`sales.test.js`)* | Lógica pura + Servicios + Contrato UI + E2E API | **Sí (crítico):** promedio ponderado 90 días, `HistorialPrecioReferencia`, permisos `Vendedor` y N+1 (`apps.sales`) |
| Guías de envío, relaciones de despacho y Track123 | TE-63 | 73 / 41 | 13 *(`shipping.test.js`)* | Lógica pura + Servicios (mock HTTP) + E2E API | **Sí (crítico):** `@transaction.atomic` en `assign_guide_to` en `TransactionTestCase` (Fallo 2 Sprint 3) |
| Cartera y conciliación contraentrega | TE-64, TE-173 *(HU 7.5)* | 24 / 15 *(incl. `test_cartera_guias`)* | 14 *(`cartera` + `carteraAction` en `sales.test.js`)* | Lógica pura + Reglas cruzadas guía-cartera + Caja única + E2E API | Ejecutada en jobs PostgreSQL (`apps.sales` y `apps.shipping`) |
| Tablero de reportes, filtros avanzados, paginación y devoluciones | TE-65, TE-177 *(HU 7.7)* | 13 / 5 | 13 *(`reports.test.js` + `usePersistedFilters.test.js`)* | Lógica pura + Exportación XLSX/CSV + Paginación >200 + Zona Colombia + N+1 + E2E API | **Sí (crítico):** `CREATE/REFRESH MATERIALIZED VIEW` v2 con `vendedor_id` y devoluciones en `apps.core.test_postgres` |
| Núcleo, PostgreSQL transversal, ERD/MER y seeds | TE-180 / Sprint 1–3 | 27 / 6 | — | Servicios + Migraciones + PostgreSQL | **Sí:** `apps.core.test_postgres` |
| Observabilidad, manejo de errores, OpenAPI y robustez API | TE-181 | +12 *(incl. en suites)* | — | Manejador global + Logging + E2E API + N+1 | Concurrencia multihilo Track123 (`ConcurrencyTrackingTests`) en `apps.shipping` |
| Retiro de salida a lavandería provisional de Inventario | TE-171 *(HU 5.3)* | Incl. en `inventory` *(rechazo 400 + historial LV)* | +1 contrato UI *(`orderLines.test.js`)* | Servicios + Serializers + Contrato UI + E2E API | Validada en `apps.inventory` y flujo real lavandería (`apps.production`) |
| Unificación de existencias de producto terminado | TE-170 *(HU 6.5)* | 6 / 3 | +2 *(`orderLines.test.js`)* | Lógica pura + Migración datos + Contrato UI + E2E API + N+1 | **Sí (crítico):** alta automática con `select_for_update`, restricción única por referencia, `heredado` y alertas vivas |
| Seguridad, bloqueo, accesos y auditoría | TE-175, TE-179 | +70 *(incl. en suites)* | — | Throttling + Auditoría + Permisos + E2E API | Validada en `apps.users`, `apps.reports` y `apps.core` sobre PostgreSQL 16 |
| **Total sistema** | **TE-42 a TE-181 + TE-170 a TE-177** | **1076** | **264** | **Lógica + Servicios/UI + E2E API** | **7 suites completas + `core.test_postgres` sobre PostgreSQL 16** |

> Nota sobre el conteo de ejecución: el corredor de Django ejecuta **1076** casos (`OK`, con 2 pruebas multi-hilo condicionales en SQLite — `ConcurrencyOrderTests` y `ConcurrencyTrackingTests` — que corren obligatoriamente en el job PostgreSQL).

---

## 4. Integración continua (GitHub Actions)

Ambos repositorios cuentan con flujos en `.github/workflows/ci.yml` disparados en cada `push` y `pull_request` hacia `main` y `pruebas`:

1. **Backend (`.github/workflows/ci.yml`):**
   - Job `calidad-y-pruebas`: instala `-r requirements-dev.txt -c constraints.txt`, ejecuta `ruff check apps config`, `python manage.py makemigrations --check --dry-run`, `python manage.py spectacular --file /tmp/openapi-schema.yml --validate --fail-on-warn`, `coverage run manage.py test` + `coverage report --fail-under=85`, `mkdocs build --strict` y `pip-audit -r requirements.txt`.
   - Job `verificacion-postgres`: levanta un servicio `postgres:16-alpine` con `TEST_DATABASE_URL` y ejecuta las pruebas de `apps.core.test_postgres`, `apps.production`, `apps.quality`, `apps.finished`, `apps.sales`, `apps.shipping` y `apps.reports`.
2. **Frontend (`.github/workflows/ci.yml`):**
   - Job `calidad-frontend`: ejecuta `npm ci`, `npm run lint` (`oxlint src`), `npm test` (`node --test`), `npm run build` (`vite build`), auditoría bloqueante de vulnerabilidades críticas en producción (`npm audit --omit=dev --audit-level=critical`) y reporte informativo completo.

---

## 5. Verificación en vivo para sustentación (H01, H03 y fallos del Sprint 3)

### 5.1 Concurrencia de órdenes de producción (H01)
Dos peticiones simultáneas de 330 m cada una sobre un inventario de 500 m de tela (requieren 660 m en conjunto):

```bash
# En SQLite (verifica la invariante de stock sin saldo negativo):
python manage.py test apps.production.test_ordenes.ConcurrencyOrderTests -v 2

# En PostgreSQL (ejecuta la carrera real con 2 hilos y threading.Barrier(2)):
TEST_DATABASE_URL="postgresql://texcore:texcore@localhost:5432/texcore_test" \
  python manage.py test apps.production.test_ordenes.ConcurrencyOrderTests -v 2
```

Resultado esperado: exactamente **1** orden creada (HTTP 201), la segunda rechazada (HTTP 400 por stock insuficiente), **170,00 m** restantes y cero órdenes parciales.

### 5.2 Transiciones inválidas en el Monitor Kanban (H03)

```bash
# Backend (rechaza pasar de PLANEADA a TERMINADA por API directa):
python manage.py test apps.production.test_monitor.TransitionApiGuardTests -v 2

# Frontend (prueba de reversión optimista + mensaje de rechazo de la API):
npm test -- src/components/Production/monitorBoard.test.js
```

### 5.3 Fallos reales del Sprint 3 en PostgreSQL
Ejecutar sobre una instancia PostgreSQL con `TEST_DATABASE_URL`:

```bash
TEST_DATABASE_URL="postgresql://texcore:texcore@localhost:5432/texcore_test" \
  python manage.py test apps.core.test_postgres -v 2
```

- **Fallo 1 (bloqueo sobre outer join nullable):** `test_sprint3_fallo1_bloqueo_of_self_con_outer_join_nullable` crea una `RemisionLote` con `receta=None` y recorre recepción de lavandería, inspección de calidad e ingreso final. Si se retira `of=("self",)` en `recepcion_services.py`, PostgreSQL falla de inmediato con `FOR UPDATE cannot be applied to the nullable side of an outer join`.
- **Fallo 2 (servicio con `select_for_update` sin transacción):** `test_sprint3_fallo2_assign_guide_to_funciona_fuera_de_transaccion_externa` corre dentro de `TransactionTestCase` (sin bloque atómico envolvente) e invoca `assign_guide_to(...)`. Si se retira `@transaction.atomic`, PostgreSQL falla de inmediato con `TransactionManagementError: select_for_update cannot be used outside of a transaction`.
