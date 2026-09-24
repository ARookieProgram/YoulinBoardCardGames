"""`games` 应用的 AppConfig。

本应用**没有模型**（对局数据在玩家库的 `t_games` / `t_games_archive` 里，只读），
注册进 `INSTALLED_APPS` 是为了统一目录约定、让 `manage.py` 的命令能发现它。

因为没有任何模型，所以**不需要**把它加进 `scripts/gen_sql.py` 的
`PLATFORM_APP_LABELS`（那里是给建库脚本的 schema 速查用的，本应用没有表）。
"""

from __future__ import annotations

from django.apps import AppConfig


class GamesConfig(AppConfig):
    """对局记录（只读监控玩家库的 `t_games` / `t_games_archive`）。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.games"
    label = "games"
    verbose_name = "对局记录"
