from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', 'Administrador'),
        ('SECRETARY', 'Secretaria'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='SECRETARY')

    def __str__(self):
        return f"{self.username} - {self.get_role_display()}"
