from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
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

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"
