"""权限类：管理平台的角色校验。

用法：在 DRF 视图上挂 `permission_classes = [IsAuthenticated, IsAdminOrAbove]`。

约定：这些类只做**角色**判断，"是否登录"交给 DRF 的 `IsAuthenticated`，
这样未登录与无权限会拿到不同的错误码（10002 vs 10003），前端才能区分
"跳登录页"和"弹无权限提示"。
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .models import AdminUser


def _current_admin(request: Request) -> AdminUser | None:
    """取出当前请求的管理员；不是管理员会话时返回 `None`。"""
    user = getattr(request, "user", None)
    if isinstance(user, AdminUser) and user.is_enabled:
        return user
    return None


class IsPlatformAdmin(BasePermission):
    """任意**启用中**的管理员。"""

    message = "需要管理员身份"

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _current_admin(request) is not None


class IsAdminOrAbove(BasePermission):
    """管理员及以上（`admin` / `super_admin`）。"""

    message = "需要管理员及以上权限"

    def has_permission(self, request: Request, view: APIView) -> bool:
        admin = _current_admin(request)
        return admin is not None and admin.has_role_at_least(AdminUser.Role.ADMIN)


class IsSuperAdmin(BasePermission):
    """仅超级管理员。"""

    message = "需要超级管理员权限"

    def has_permission(self, request: Request, view: APIView) -> bool:
        admin = _current_admin(request)
        return admin is not None and admin.has_role_at_least(AdminUser.Role.SUPER_ADMIN)


class HasRoleAtLeast(BasePermission):
    """按视图上的 `required_role` 动态判断角色下限。

    视图里写：

        class FooView(APIView):
            permission_classes = [IsAuthenticated, HasRoleAtLeast]
            required_role = AdminUser.Role.ADMIN
    """

    message = "权限不足"

    def has_permission(self, request: Request, view: APIView) -> bool:
        admin = _current_admin(request)
        if admin is None:
            return False
        required = getattr(view, "required_role", AdminUser.Role.OPERATOR)
        return admin.has_role_at_least(required)
