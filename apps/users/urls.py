from django.urls import path
from apps.users.views import CustomTokenObtainPairView, UserListView, RoleUpdateView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/<int:pk>/role/', RoleUpdateView.as_view(), name='role_update'),
]
