"""`manage.py init_player_dev` —— 给**离线**的 SQLite 玩家库造一份样例数据。

存在的理由：`PLATFORM_DB_ENGINE=sqlite` 这条路径按 README 的说明，
是为了在没有 MySQL 的机器上把平台跑通。玩家管理需要玩家库里的 `t_users`，
而 SQLite 玩家库是空的、也没有迁移（管理平台在玩家库里没有任何模型），
所以给一条显式的建表 + 塞样例数据的命令。

**只用于本机开发**：

* 只允许跑在 `sqlite` 玩家库上（MySQL 玩家库一律拒绝，避免误碰真实数据）；
* 写的是一张独立的 `t_users`，不碰 `t_accounts`；
* 不参与任何生产流程，也不被 `migrate` 调用。

用法::

    PLATFORM_PLAYER_DB_ENGINE=sqlite ../.venv/bin/python manage.py init_player_dev
    PLATFORM_PLAYER_DB_ENGINE=sqlite ../.venv/bin/python manage.py init_player_dev --reset
"""

from __future__ import annotations

import base64
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.players import player_source

#: 离线样例：账号后缀 / 昵称 / 金币 / 房卡。数据刻意有差异，方便看排序与筛选。
SAMPLE_PLAYERS: tuple[tuple[str, str, int, int], ...] = (
    ("guest_demo1", "示范玩家一", 1000, 21),
    ("guest_demo2", "示范玩家二", 2500, 8),
    ("guest_demo3", "示范玩家三", 300, 0),
    ("guest_demo4", "示范玩家四", 8800, 66),
    ("guest_demo5", "示范玩家五", 1000, 3),
    ("guest_demo6", "示范玩家六", 1500, 12),
)

#: SQLite 版 `t_users`（列与 `server/sql/db_babykylin.sql` 对齐）。
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS t_users (
    userid  INTEGER PRIMARY KEY,
    account TEXT    NOT NULL DEFAULT '',
    name    TEXT,
    sex     INTEGER DEFAULT 0,
    headimg TEXT,
    lv      INTEGER DEFAULT 1,
    exp     INTEGER DEFAULT 0,
    coins   INTEGER DEFAULT 0,
    gems    INTEGER DEFAULT 0,
    roomid  TEXT,
    history TEXT    NOT NULL DEFAULT ''
)
"""


class Command(BaseCommand):
    """在 SQLite 玩家库上建 `t_users` 并写入样例玩家。"""

    help = "为离线 SQLite 玩家库建 t_users 并写入样例玩家（仅本机开发用）"

    def add_arguments(self, parser: Any) -> None:
        """声明命令行参数。"""
        parser.add_argument("--reset", action="store_true", help="先清空 t_users 再写入")

    def handle(self, *args: Any, **options: Any) -> str:
        """建表并写入样例数据。"""
        connection = connections[player_source.PLAYER_DB_ALIAS]
        if connection.vendor != "sqlite":
            raise CommandError(
                "本命令只给 SQLite 玩家库造样例数据；"
                f"当前玩家库是 {connection.vendor}。"
                "真实 MySQL 玩家库不需要（也不允许）由本命令写入。"
            )

        with connection.cursor() as cursor:
            cursor.execute(CREATE_TABLE_SQL)
            if options["reset"]:
                cursor.execute("DELETE FROM t_users")

            rows = [
                (
                    index + 1001,
                    account,
                    base64.b64encode(name.encode("utf-8")).decode("ascii"),
                    0,
                    None,
                    1,
                    0,
                    coins,
                    gems,
                    None,
                    "",
                )
                for index, (account, name, coins, gems) in enumerate(SAMPLE_PLAYERS)
            ]
            cursor.executemany(
                "INSERT OR REPLACE INTO t_users"
                " (userid, account, name, sex, headimg, lv, exp, coins, gems, roomid, history)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            cursor.execute("SELECT COUNT(*) FROM t_users")
            total = cursor.fetchone()[0]

        self.stdout.write(
            self.style.SUCCESS(f"已写入样例玩家 {len(rows)} 个（当前 t_users 共 {total} 行）")
        )
        self.stdout.write("提示：这是本机开发数据，生产环境不要执行本命令。")
        return "ok"
