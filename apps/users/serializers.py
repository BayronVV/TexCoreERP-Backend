import re

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from . import catalog
from .models import ModulePermission, Role
from .validators import validate_password_policy, validate_passwords_match

User = get_user_model()


def _email_taken(email):
    """Incluye usuarios eliminados: username (= correo) es único en toda la tabla."""
    return User.all_objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists()


def other_working_admins(user):
    """¿Queda algún otro ADMIN que de verdad pueda entrar? Bloquea las filas para
    que dos cambios simultáneos no dejen el sistema sin administrador.
    Llamar dentro de transaction.atomic."""
    admins = (
        User.objects.select_for_update()
        .filter(role_id=catalog.ADMIN, is_active=True)
        .exclude(pk=user.pk)
        .exclude(password__startswith="!")  # cuenta invitada que nunca definió su contraseña
    )
    return admins.exists()


def _is_admin(user):
    return user.role_id == catalog.ADMIN


def _grants_security(role):
    return role.code == catalog.ADMIN or role.permissions.filter(module="seguridad").exists()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        # El registro guarda el correo en minúsculas; el login no debe distinguir.
        attrs[self.username_field] = attrs[self.username_field].strip().lower()
        return super().validate(attrs)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role_id
        return token


class SafeTokenRefreshSerializer(TokenRefreshSerializer):
    """Como el de simplejwt, pero: responde 401 (no 500) si el usuario fue
    eliminado, y rechaza refresh tokens emitidos antes de un cambio de contraseña."""

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user = User.objects.filter(pk=refresh.payload.get(jwt_settings.USER_ID_CLAIM)).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed("La cuenta ya no está activa.", "no_active_account")
        if refresh.payload.get(jwt_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(user.password):
            raise AuthenticationFailed("La sesión se cerró porque cambió la contraseña.", "password_changed")
        return super().validate(attrs)


# Usuarios


class UserSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)
    requested_area_name = serializers.CharField(source="requested_area.name", read_only=True, default=None)
    full_name = serializers.SerializerMethodField()
    # False = cuenta creada por un administrador que todavía no definió su contraseña.
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "document_id",
            "role",
            "role_name",
            "requested_area",
            "requested_area_name",
            "is_active",
            "has_password",
            "date_joined",
            "last_login",
        ]
        read_only_fields = fields

    def get_full_name(self, user):
        return user.get_full_name() or user.email

    def get_has_password(self, user):
        return user.has_usable_password()


class MeSerializer(UserSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ["permissions"]
        read_only_fields = fields

    def get_permissions(self, user):
        return sorted(user.get_permission_codes())


class _RoleField(serializers.SlugRelatedField):
    def __init__(self, **kwargs):
        super().__init__(slug_field="code", queryset=Role.objects.all(), **kwargs)


class _AssignRoleMixin:
    """Solo un ADMIN puede entregar el rol de Administrador o un rol con permisos
    del módulo Seguridad. Sin esta regla, quien gestiona usuarios podría fabricarse
    un administrador."""

    def check_can_assign(self, role):
        actor = self.context["request"].user
        if not _is_admin(actor) and _grants_security(role):
            raise PermissionDenied("Solo un Administrador puede asignar ese rol.")


class UserCreateSerializer(_AssignRoleMixin, serializers.ModelSerializer):
    """Alta hecha desde "Usuarios": la persona define su contraseña con el enlace del correo."""

    role = _RoleField()

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "document_id", "role"]
        extra_kwargs = {
            "first_name": {"required": True, "allow_blank": False},
            "last_name": {"required": True, "allow_blank": False},
            "email": {"required": True, "allow_blank": False},
        }

    def validate_email(self, email):
        email = email.strip().lower()
        if _email_taken(email):
            raise ValidationError("Ya existe una cuenta con este correo.")
        return email

    def validate_role(self, role):
        if role.code == catalog.PENDING:
            raise ValidationError("Elige un rol distinto de Pendiente.")
        self.check_can_assign(role)
        return role

    def create(self, validated_data):
        user = User(username=validated_data["email"], **validated_data)
        user.set_unusable_password()
        user.save()
        return user


class UserAdminUpdateSerializer(_AssignRoleMixin, serializers.ModelSerializer):
    role = _RoleField(required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "document_id", "role", "is_active"]

    def validate(self, attrs):
        user = self.instance
        actor = self.context["request"].user
        new_role = attrs.get("role", user.role)
        new_active = attrs.get("is_active", user.is_active)

        if user.pk == actor.pk:
            if new_role.code != user.role_id:
                raise ValidationError({"role": "No puedes cambiar tu propio rol."})
            if not new_active:
                raise ValidationError({"is_active": "No puedes desactivar tu propia cuenta."})

        if _is_admin(user) and not _is_admin(actor):
            raise PermissionDenied("Solo un Administrador puede modificar la cuenta de otro Administrador.")
        if "role" in attrs and new_role.code != user.role_id:
            self.check_can_assign(new_role)

        loses_admin = (
            _is_admin(user) and user.is_active and (new_role.code != catalog.ADMIN or not new_active)
        )
        if loses_admin and not other_working_admins(user):
            raise ValidationError("Debe quedar al menos un administrador activo en el sistema.")
        return attrs


class UserRegistrationSerializer(serializers.ModelSerializer):
    password_confirm = serializers.CharField(write_only=True)
    requested_area = _RoleField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "password",
            "password_confirm",
            "requested_area",
            "document_id",
        ]
        extra_kwargs = {
            "password": {"write_only": True},
            "first_name": {"required": True},
            "last_name": {"required": True},
            "email": {"required": True},
        }

    def validate_email(self, email):
        email = email.strip().lower()
        if _email_taken(email):
            raise ValidationError("Ya existe una cuenta con este correo.")
        return email

    def validate_requested_area(self, role):
        if role and role.code in catalog.NON_REQUESTABLE_ROLES:
            raise ValidationError("Esa área no se puede solicitar.")
        return role

    def validate(self, attrs):
        validate_passwords_match(attrs["password"], attrs["password_confirm"])
        candidate = User(email=attrs["email"], first_name=attrs["first_name"], last_name=attrs["last_name"])
        validate_password_policy(attrs["password"], candidate)
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        return User.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            password=validated_data["password"],
            requested_area=validated_data.get("requested_area"),
            document_id=validated_data.get("document_id") or None,
            role_id=catalog.PENDING,
        )


# Roles y permisos


class ModulePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModulePermission
        fields = ["code", "name", "module", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(
        slug_field="code", queryset=ModulePermission.objects.all(), many=True, required=False
    )
    users_count = serializers.IntegerField(read_only=True, default=0)
    has_all_permissions = serializers.BooleanField(read_only=True)

    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "name",
            "description",
            "is_system",
            "has_all_permissions",
            "permissions",
            "users_count",
        ]
        read_only_fields = ["id", "is_system"]

    def validate_code(self, code):
        if self.instance is not None:
            if code != self.instance.code:
                raise ValidationError("El código de un rol no se puede cambiar.")
            return code
        code = code.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,19}", code):
            raise ValidationError("Usa de 3 a 20 letras mayúsculas, números o guion bajo (ej. SUPERVISOR).")
        if Role.all_objects.filter(code=code).exists():
            raise ValidationError("Ya existe un rol con ese código.")
        return code

    def validate_permissions(self, permissions):
        role = self.instance
        actor = self.context["request"].user
        if role is not None and role.code == catalog.ADMIN:
            raise ValidationError("Los permisos del Administrador no se pueden modificar.")
        if role is not None and role.code == catalog.PENDING and permissions:
            raise ValidationError("Las cuentas pendientes no pueden tener permisos.")

        codes = {p.code for p in permissions}
        missing_view = sorted(
            f"{p.module}.ver"
            for p in permissions
            if p.code != f"{p.module}.ver" and f"{p.module}.ver" not in codes
        )
        if missing_view:
            raise ValidationError(
                f"Para registrar o modificar en un módulo hay que poder verlo: falta {missing_view[0]}."
            )

        if not _is_admin(actor):
            if role is not None and role.code == actor.role_id:
                raise PermissionDenied("No puedes cambiar los permisos de tu propio rol.")
            current = set(role.permissions.values_list("code", flat=True)) if role else set()
            touched = codes ^ current
            if any(code.startswith("seguridad.") for code in touched):
                raise PermissionDenied("Solo un Administrador puede dar o quitar permisos de Seguridad.")
        return permissions

    def create(self, validated_data):
        permissions = validated_data.pop("permissions", [])
        role = Role.objects.create(**validated_data)
        role.permissions.set(permissions, through_defaults={"granted_by": self.context["request"].user})
        role.users_count = 0
        return role

    def update(self, role, validated_data):
        permissions = validated_data.pop("permissions", None)
        validated_data.pop("code", None)
        for attr, value in validated_data.items():
            setattr(role, attr, value)
        role.save()
        if permissions is not None:
            role.permissions.set(permissions, through_defaults={"granted_by": self.context["request"].user})
        return role


# Recuperación de contraseña


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetTokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class PasswordResetConfirmSerializer(PasswordResetTokenSerializer):
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        validate_passwords_match(attrs["password"], attrs["password_confirm"])
        return attrs
