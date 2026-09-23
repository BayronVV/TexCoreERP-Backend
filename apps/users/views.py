from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model

from apps.core.constants import USERS_MODULE_ROLES
from apps.core.permissions import HasRole
from .serializers import CustomTokenObtainPairSerializer, UserSerializer, RoleUpdateSerializer, UserRegistrationSerializer

User = get_user_model()


class UserRegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class UserListView(generics.ListAPIView):
    """GET /api/users/ — gestión de usuarios y roles (HU 1.4). Solo ADMIN."""

    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [HasRole]
    allowed_roles = USERS_MODULE_ROLES


class RoleUpdateView(generics.UpdateAPIView):
    """PATCH /api/users/<id>/role/ — reasigna el rol de un usuario. Solo ADMIN."""

    queryset = User.objects.all()
    serializer_class = RoleUpdateSerializer
    permission_classes = [HasRole]
    allowed_roles = USERS_MODULE_ROLES
