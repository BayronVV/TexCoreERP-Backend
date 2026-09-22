from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from apps.core.models import BaseModel

class CustomUserManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)
    
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'ADMIN')
        return super().create_superuser(username, email, password, **extra_fields)

class CustomUser(AbstractUser, BaseModel):
    objects = CustomUserManager()
    ROLE_CHOICES = (
        ('PENDING', 'Pendiente'),
        ('ADMIN', 'Administrador'),
        ('VENDEDOR', 'Vendedor'),
        ('GERENTE', 'Gerente'),
        ('PRODUCCION', 'Jefe de Producción'),
        ('ALMACENISTA', 'Almacenista'),
        ('TERMINACION', 'Personal de Terminacion'),
        ('SECRETARIA', 'Secretaria'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='PENDING')
    requested_area = models.CharField(max_length=20, choices=ROLE_CHOICES, null=True, blank=True)
    document_id = models.CharField(max_length=20, null=True, blank=True)

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"
