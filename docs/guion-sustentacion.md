# Guion de sustentación en vivo (TE-187)

Comandos ejecutables y resultados esperados para demostrar en vivo (en **menos de 2 minutos** cada escenario) la coherencia de cantidades, saldos, concurrencia, seguridad y manejo de errores entre todos los módulos.

> **Requisito previo:** posicionarse en `backend/` (con el entorno virtual activo) o en `frontend/` según el escenario. Para pruebas con concurrencia multi-hilo real (`TEST_DATABASE_URL`), exportar la cadena de PostgreSQL local o de pruebas:
> ```bash
> export TEST_DATABASE_URL="postgresql://texcore:texcore@localhost:5432/texcore_test"
> ```

---

## Escenario 1 · Lavandería, Calidad e Inventario Final (`120 → 115 → 5 → 8 → 107`)

**Qué demuestra:** se remiten **120** prendas a lavandería, retornan **115** conformes con **5** faltantes en merma, Calidad clasifica **8** como marras, exactamente **107** quedan disponibles para ingreso final y todas las diferencias conservan historial consultable por Gerencia.

```bash
python manage.py test apps.core.test_e2e_sustentacion.LavanderiaCalidadInventarioE2ETests -v 2
```

- **Resultado esperado:** `Ran 1 test ... OK`. Verifica `Lote.cantidad == 120` preservado (TE-172), recepción `total_recibido_conforme == 115` / `total_merma == 5`, inspección `aptas == 107` / `marras == 8`, rechazo `400` al intentar ingresar `108` y stock final total de `107`.

---

## Escenario 2 · Controles integrales del Inventario Final

**Qué demuestra:** tope estricto contra las `aptas` inspeccionadas, imposibilidad de ingresar o ajustar dos veces un mismo comprobante/token (`409`), prohibición de existencias negativas (`400`), registro de trazabilidad en ajustes (`realizado_por_nombre`, `fecha`, `motivo`, `saldo_antes`/`saldo_despues`) y cero movimientos huérfanos ante fallos.

```bash
# Prueba integral E2E + baterías existentes de ingresos y ajustes:
python manage.py test apps.core.test_e2e_sustentacion.ControlesInventarioFinalTests apps.finished -v 2
```

- **Resultado esperado:** todas las pruebas de `ControlesInventarioFinalTests` (`1`), `EntryTests` (`21`) y `AdjustmentsTests` (`26`) en verde (`OK`).

---

## Escenario 3 · Concurrencia real en Producción y Facturación (PostgreSQL)

**Qué demuestra:** dos peticiones simultáneas compitiendo por las últimas unidades con conexiones independientes sobre PostgreSQL (`threading.Barrier(2)` + `SELECT ... FOR UPDATE`). Solo gana una (`201`), la segunda rechaza con `400`, el consecutivo no deja huecos, los saldos/montos/cartera cuadran, la anulación revierte exactamente el stock y si se retirara el bloqueo por fila la prueba fallaría de inmediato.

```bash
# 1) Facturación concurrente, consecutivos, IVA, cartera, anulación y verificación de bloqueo:
python manage.py test apps.sales.test_concurrencia_facturacion -v 2

# 2) Concurrencia en órdenes de producción (H01: 2 órdenes de 330 m sobre 500 m):
python manage.py test apps.production.test_ordenes.ConcurrencyOrderTests -v 2
```

> En SQLite corre la verificación secuencial y la comprobación explícita de `select_for_update()` (`test_te187_prueba_concurrencia_detecta_ausencia_de_bloqueo`); con `TEST_DATABASE_URL` hacia PostgreSQL se ejecuta además la carrera real multi-hilo con `Barrier(2)` (`201` + `400`).

---

## Escenario 4 · Reportes coherentes antes y después de pago y devolución

**Qué demuestra:** una factura emitida contraentrega NO cuenta como dinero recaudado hasta que se confirma el pago; tras recaudar una factura (`ENTREGADA`) y registrar devolución física en otra (`DEVUELTA` con flete `$14.000`), el KPI del tablero, la caja y las tablas exportables a Excel/CSV coinciden exactamente.

```bash
# Backend (E2E reporte antes/después de pago y devolución):
python manage.py test apps.core.test_e2e_sustentacion.ReportesCoherentesE2ETests -v 2

# Frontend (coincidencia de matriz de exportación Excel/CSV vs KPIs):
cd ../frontend && npm test -- src/components/Reports/reports.test.js
```

---

## Escenario 5 · Fallos controlados de Track123

**Qué demuestra:** sin respuesta (timeout/`503`), cuota agotada (`0` restante/`400`), guía no registrada aún (`NO_RECORD`/`200` sin 500) y datos desactualizados (`ENTREGADA` no retrocede a `EN TRÁNSITO`); ninguna venta ni despacho queda bloqueado.

```bash
python manage.py test apps.shipping.test_rastreo -v 2
```

---

## Escenario 6 · Permisos en el 100 % de las rutas de la API (RNF01)

**Qué demuestra:** inspección dinámica de las `123` rutas de `/api/`: solo las `8` rutas públicas esperadas admiten anónimos (`AllowAny`/`()`), `/api/auth/me/` exige sesión, y el **100 % de las rutas restantes** en cada método HTTP implementado responde `401` sin token y `403` con un usuario autenticado sin permisos.

```bash
python manage.py test apps.core.test_permisos_rutas -v 2
```

---

## Escenario 7 · Errores en interfaz sin datos obsoletos ni simulados

**Qué demuestra:** las pantallas críticas traducen errores `403`/`500`/`503` y pérdida de conexión (`ApiError status 0`), limpian el estado anterior (`null`/`[]`), muestran el mensaje de error al usuario y no contienen datos simulados de respaldo.

```bash
cd ../frontend && npm test -- src/uiErrorHandling.test.js
```
