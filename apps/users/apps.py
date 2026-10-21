"""Configuración de la app `users` (usuarios, roles y permisos)."""
from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Registro de la app de usuarios, roles y permisos."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
