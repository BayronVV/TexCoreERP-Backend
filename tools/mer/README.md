# Render del MER (notación de Chen)

Graphviz no es dependencia del proyecto: se usa su versión en WebAssembly desde Node, solo para regenerar las imágenes de `docs/img/mer-*`.

```bash
cd backend
python manage.py generar_mer --dot-dir /tmp/mer-dot          # un .dot por figura (determinista)
cd tools/mer && npm install                                    # una sola vez
node render.mjs /tmp/mer-dot ../../docs/img all 8000           # figuras por módulo y MER general (neato)
node radial.mjs /tmp/mer-dot/mer-general-atributos.dot ../../docs/img 1.8 0.22 8000
```

- `render.mjs <dot> <salida> [figuras|all] [px]`: dibuja con `neato`, genera SVG y PNG (lado mayor máx. `px`, 8000 por defecto). Usa Arial de Windows para el texto; cambia las rutas de `fontFiles` en otros sistemas.
- `radial.mjs <dot> <salida> [escala] [separación] [px]`: dibuja primero entidades y rombos con `neato`, escala las posiciones y coloca los atributos alrededor de cada entidad evitando choques (el MER general con atributos no queda legible con el motor automático).
- Después de cambiar un modelo hay que regenerar `docs/modelo-de-datos.md` (`generar_erd`) **y** las imágenes: son estáticas.
- Un PNG de más de 8000 px puede salir en blanco o ser rechazado al compartirlo; el SVG es el vectorial.
