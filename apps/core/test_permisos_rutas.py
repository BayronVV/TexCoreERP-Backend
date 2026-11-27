"""
Auditoría automática del 100 % de las rutas de la API (RNF01, TE-187):
- Recorre todas las URL registradas bajo `api/` (salvo las de documentación OpenAPI).
- Verifica que solo las 8 rutas públicas esperadas permitan acceso anónimo.
- Verifica que `api/auth/me/` exija sesión (401 sin sesión, 200 con sesión).
- Verifica sobre el 100 % de las rutas restantes (y todos sus métodos HTTP implementados) que:
  * Usen `HasPermission` con `required_permissions` explícito.
  * Sin sesión respondan `401`.
  * Con sesión de un rol sin permisos respondan `403`.
"""
import re

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.test import APIClient

from apps.core.permissions import HasPermission
from apps.core.testing import client_for, make_user
from apps.users.models import Role

DOC_PREFIXES = ("api/docs/", "api/redoc/", "api/schema/")
PUBLIC_ROUTES = {
    "api/health/",
    "api/health/db/",
    "api/register/",
    "api/token/",
    "api/token/refresh/",
    "api/auth/password-reset/",
    "api/auth/password-reset/validate/",
    "api/auth/password-reset/confirm/",
}
SESSION_ONLY_ROUTES = {"api/auth/me/"}
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _iter_api_patterns(patterns=None, prefix=""):
    if patterns is None:
        patterns = get_resolver().url_patterns
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _iter_api_patterns(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            route = prefix + str(entry.pattern)
            if route.startswith("api/") and not route.startswith(DOC_PREFIXES):
                yield route, entry.callback


def _concrete_path(route):
    path = re.sub(r"<int:[^>]+>", "999999", route)
    path = re.sub(r"<str:[^>]+>", "accion_invalida", path)
    path = re.sub(r"<[^>]+>", "test", path)
    return "/" + path


class AllApiRoutesPermissionsTests(TestCase):
    """Recorre todas las rutas de la API verificando 401 sin sesión y 403 con un rol sin permisos."""

    def test_te187_permisos_en_el_100_por_ciento_de_las_rutas(self):
        Role.objects.get_or_create(code="SIN_PERMISOS", defaults={"name": "Sin permisos"})
        unpriv_user = make_user("sin_permisos_187@t.co", "SIN_PERMISOS")
        anon = APIClient()
        unpriv = client_for(unpriv_user)

        discovered = list(_iter_api_patterns())
        routes_by_path = {route: cb for route, cb in discovered}
        self.assertGreater(len(discovered), 100)

        found_public = set()
        found_session = set()
        protected_checked = 0

        for route, callback in discovered:
            view_cls = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
            self.assertIsNotNone(view_cls, f"La ruta {route} no expone clase de vista inspeccionable.")
            perm_classes = list(getattr(view_cls, "permission_classes", []) or [])

            if route in PUBLIC_ROUTES:
                self.assertTrue(
                    AllowAny in perm_classes or perm_classes == [],
                    f"{route} figura como pública pero declara {perm_classes}",
                )
                found_public.add(route)
                continue

            self.assertNotIn(AllowAny, perm_classes, f"{route} no debería ser pública")

            if route in SESSION_ONLY_ROUTES:
                self.assertIn(IsAuthenticated, perm_classes, route)
                found_session.add(route)
                url = _concrete_path(route)
                self.assertEqual(anon.get(url).status_code, 401, url)
                self.assertEqual(unpriv.get(url).status_code, 200, url)
                continue

            # Toda ruta de negocio debe estar protegida por HasPermission y required_permissions
            self.assertIn(HasPermission, perm_classes, f"{route} debe usar HasPermission")
            required = getattr(view_cls, "required_permissions", None)
            self.assertTrue(required, f"{route} no declara required_permissions")

            url = _concrete_path(route)
            allowed_names = {m.lower() for m in getattr(view_cls, "http_method_names", HTTP_METHODS)}
            implemented_methods = [m for m in HTTP_METHODS if hasattr(view_cls, m) and m in allowed_names]
            self.assertTrue(implemented_methods, f"{route} no implementa métodos HTTP")

            for method in implemented_methods:
                if isinstance(required, dict):
                    self.assertIn(method.upper(), required, f"{route} {method.upper()} falta en required_permissions")

                anon_res = getattr(anon, method)(url, {}, format="json")
                self.assertEqual(anon_res.status_code, 401, f"{method.upper()} {url} anónimo devolvió {anon_res.status_code}")

                unpriv_res = getattr(unpriv, method)(url, {}, format="json")
                self.assertEqual(unpriv_res.status_code, 403, f"{method.upper()} {url} sin permisos devolvió {unpriv_res.status_code}")
                protected_checked += 1

        self.assertEqual(found_public, PUBLIC_ROUTES)
        self.assertEqual(found_session, SESSION_ONLY_ROUTES)
        self.assertEqual(
            len(routes_by_path) - len(found_public) - len(found_session),
            len(discovered) - len(PUBLIC_ROUTES) - len(SESSION_ONLY_ROUTES),
        )
        self.assertGreaterEqual(protected_checked, 150)
