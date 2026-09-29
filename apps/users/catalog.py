"""Códigos de rol y permiso que el código usa por nombre. La matriz inicial rol ->
permiso está en la migración 0003; después se edita desde "Roles y permisos"."""

ADMIN = "ADMIN"
PENDING = "PENDING"

# Roles que NO se pueden pedir al registrarse.
NON_REQUESTABLE_ROLES = {ADMIN, PENDING}

USERS_VIEW = "seguridad.ver"
USERS_MANAGE = "seguridad.gestionar"
ROLES_MANAGE = "seguridad.roles"
