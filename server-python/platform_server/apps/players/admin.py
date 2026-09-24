"""把 `PlayerBan` 注册到 Django 自带的 admin 站点（运维兜底）。

**只读注册**：封禁 / 解封必须走 `/api/players/<id>/ban/` 这类接口，
那里会写操作人、原因与时间。如果允许在 admin 里手工改一行，
审计链就断了（谁改的、为什么改，都查不到），所以这里关掉增删改。
"""

from __future__ import annotations

from django.contrib import admin

from .models import PlayerBan


@admin.register(PlayerBan)
class PlayerBanAdmin(admin.ModelAdmin):
    """封禁流水的只读视图。"""

    list_display = (
        "id",
        "player_id",
        "account",
        "player_name",
        "action",
        "reason",
        "operator_name",
        "created_at",
        "expires_at",
    )
    list_filter = ("action", "created_at")
    search_fields = ("account", "player_name", "player_id", "operator_name")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request: object) -> bool:
        """禁止在 admin 里新增流水——必须走接口，否则没有操作人与原因。"""
        return False

    def has_change_permission(self, request: object, obj: PlayerBan | None = None) -> bool:
        """禁止修改历史流水（流水是审计记录，不该被改写）。"""
        return False

    def has_delete_permission(self, request: object, obj: PlayerBan | None = None) -> bool:
        """禁止删除流水。"""
        return False
