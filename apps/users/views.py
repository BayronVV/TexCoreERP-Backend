import ipaddress

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

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


class UserRegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class MeView(generics.RetrieveAPIView):
    """Usuario de la sesión con sus permisos efectivos."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


# Usuarios


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


class RoleListCreateView(generics.ListCreateAPIView):
    required_permissions = {"GET": catalog.USERS_VIEW, "POST": catalog.ROLES_MANAGE}
    serializer_class = RoleSerializer
    pagination_class = None

    def get_queryset(self):
        return _roles_with_counts()

    def perform_create(self, serializer):
        serializer.save(is_system=False)


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
