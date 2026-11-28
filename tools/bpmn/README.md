# Diagramas BPMN del proceso de negocio

Genera `texcore-proceso.bpmn` (visión de conjunto) y dos diagramas de detalle (`-produccion`, `-venta`) con apariencia estándar de bpmn.io, y los convierte a SVG y PNG.

```bash
cd backend/tools/bpmn
python generar_bpmn.py /tmp/bpmn            # escribe los .bpmn con el diagrama (DI) completo
npm install                                  # una sola vez (bpmn-js, puppeteer-core, resvg y bpmnlint)
npx bpmnlint /tmp/bpmn/*.bpmn                # validación BPMN (0 errores)
node render.mjs /tmp/bpmn-img /tmp/bpmn/*.bpmn   # SVG + PNG; falla si bpmn-js avisa de algo
```

- La definición (carriles, participantes externos, nodos con carril y columna, flujos con su condición o salida por defecto, flujos de mensaje y notas) está al inicio de `generar_bpmn.py`; los diagramas de detalle son cortes por columna de la misma definición.
- La lavandería y la transportadora son **participantes externos** (piscinas negras): solo se dibujan sus intercambios con TexCore como flujos de mensaje.
- `generar_bpmn.py` falla (código 1) si una compuerta no tiene exactamente una salida por defecto, si a otra salida le falta su condición, si un nodo queda sin entrada o sin salida, o si una línea atraviesa una tarea.
- `npx bpmnlint ../../docs/bpmn/*.bpmn` valida los diagramas con las reglas recomendadas (`.bpmnlintrc`); la integración continua lo corre y comprueba que los `.bpmn` publicados son los que genera el script. Los avisos `fake-join` (tareas a las que llegan dos caminos sin compuerta de unión) no son errores.
- `render.mjs` usa Microsoft Edge sin ventana (`EDGE_PATH` cambia la ruta) y Arial de Windows para el PNG (lado mayor máximo `MAX_PX`, 8000 por defecto). `BPMN_NODE_MODULES` permite usar un `node_modules` en otra carpeta.
- Después copia los `.bpmn` a `docs/bpmn/` y los SVG/PNG a `docs/img/bpmn-*` (y a `BPMN/` en la raíz del proyecto): son estáticos.
