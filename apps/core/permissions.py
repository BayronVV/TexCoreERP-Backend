"""
Control de acceso por rol (HU 1.4 - TE-77).

DRF resuelve la autenticación JWT y arma `request.user` durante el
despacho de la vista, no en el pipeline de `MIDDLEWARE` de Django (ahí
`request.user` todavía sería anónimo). Por eso el punto correcto para
"interceptar la petición y validar si el rol tiene acceso a la ruta" es
una permission class de DRF: corre antes que el `handler` de la vista,
para cada request, exactamente igual que un middleware — pero con
`request.user` ya resuelto.

Uso en una vista:

    class MiVista(generics.ListAPIView):
        permission_classes = [HasRole]
        allowed_roles = ["ADMIN", "GERENTE"]
"""
from rest_framework.permissions import BasePermission


class HasRole(BasePermission):
    """Permite el acceso solo si el usuario autenticado tiene uno de los
    roles listados en `view.allowed_roles`. Si la vista no define
    `allowed_roles`, no restringe (deja pasar a cualquier autenticado)."""

    message = "Tu rol no tiene permiso para acceder a este recurso."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        allowed_roles = getattr(view, "allowed_roles", None)
        if not allowed_roles:
            return True

        return request.user.role in allowed_roles
