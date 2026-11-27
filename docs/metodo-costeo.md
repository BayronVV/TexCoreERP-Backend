# Método de costeo (H02)

Especificación técnica y funcional de cómo TexCore ERP calcula el costo de producción (HU 4.6), el servicio de lavandería (HU 5.2 / 5.4) y el costo sugerido de fábrica (HU 4.7). Todas las reglas aquí descritas reflejan la implementación exacta en `apps/inventory/services.py`, `apps/production/costing.py`, `apps/production/tracking.py`, `apps/production/recepcion_services.py` y `apps/sales/pricing.py`.

---

## 1. Costo real vs. costo estimado / provisional

La pantalla y endpoint `GET /api/produccion/ordenes/<id>/costos/` devuelven una **liquidación en vivo** compuesta por materiales + mano de obra por etapa y por lote, acompañada de dos banderas de confiabilidad:

| Indicador | Qué significa en el sistema | Cuándo ocurre |
|---|---|---|
| `completo: true` | Todos los materiales consumidos tienen `costo_unitario` y todas las etapas con tiempo neto `> 0` tienen tarifa vigente | Liquidación financiera completa para tomar decisiones y sugerir costo de fábrica |
| `completo: false` + `advertencias` | Falta el costo de al menos un insumo (`sin_costo: true`) o la tarifa de alguna etapa ejecutada (`sin_tarifa: true`) | Los faltantes aportan `$0.00` de forma explícita y aparecen advertencias detalladas (`"Falta la tarifa de la etapa …"`, `"El material … no tiene costo."`) |
| `provisional: true` (por etapa) | La etapa todavía está **En curso** (`STAGE_RUNNING`) o fue reanudada y sigue acumulando tiempo | El costo mostrado es parcial con corte al instante actual; al finalizar la etapa queda definitivo |
| Orden anulada (`anulada: true`) | La `OrdenSalida` fue anulada | Todos los totales de materiales, mano de obra y costo por prenda se reportan en `$0.00` |

> **Nota:** la liquidación de orden (`costing.py`) evalúa los **costos internos de producción** (materiales + mano de obra). El costo del **servicio externo de lavandería** y las **prendas aptas** se integran en el cálculo del costo de fábrica sugerido por referencia (sección 5).

---

## 2. Valoración de materiales y prorrateo por lote

1. **Costo promedio ponderado en Inventario (`inventory.services.register_entry`):**
   - Cada compra o ingreso con `costo_unitario` actualiza el `costo_promedio` de `Producto` mediante promedio ponderado:
     $$\text{CPP}_{\text{nuevo}} = \frac{(\text{stock\_actual} \times \text{costo\_promedio}_{\text{actual}}) + (\text{cantidad} \times \text{costo\_unitario})}{\text{stock\_actual} + \text{cantidad}}$$
   - Redondeado a **4 decimales** (`0.0001`). Si el stock previo era 0, toma directamente el `costo_unitario` de la compra.
2. **Foto inmutable al crear la orden (`OrdenLinea.costo_unitario`):**
   - Al generar la orden de producción (`OP-XXXX`), cada línea de material descontada en la `OrdenSalida` congela el `costo_promedio` vigente de ese instante en `OrdenLinea.costo_unitario`.
   - Costo de línea: `round_cents(cantidad × costo_unitario)` usando `ROUND_HALF_UP` a 2 decimales.
3. **Prorrateo proporcional por lote:**
   - El material se descuenta por la orden completa, así que a cada lote se le asigna:
     $$\text{materiales}_{\text{lote}} = \text{round\_cents}\!\left(\text{total\_materiales} \times \frac{\text{prendas\_del\_lote}}{\text{prendas\_de\_la\_orden}}\right)$$

---

## 3. Tarifa por fecha de ejecución y tratamiento de las pausas

1. **Tiempo neto de ejecución (`production.tracking.net_seconds`):**
   - Solo suma el tiempo efectivo trabajado en cada etapa (`Corte`, `Confección`, `Terminación`).
   - Cada transición a **Pausa** suma `int((ahora - reanudada_at).total_seconds())` a `tiempo_acumulado_seg` y detiene el reloj; los intervalos pausados **no se cobran** como mano de obra.
   - El reloj de las etapas se almacena al segundo y se convierte a minutos solo al costear: `(segundos_netos / 60) × tarifa_minuto`, redondeando con `ROUND_HALF_UP` únicamente al final.
2. **Tarifa vigente en la fecha de ejecución (`costing.find_applicable_rate`):**
   - Cada registro en `TarifaManoObra` guarda `(etapa, costo_minuto, vigente_desde)`.
   - Para cada etapa de cada lote, la fecha de referencia (`target_date`) es `stage.fin_at.date()` si la etapa ya finalizó, o `today` si sigue abierta/pendiente.
   - Se busca la tarifa con `vigente_desde <= target_date` ordenada por `-vigente_desde, -id`. Así, crear hoy una tarifa más alta con `vigente_desde = hoy` **no modifica retroactivamente** las etapas terminadas ayer.
   - Si `net_seconds == 0` y no hay tarifa, no marca faltante (`sin_tarifa = False`); solo exige tarifa cuando hubo ejecución (`net_seconds > 0`).

---

## 4. Costo por unidad y servicio de lavandería

- **En liquidación de la orden (`costing.calculate_order_costs`):**
  $$\text{costo\_por\_prenda\_orden} = \text{round\_cents}\!\left(\frac{\text{total\_materiales} + \text{total\_mano\_obra}}{\text{cantidad\_planificada\_orden}}\right)$$
- **En recepción de lavandería (`production.recepcion_services.create_laundry_reception`):**
  - El servicio de lavado contratado de cada lote se calcula como `cantidad_recibida_conforme × receta.tarifa_sugerida`.
  - Si hubo pérdidas (`cantidad_merma + cantidad_danada > 0`), exige `costo_unitario_prenda` y liquida la pérdida como `unidades_perdidas × costo_unitario_prenda`.

---

## 5. Costo de fábrica sugerido para Ventas (HU 4.7, TE-174)

Implementado en `apps/sales/pricing.py` (`evaluate_order_factory_cost` y `calculate_references_costs`):

1. Toma órdenes no anuladas cuyas etapas estén todas terminadas (`STATE_DONE`), con recepción de lavandería e inspección registradas, cerradas dentro de la ventana de **90 días** (`COST_WINDOW_DAYS = 90`).
2. Para cada orden completa calcula:
   $$\text{costo\_total\_orden} = \text{materiales} + \text{mano\_obra} + \text{servicio\_lavanderia}$$
3. Agrupa las órdenes completas por referencia como **promedio ponderado por prendas aptas** de calidad (al peso entero más cercano con `ROUND_HALF_UP`):
   $$\text{costo\_calculado\_fabrica} = \text{round\_cop}\!\left(\frac{\sum \text{costo\_total\_orden}}{\sum \text{prendas\_aptas}}\right)$$
4. **Sugerencia controlada:** si falta tarifa o costo de material en alguna orden, se reporta `estado: INCOMPLETO` y qué falta; el costo vigente nunca cambia automático, requiere confirmación manual (`ventas.precios`), valida que `precio_mayorista >= costo_fabrica` y deja auditoría en `HistorialPrecioReferencia`.

---

## 6. Por qué una liquidación histórica y las facturas no cambian

- `OrdenLinea.costo_unitario` guarda el CPP exacto del momento del despacho, aislando la orden de compras posteriores de insumos.
- `TarifaManoObra` funciona como histórico por `vigente_desde`: nuevas vigencias no sobrescriben tarifas de etapas ya cerradas en fechas pasadas.
- Al emitir una factura, `DetalleVenta.costo_unitario` congela el `costo_fabrica` vigente en ese momento y `HistorialPrecioReferencia` registra quién, cuándo y con qué origen cambió `PrecioReferencia`; aplicar un nuevo costo nunca reescribe facturas emitidas.
