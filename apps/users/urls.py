from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    # Autenticación
    path("register/", views.UserRegisterView.as_view(), name="user_register"),
    path("token/", views.CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    # Recuperación de contraseña (HU 1.3)
    path("auth/password-reset/", views.PasswordResetRequestView.as_view(), name="password_reset"),
    path(
        "auth/password-reset/validate/",
        views.PasswordResetValidateView.as_view(),
        name="password_reset_validate",
    ),
    path(
        "auth/password-reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    # Usuarios, roles y permisos (HU 1.4)
    path("users/", views.UserListCreateView.as_view(), name="user_list"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/invite/", views.UserResendInviteView.as_view(), name="user_invite"),
    path("roles/", views.RoleListCreateView.as_view(), name="role_list"),
    path("roles/<int:pk>/", views.RoleDetailView.as_view(), name="role_detail"),
    path("permissions/", views.ModulePermissionListView.as_view(), name="permission_list"),
]
