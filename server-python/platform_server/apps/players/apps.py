"""`players` 应用的 AppConfig。"""

from __future__ import annotations

from django.apps import AppConfig


class PlayersConfig(AppConfig):
    """玩家管理（只读玩家库 + 本平台的封禁记录）。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.players"
    label = "players"
    verbose_name = "玩家管理"
