"""把 `AdminUser` 注册到 Django 自带的 admin 站点。

这只是**运维兜底**用的数据库管理界面（`/admin/`），不是本平台的前端。
平台自己的登录页在 `admin-platform/`，走 `/api/auth/login/`。

注意：这里的登录走的是 Django 的 session 认证（超级管理员才能进），
和 JWT 是两套机制，两者都只认 `AdminUser` 表。
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AdminUser


@admin.register(AdminUser)
class AdminUserAdmin(DjangoUserAdmin):
    """管理员的后台管理界面。"""

    list_display = ("username", "nickname", "email", "role", "status", "is_superuser", "last_login")
    list_filter = ("role", "status", "is_superuser", "is_staff", "is_active")
    search_fields = ("username", "nickname", "email")
    ordering = ("-created_at",)
    readonly_fields = ("last_login", "last_login_ip", "created_at", "updated_at", "date_joined")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("资料", {"fields": ("nickname", "email")}),
        ("角色与状态", {"fields": ("role", "status", "remark")}),
        (
            "权限",
            {
                "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                "description": "is_active 由 status 自动同步，不要在业务里单独修改。",
            },
        ),
        ("登录信息", {"fields": ("last_login", "last_login_ip", "date_joined", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "nickname", "email", "role", "password1", "password2"),
            },
        ),
    )
