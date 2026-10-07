"""
Permiso por ruta (HU 1.4). Es una permission class y no un middleware porque el
usuario del JWT solo existe dentro de DRF. Se usa por defecto en todas las vistas
(settings.REST_FRAMEWORK); cada vista declara qué permiso exige:

    required_permissions = {"GET": "inventario.ver", "POST": "inventario.gestionar"}
    required_permissions = "inventario.ver"   # el mismo para todos los métodos
"""

from rest_framework.permissions import BasePermission


class HasPermission(BasePermission):
    """Permiso por defecto de la API: la vista declara `required_permissions` y el rol del usuario debe tenerlo.
    Falla cerrado: una vista o método sin permiso declarado no se abre.
    """
    message = "Tu rol no tiene permiso para realizar esta acción."

    def has_permission(self, request, view):
        """True si hay sesión y el rol tiene el permiso que la vista exige para el método HTTP."""
        user = request.user
        if not (user and user.is_authenticated):
            return False

        required = getattr(view, "required_permissions", None)
        if isinstance(required, dict):
            method = "GET" if request.method == "HEAD" else request.method
            required = required.get(method)
        # Falla cerrado: una vista o un método sin permiso declarado no se abre.
        if not required:
            return request.method == "OPTIONS"
        return user.has_permission_code(required)
