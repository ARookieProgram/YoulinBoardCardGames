"""`accounts` 应用路由。

挂在 `/api/auth/` 下，与玩家侧的 HTTP 路由（账号服 `/login`、`/guest` 等）
没有任何前缀重叠。
"""

from __future__ import annotations

from django.urls import path

from .views import CurrentAdminView, LoginView, LogoutView, RefreshTokenView

app_name = "accounts"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshTokenView.as_view(), name="refresh"),
    path("me/", CurrentAdminView.as_view(), name="me"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
