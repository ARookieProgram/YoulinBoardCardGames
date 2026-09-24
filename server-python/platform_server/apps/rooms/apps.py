"""`rooms` 应用的 AppConfig。

本应用**没有模型**（房间数据在玩家库里，只读），注册进 `INSTALLED_APPS` 是为了
统一目录约定、让 `manage.py` 的命令能发现它，也为将来可能出现的平台侧配置留位置。

因为没有任何模型，所以**不需要**把它加进 `scripts/gen_sql.py` 的
`PLATFORM_APP_LABELS`（那里是给建库脚本的 schema 速查用的，本应用没有表）。
"""

from __future__ import annotations

from django.apps import AppConfig


class RoomsConfig(AppConfig):
    """房间管理（只读监控玩家库 `t_rooms`）。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rooms"
    label = "rooms"
    verbose_name = "房间管理"
