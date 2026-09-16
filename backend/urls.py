from django.contrib import admin
from django.urls import path
from users.views import CustomTokenObtainPairView, UserListView, RoleUpdateView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/users/', UserListView.as_view(), name='user_list'),
    path('api/users/<int:pk>/role/', RoleUpdateView.as_view(), name='role_update'),
]
