"""`manage.py init_player_dev` —— 给**离线**的 SQLite 玩家库造一份样例数据。

存在的理由：`PLATFORM_DB_ENGINE=sqlite` 这条路径按 README 的说明，
是为了在没有 MySQL 的机器上把平台跑通。玩家管理要 `t_users`、房间管理要 `t_rooms`，
而 SQLite 玩家库是空的、也没有迁移（管理平台在玩家库里没有任何模型），
所以给一条显式的建表 + 塞样例数据的命令。

**只用于本机开发**：

* 只允许跑在 `sqlite` 玩家库上（MySQL 玩家库一律拒绝，避免误碰真实数据）；
* 只建/写玩家库里的 `t_users` 与 `t_rooms`，不碰 `t_accounts`；
* 不参与任何生产流程，也不被 `migrate` 调用。

用法::

    PLATFORM_PLAYER_DB_ENGINE=sqlite ../.venv/bin/python manage.py init_player_dev
    PLATFORM_PLAYER_DB_ENGINE=sqlite ../.venv/bin/python manage.py init_player_dev --reset
"""

from __future__ import annotations

import base64
import json
import time
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

#: 离线样例房间：房间号 / 玩法 / 底分 / 局数上限 / 已打局数 / 房主账号 / 四个座位上的账号
#: （空串 = 空座）。
#: 刻意造出"满座在打"与"未满座等玩家"两种状态，好把列表的状态过滤试出来。
SAMPLE_ROOMS: tuple[tuple[str, str, int, int, int, str, tuple[str, str, str, str]], ...] = (
    ("526035", "xzdd", 1, 4, 2, "guest_demo1", ("guest_demo1", "guest_demo2", "guest_demo3", "guest_demo4")),
    ("730112", "xlch", 2, 8, 0, "guest_demo5", ("guest_demo5", "guest_demo6", "", "")),
)

#: 样例 uuid 的前缀（13 位毫秒时间戳 + 6 位房间号 = 19 位，与游戏服的生成口径一致）。
SAMPLE_UUID_PREFIX = "1760000000000"

#: SQLite 版 `t_users`（列与 `server/sql/db_babykylin.sql` 对齐）。
CREATE_PLAYER_TABLE_SQL = """
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

#: SQLite 版 `t_rooms`（列与 `server/sql/db_babykylin.sql` 对齐：四个座位是宽表列）。
CREATE_ROOM_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS t_rooms (
    uuid          CHAR(20) NOT NULL,
    id            CHAR(8)  NOT NULL,
    base_info     TEXT     NOT NULL DEFAULT '0',
    create_time   INTEGER  NOT NULL,
    num_of_turns  INTEGER  NOT NULL DEFAULT 0,
    next_button   INTEGER  NOT NULL DEFAULT 0,
    user_id0      INTEGER  NOT NULL DEFAULT 0,
    user_icon0    TEXT     NOT NULL DEFAULT '',
    user_name0    TEXT     NOT NULL DEFAULT '',
    user_score0   INTEGER  NOT NULL DEFAULT 0,
    user_id1      INTEGER  NOT NULL DEFAULT 0,
    user_icon1    TEXT     NOT NULL DEFAULT '',
    user_name1    TEXT     NOT NULL DEFAULT '',
    user_score1   INTEGER  NOT NULL DEFAULT 0,
    user_id2      INTEGER  NOT NULL DEFAULT 0,
    user_icon2    TEXT     NOT NULL DEFAULT '',
    user_name2    TEXT     NOT NULL DEFAULT '',
    user_score2   INTEGER  NOT NULL DEFAULT 0,
    user_id3      INTEGER  NOT NULL DEFAULT 0,
    user_icon3    TEXT     NOT NULL DEFAULT '',
    user_name3    TEXT     NOT NULL DEFAULT '',
    user_score3   INTEGER  NOT NULL DEFAULT 0,
    ip            TEXT,
    port          INTEGER DEFAULT 0,
    PRIMARY KEY (uuid),
    UNIQUE (id)
)
"""


def _b64(value: str) -> str:
    """按游戏服的入库口径把昵称编码成 Base64。"""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


class Command(BaseCommand):
    """在 SQLite 玩家库上建 `t_users` / `t_rooms` 并写入样例数据。"""

    help = "为离线 SQLite 玩家库建 t_users / t_rooms 并写入样例数据（仅本机开发用）"

    def add_arguments(self, parser: Any) -> None:
        """声明命令行参数。"""
        parser.add_argument(
            "--reset", action="store_true", help="先清空 t_users / t_rooms 再写入"
        )

    def handle(self, *args: Any, **options: Any) -> str:
        """建表并写入样例数据。"""
        connection = connections[player_source.PLAYER_DB_ALIAS]
        if connection.vendor != "sqlite":
            raise CommandError(
                "本命令只给 SQLite 玩家库造样例数据；"
                f"当前玩家库是 {connection.vendor}。"
                "真实 MySQL 玩家库不需要（也不允许）由本命令写入。"
            )

        players: dict[str, tuple[int, str]] = {}
        with connection.cursor() as cursor:
            cursor.execute(CREATE_PLAYER_TABLE_SQL)
            cursor.execute(CREATE_ROOM_TABLE_SQL)
            if options["reset"]:
                cursor.execute("DELETE FROM t_users")
                cursor.execute("DELETE FROM t_rooms")

            player_rows = []
            for index, (account, name, coins, gems) in enumerate(SAMPLE_PLAYERS):
                userid = index + 1001
                players[account] = (userid, name)
                player_rows.append(
                    (userid, account, _b64(name), 0, None, 1, 0, coins, gems, None, "")
                )
            cursor.executemany(
                "INSERT OR REPLACE INTO t_users"
                " (userid, account, name, sex, headimg, lv, exp, coins, gems, roomid, history)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                player_rows,
            )

            now = int(time.time())
            room_rows = [
                self._room_row(
                    room_id=room_id,
                    room_type=room_type,
                    base_score=base_score,
                    max_games=max_games,
                    num_of_turns=num_of_turns,
                    creator=creator,
                    seats=seats,
                    # 第一个房间"刚开 10 分钟"，第二个"昨天开的"，让概览的
                    # "最近 24 小时新建"有区分度。
                    create_time=now - (600 if index == 0 else 26 * 3600),
                    players=players,
                )
                for index, (
                    room_id,
                    room_type,
                    base_score,
                    max_games,
                    num_of_turns,
                    creator,
                    seats,
                ) in enumerate(SAMPLE_ROOMS)
            ]
            cursor.executemany(
                "INSERT OR REPLACE INTO t_rooms"
                " (uuid, id, base_info, create_time, num_of_turns, next_button,"
                "  user_id0, user_icon0, user_name0, user_score0,"
                "  user_id1, user_icon1, user_name1, user_score1,"
                "  user_id2, user_icon2, user_name2, user_score2,"
                "  user_id3, user_icon3, user_name3, user_score3,"
                "  ip, port)"
                " VALUES (?, ?, ?, ?, ?, 0,"
                "  ?, '', ?, ?, ?, '', ?, ?, ?, '', ?, ?, ?, '', ?, ?, '127.0.0.1', 10000)",
                room_rows,
            )

            cursor.execute("SELECT COUNT(*) FROM t_users")
            player_total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM t_rooms")
            room_total = cursor.fetchone()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"已写入样例玩家 {len(player_rows)} 个（t_users 共 {player_total} 行）、"
                f"样例房间 {len(room_rows)} 个（t_rooms 共 {room_total} 行）"
            )
        )
        self.stdout.write("提示：这是本机开发数据，生产环境不要执行本命令。")
        return "ok"

    @staticmethod
    def _room_row(
        *,
        room_id: str,
        room_type: str,
        base_score: int,
        max_games: int,
        num_of_turns: int,
        creator: str,
        seats: tuple[str, str, str, str],
        create_time: int,
        players: dict[str, tuple[int, str]],
    ) -> tuple[Any, ...]:
        """拼一行 `t_rooms` 的 INSERT 参数。

        `base_info` 的键序刻意与 `utils/db._conf_to_wire` 一致（`type` 在最前），
        这样房间管理里"按玩法过滤"用的 `LIKE '%"type":"xx"%'` 对样例数据同样成立。
        """
        creator_id = players.get(creator, (0, ""))[0]
        conf = {
            "type": room_type,
            "baseScore": base_score,
            "zimo": 0,
            "jiangdui": False,
            "hsz": False,
            "dianganghua": 0,
            "menqing": False,
            "tiandihu": False,
            "maxFan": 4,
            "maxGames": max_games,
            "creator": creator_id,
        }
        seat_values: list[Any] = []
        for index, account in enumerate(seats):
            userid, name = players.get(account, (0, ""))
            # 已开打的房间给座位一点分差，方便看详情页；空座与未开打都是 0。
            score = (2 - index) * 10 if (userid and num_of_turns > 0) else 0
            # 每座三个占位：user_id / user_name（Base64）/ user_score，
            # user_icon 在 SQL 里固定是空串（样例没有头像）。
            seat_values.extend([userid, _b64(name) if name else "", score])
        return (
            SAMPLE_UUID_PREFIX + room_id,
            room_id,
            json.dumps(conf, separators=(",", ":")),
            create_time,
            num_of_turns,
            *seat_values,
        )
