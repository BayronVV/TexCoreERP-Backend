"""
Constantes compartidas de TexCore.

ROLE_MODULES es la fuente única de verdad de qué módulo del sistema puede
ver/usar cada rol (basado en el diagrama de casos de uso del negocio). La
usan:

- El backend, para documentar qué `allowed_roles` corresponde a cada
  endpoint (ver apps/core/permissions.HasRole).
- El frontend, en `src/config/roleModules.js`, para bloquear visualmente
  el menú lateral (HU 1.4 / TE-75). Si cambias esta lista, actualiza
  también la copia del frontend.

"*" significa "todos los módulos" (solo lo tiene ADMIN).
"""

ADMIN = "ADMIN"
VENDEDOR = "VENDEDOR"
GERENTE = "GERENTE"
PRODUCCION = "PRODUCCION"
ALMACENISTA = "ALMACENISTA"
TERMINACION = "TERMINACION"
SECRETARIA = "SECRETARIA"
PENDING = "PENDING"

ROLE_MODULES = {
    ADMIN: ["*"],
    ALMACENISTA: ["inventario"],
    PRODUCCION: ["fichas_tecnicas", "produccion", "lavanderia"],
    TERMINACION: ["calidad"],
    SECRETARIA: ["producto_terminado"],
    VENDEDOR: ["ventas"],
    GERENTE: ["reportes"],
    PENDING: [],
}

# El módulo de "usuarios" (este HU) solo lo administra ADMIN.
USERS_MODULE_ROLES = [ADMIN]
