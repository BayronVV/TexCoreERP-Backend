import ipaddress

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view, inline_serializer
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import catalog, password_reset
from .models import ModulePermission, PasswordResetToken, Role
from .serializers import (
    CustomTokenObtainPairSerializer,
    MeSerializer,
    ModulePermissionSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordResetTokenSerializer,
    RoleSerializer,
    UserAdminUpdateSerializer,
    UserCreateSerializer,
    UserRegistrationSerializer,
    UserSerializer,
    other_working_admins,
)
from .validators import validate_password_policy

User = get_user_model()

# Sin PUT: las actualizaciones son parciales.
DETAIL_METHODS = ["get", "patch", "delete", "head", "options"]


def _client_ip(request):
    # La misma IP que usa el throttling (respeta NUM_PROXIES); se descarta si no es válida.
    ip = ScopedRateThrottle().get_ident(request)
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


@extend_schema(
    tags=["auth"], summary="Registrar un usuario nuevo (HU 1.1)",
    description="La cuenta nace con el rol `PENDING` y sin permisos hasta que un Administrador la apruebe.",
)
class UserRegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


@extend_schema(
    tags=["auth"], summary="Iniciar sesión (HU 1.2)",
    description="Devuelve `access` (15 min) y `refresh` (30 min). El correo no distingue mayúsculas. "
    "401 si las credenciales son inválidas o la cuenta está inactiva; 429 si se supera el límite de intentos.",
)
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


@extend_schema(
    tags=["auth"], summary="Renovar el access token",
    description="Entrega un `access` nuevo y un `refresh` nuevo (rotativo). 401 si el usuario ya no está activo o cambió su contraseña.",
)
class CustomTokenRefreshView(TokenRefreshView):
    pass


@extend_schema(tags=["auth"], summary="Usuario de la sesión y sus permisos")
class MeView(generics.RetrieveAPIView):
    """Usuario de la sesión con sus permisos efectivos."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


# Usuarios


@extend_schema_view(
    get=extend_schema(tags=["users"], summary="Listar usuarios",
        parameters=[OpenApiParameter("role", str, description="Código del rol (ADMIN, ALMACENISTA...)")]),
    post=extend_schema(tags=["users"], summary="Crear un usuario con invitación por correo",
        description="Envía un enlace para que la persona defina su contraseña. `email_sent` indica si el correo salió."),
)
class UserListCreateView(generics.ListCreateAPIView):
    required_permissions = {"GET": catalog.USERS_VIEW, "POST": catalog.USERS_MANAGE}

    def get_queryset(self):
        users = User.objects.select_related("role", "requested_area").order_by("-date_joined")
        role = self.request.query_params.get("role")
        return users.filter(role_id=role) if role else users

    def get_serializer_class(self):
        return UserCreateSerializer if self.request.method == "POST" else UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user = serializer.save()
            raw = password_reset.issue_token(user, PasswordResetToken.PURPOSE_INVITE, _client_ip(request))
        sent = password_reset.send_token_email(user, raw, PasswordResetToken.PURPOSE_INVITE)
        data = UserSerializer(user).data
        data["email_sent"] = sent
        return Response(data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(tags=["users"], summary="Consultar un usuario"),
    patch=extend_schema(tags=["users"], summary="Aprobar, cambiar rol o activar/desactivar",
        description="Solo un Administrador asigna roles con permisos de Seguridad (BUG-01). Nadie edita su propio rol."),
    delete=extend_schema(tags=["users"], summary="Eliminar (borrado lógico)",
        description="Siempre debe quedar al menos un Administrador activo."),
)
class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    http_method_names = DETAIL_METHODS
    required_permissions = {
        "GET": catalog.USERS_VIEW,
        "PATCH": catalog.USERS_MANAGE,
        "DELETE": catalog.USERS_MANAGE,
    }
    queryset = User.objects.select_related("role", "requested_area")

    def get_serializer_class(self):
        return UserSerializer if self.request.method == "GET" else UserAdminUpdateSerializer

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        super().update(request, *args, **kwargs)
        return Response(UserSerializer(self.get_object()).data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    def perform_destroy(self, user):
        """Borrado lógico: la cuenta se oculta y queda inactiva, pero la fila persiste."""
        actor = self.request.user
        if user.pk == actor.pk:
            raise ValidationError("No puedes eliminar tu propia cuenta.")
        if user.role_id == catalog.ADMIN:
            if actor.role_id != catalog.ADMIN:
                raise PermissionDenied("Solo un Administrador puede eliminar a otro Administrador.")
            if user.is_active and not other_working_admins(user):
                raise ValidationError("Debe quedar al menos un administrador activo en el sistema.")
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save(update_fields=["is_active", "deleted_at", "updated_at"])


@extend_schema(
    tags=["users"], summary="Reenviar la invitación", request=None,
    responses=inline_serializer("Detalle", {"detail": serializers.CharField()}),
)
class UserResendInviteView(APIView):
    """Reenvía el enlace para definir la contraseña de una cuenta creada por un admin."""

    required_permissions = catalog.USERS_MANAGE

    def post(self, request, pk):
        user = generics.get_object_or_404(User.objects.all(), pk=pk)
        if not user.is_active:
            raise ValidationError("La cuenta está desactivada; actívala antes de reenviar el enlace.")
        if user.has_usable_password():
            raise ValidationError(
                "Esta cuenta ya tiene contraseña. Si la olvidó, puede pedir una nueva desde el login."
            )
        raw = password_reset.issue_token(user, PasswordResetToken.PURPOSE_INVITE, _client_ip(request))
        if not password_reset.send_token_email(user, raw, PasswordResetToken.PURPOSE_INVITE):
            return Response(
                {"detail": "No se pudo enviar el correo. Intenta de nuevo en unos minutos."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"detail": f"Enviamos un enlace de activación a {user.email}."})


# Roles y permisos


def _roles_with_counts():
    return Role.objects.annotate(
        users_count=Count("users", filter=Q(users__deleted_at__isnull=True), distinct=True)
    ).prefetch_related("permissions")


@extend_schema_view(
    get=extend_schema(tags=["roles"], summary="Listar roles con sus permisos y número de usuarios"),
    post=extend_schema(tags=["roles"], summary="Crear un rol propio",
        description="El código es inmutable (mayúsculas, números o guion bajo). Requiere `seguridad.roles`."),
)
class RoleListCreateView(generics.ListCreateAPIView):
    required_permissions = {"GET": catalog.USERS_VIEW, "POST": catalog.ROLES_MANAGE}
    serializer_class = RoleSerializer
    pagination_class = None

    def get_queryset(self):
        return _roles_with_counts()

    def perform_create(self, serializer):
        serializer.save(is_system=False)


@extend_schema_view(
    get=extend_schema(tags=["roles"], summary="Consultar un rol"),
    patch=extend_schema(tags=["roles"], summary="Editar el nombre o los permisos de un rol",
        description="Los permisos de ADMIN y PENDING no se editan. \"Registrar y modificar\" exige también \"Ver\" el módulo."),
    delete=extend_schema(tags=["roles"], summary="Eliminar un rol",
        description="Solo roles que no son base del sistema y sin usuarios asignados."),
)
class RoleDetailView(generics.RetrieveUpdateDestroyAPIView):
    http_method_names = DETAIL_METHODS
    required_permissions = {
        "GET": catalog.USERS_VIEW,
        "PATCH": catalog.ROLES_MANAGE,
        "DELETE": catalog.ROLES_MANAGE,
    }
    serializer_class = RoleSerializer

    def get_queryset(self):
        return _roles_with_counts()

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        super().update(request, *args, **kwargs)
        return Response(self.get_serializer(self.get_object()).data)

    def perform_destroy(self, role):
        if role.is_system:
            raise ValidationError("Los roles base del sistema no se pueden eliminar.")
        if role.users_count:
            raise ValidationError("Reasigna los usuarios de este rol antes de eliminarlo.")
        role.delete()


@extend_schema(tags=["roles"], summary="Catálogo de permisos por módulo")
class ModulePermissionListView(generics.ListAPIView):
    required_permissions = catalog.USERS_VIEW
    serializer_class = ModulePermissionSerializer
    queryset = ModulePermission.objects.all()
    pagination_class = None


# Recuperación de contraseña

GENERIC_RESET_MESSAGE = (
    "Si el correo pertenece a una cuenta activa, te enviamos un enlace para restablecer la contraseña."
)
INVALID_LINK_MESSAGE = "El enlace no es válido o ya venció. Solicita uno nuevo."


@extend_schema(
    tags=["auth"], summary="Pedir enlace para restablecer la contraseña (HU 1.3)",
    request=PasswordResetRequestSerializer,
    responses=inline_serializer("RecuperacionSolicitada", {
        "detail": serializers.CharField(), "expires_minutes": serializers.IntegerField()}),
)
class PasswordResetRequestView(APIView):
    """Responde lo mismo exista o no el correo (y aunque falle el envío), para no
    revelar qué cuentas existen."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(email__iexact=serializer.validated_data["email"], is_active=True).first()
        if user and password_reset.can_request_reset(user):
            raw = password_reset.issue_token(user, ip=_client_ip(request))
            password_reset.send_token_email(user, raw, PasswordResetToken.PURPOSE_RESET)
        return Response(
            {"detail": GENERIC_RESET_MESSAGE, "expires_minutes": settings.PASSWORD_RESET_TOKEN_MINUTES}
        )


@extend_schema(
    tags=["auth"], summary="Comprobar si un enlace sigue vigente",
    request=PasswordResetTokenSerializer,
    responses=inline_serializer("EnlaceValido", {
        "valid": serializers.BooleanField(), "purpose": serializers.CharField(),
        "email": serializers.EmailField()}),
)
class PasswordResetValidateView(APIView):
    """Permite al frontend avisar antes de que el usuario escriba, si el enlace ya no sirve.
    Es POST para que el token no quede en los logs de acceso."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_check"

    def post(self, request):
        serializer = PasswordResetTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = password_reset.find_usable_token(serializer.validated_data["token"])
        if token is None:
            return Response(
                {"valid": False, "detail": INVALID_LINK_MESSAGE}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response({"valid": True, "purpose": token.purpose, "email": token.user.email})


@extend_schema(
    tags=["auth"], summary="Definir la nueva contraseña con el enlace",
    request=PasswordResetConfirmSerializer,
    responses=inline_serializer("ContrasenaActualizada", {"detail": serializers.CharField()}),
)
class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_check"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            token = password_reset.find_usable_token(serializer.validated_data["token"], lock=True)
            if token is None:
                raise ValidationError({"token": INVALID_LINK_MESSAGE})
            validate_password_policy(serializer.validated_data["password"], token.user)
            password_reset.consume_token(token, serializer.validated_data["password"])
        return Response({"detail": "Tu contraseña se actualizó. Ya puedes iniciar sesión."})
