from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel

from . import catalog


class ModulePermission(BaseModel):
    """Acción concreta sobre un módulo, p. ej. "inventario.gestionar"."""

    code = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    module = models.CharField(max_length=40)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "seguridad_permiso"
        ordering = ["module", "code"]

    def __str__(self):
        return self.code


class Role(BaseModel):
    """Perfil de acceso. El código es inmutable: lo usan el JWT y el frontend."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)
    # Los roles del sistema (los del diagrama de casos de uso) no se pueden borrar.
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(
        ModulePermission, through="RolePermission", related_name="roles", blank=True
    )

    class Meta:
        db_table = "seguridad_rol"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def has_all_permissions(self):
        return self.code == catalog.ADMIN


class RolePermission(models.Model):
    """Asignación de un permiso a un rol (tabla intermedia), con quién y cuándo lo concedió."""
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(ModulePermission, on_delete=models.CASCADE)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        "users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "seguridad_rol_permiso"
        constraints = [models.UniqueConstraint(fields=["role", "permission"], name="uq_rol_permiso")]


class CustomUserManager(UserManager):
    """Manager que oculta los usuarios eliminados (borrado lógico) y crea superusuarios con rol ADMIN."""
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role_id", catalog.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class CustomUser(AbstractUser, BaseModel):
    """Usuario del sistema. El correo es también el `username`; el rol decide los permisos (RBAC)."""
    # to_field="code" + db_column: la columna sigue guardando el código del rol
    # ("ADMIN", "VENDEDOR"...), igual que antes de tener tabla de roles.
    role = models.ForeignKey(
        Role,
        to_field="code",
        db_column="role",
        on_delete=models.PROTECT,
        default=catalog.PENDING,
        related_name="users",
    )
    requested_area = models.ForeignKey(
        Role,
        to_field="code",
        db_column="requested_area",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    document_id = models.CharField(max_length=20, null=True, blank=True)

    objects = CustomUserManager()
    all_objects = UserManager()

    def __str__(self):
        return f"{self.username} - {self.role_id}"

    def get_permission_codes(self):
        """Códigos de permiso efectivos del usuario (se cachean por instancia)."""
        if not hasattr(self, "_permission_codes"):
            if not self.is_active:
                codes = set()
            elif self.role_id == catalog.ADMIN:
                codes = set(ModulePermission.objects.values_list("code", flat=True))
            else:
                codes = set(
                    ModulePermission.objects.filter(roles__code=self.role_id).values_list("code", flat=True)
                )
            self._permission_codes = codes
        return self._permission_codes

    def has_permission_code(self, code):
        return code in self.get_permission_codes()


class PasswordResetToken(models.Model):
    """Token de un solo uso para restablecer o definir la contraseña (HU 1.3).

    Solo se guarda el hash SHA-256: si alguien lee la tabla no puede usar los tokens.
    """

    PURPOSE_RESET = "reset"
    PURPOSE_INVITE = "invite"
    PURPOSE_CHOICES = [
        (PURPOSE_RESET, "Recuperación de contraseña"),
        (PURPOSE_INVITE, "Activación de cuenta creada por un administrador"),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="reset_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=10, choices=PURPOSE_CHOICES, default=PURPOSE_RESET)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "seguridad_token_recuperacion"
        ordering = ["-created_at"]

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()
