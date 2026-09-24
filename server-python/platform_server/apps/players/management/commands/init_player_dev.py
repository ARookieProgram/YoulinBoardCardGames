"""`manage.py init_player_dev` —— 给**离线**的 SQLite 玩家库造一份样例数据。

存在的理由：`PLATFORM_DB_ENGINE=sqlite` 这条路径按 README 的说明，
是为了在没有 MySQL 的机器上把平台跑通。玩家管理要 `t_users`、房间管理要 `t_rooms`、
对局记录要 `t_games` / `t_games_archive`，而 SQLite 玩家库是空的、也没有迁移
（管理平台在玩家库里没有任何模型），所以给一条显式的建表 + 塞样例数据的命令。

**只用于本机开发**：

* 只允许跑在 `sqlite` 玩家库上（MySQL 玩家库一律拒绝，避免误碰真实数据）；
* 只建/写玩家库里的 `t_users` / `t_rooms` / `t_games` / `t_games_archive`，
  不碰 `t_accounts`；
* 不参与任何生产流程，也不被 `migrate` 调用。

样例刻意覆盖对局记录的**三种玩家身份来源**（见 `apps/players/player_source.py`）：

======================  ==========================  ==============================
房间                    样例内容                     身份来源
======================  ==========================  ==============================
``526035``（未销毁）     在局 1 局（`t_games`）        `t_rooms` 座位列 → `rooms`
``641280``（已销毁）     归档 3 局 + 战绩快照          `t_users.history` → `history`
``593071``（已销毁）     归档 1 局、**不写**战绩快照    查不到 → `unknown`
======================  ==========================  ==============================

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

from apps.games import decoding
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

#: 离线样例房间（**尚未销毁**的那两个）：房间号 / 玩法 / 底分 / 局数上限 / 已打局数 /
#: 房主账号 / 四个座位上的账号（空串 = 空座）。
#: 刻意造出"满座在打"与"未满座等玩家"两种状态，好把列表的状态过滤试出来。
SAMPLE_ROOMS: tuple[tuple[str, str, int, int, int, str, tuple[str, str, str, str]], ...] = (
    ("526035", "xzdd", 1, 4, 2, "guest_demo1", ("guest_demo1", "guest_demo2", "guest_demo3", "guest_demo4")),
    ("730112", "xlch", 2, 8, 0, "guest_demo5", ("guest_demo5", "guest_demo6", "", "")),
)

#: 已销毁房间的样例对局：房间号 / 玩法 / 底分 / 局数上限 / 房主账号 / 四个座位 /
#: 归档局数 / 是否写 `t_users.history` 战绩快照（不写就查不到玩家身份）。
SAMPLE_ARCHIVED_ROOMS: tuple[
    tuple[str, str, int, int, str, tuple[str, str, str, str], int, bool], ...
] = (
    (
        "641280",
        "xzdd",
        1,
        4,
        "guest_demo1",
        ("guest_demo1", "guest_demo2", "guest_demo3", "guest_demo4"),
        3,
        True,
    ),
    (
        "593071",
        "xlch",
        2,
        8,
        "guest_demo5",
        ("guest_demo5", "guest_demo6", "guest_demo1", "guest_demo2"),
        1,
        False,
    ),
)

#: 样例 uuid 的前缀（13 位毫秒时间戳 + 6 位房间号 = 19 位，与游戏服的生成口径一致）。
SAMPLE_UUID_PREFIX = "1760000000000"

#: 样例对局的出牌流水（三元组：座位 / 动作 / 牌）。
#:
#: **这不是一局真实的牌**，只是把六种动作（出牌 / 摸牌 / 碰 / 杠 / 胡 / 自摸）
#: 各造一次，好让后台的"出牌记录"时间线、被碰标注、座位统计都有东西可看。
#: 牌 id 的口径见 `apps/games/decoding.py`（0~8 筒 / 9~17 条 / 18~26 万）。
SAMPLE_ACTIONS: tuple[int, ...] = (
    0, decoding.ACTION_CHUPAI, 0,  # 座位0 打出 一筒
    1, decoding.ACTION_MOPAI, 9,  # 座位1 摸到 一条
    1, decoding.ACTION_CHUPAI, 1,  # 座位1 打出 二筒
    2, decoding.ACTION_PENG, 1,  # 座位2 碰 二筒
    2, decoding.ACTION_CHUPAI, 18,  # 座位2 打出 一万
    3, decoding.ACTION_MOPAI, 3,  # 座位3 摸到 四筒
    3, decoding.ACTION_GANG, 3,  # 座位3 杠 四筒
    3, decoding.ACTION_CHUPAI, 20,  # 座位3 打出 三万
    0, decoding.ACTION_MOPAI, 8,  # 座位0 摸到 九筒
    0, decoding.ACTION_ZIMO, 8,  # 座位0 自摸 九筒
    1, decoding.ACTION_HU, 0,  # 座位1 胡 一筒
)

#: 样例单局得分（四个座位，和为 0，与游戏服的结算口径一致）。
SAMPLE_RESULT: tuple[int, int, int, int] = (10, -6, -2, -2)

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

#: SQLite 版 `t_games` / `t_games_archive`（两张表结构完全相同）。
CREATE_GAME_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    room_uuid      CHAR(20) NOT NULL,
    game_index     INTEGER  NOT NULL,
    base_info      TEXT     NOT NULL,
    create_time    INTEGER  NOT NULL,
    snapshots      TEXT,
    action_records TEXT,
    result         TEXT,
    PRIMARY KEY (room_uuid, game_index)
)
"""

#: 建表语句的表名（顺序固定，`--reset` 与统计都按它来）。
GAME_TABLES: tuple[str, ...] = (player_source.GAME_LIVE_TABLE, player_source.GAME_ARCHIVE_TABLE)


def _b64(value: str) -> str:
    """按游戏服的入库口径把昵称编码成 Base64。"""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _sample_wall() -> list[int]:
    """造一副"洗好的牌墙"：`0,0,0,0,1,1,1,1,...,26,26,26,26`。"""
    return [tile for tile in range(decoding.TILE_MAX + 1) for _ in range(decoding.TILES_PER_KIND)]


def _base_info(wall: list[int], room_type: str, game_index: int, button: int) -> str:
    """拼 `t_games.base_info`：开局快照（牌墙 + 四家起手牌）。

    起手牌按真实发牌口径取牌墙前 53 张（庄家 14 张、其余三家各 13 张），
    这样后台算出来的"牌墙剩余"是对的。
    """
    hands: list[list[int]] = [[], [], [], []]
    for index in range(53):
        hands[index % 4].append(wall[index])
    payload = {
        "type": room_type,
        "button": button,
        "index": game_index,
        "mahjongs": wall,
        "game_seats": hands,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _action_records() -> str:
    """拼 `t_games.action_records`（紧凑 JSON 数组）。"""
    return json.dumps(list(SAMPLE_ACTIONS), separators=(",", ":"))


def _result(offset: int) -> str:
    """拼 `t_games.result`；带一点偏移，免得所有样例局的分完全一样。"""
    scores = [score + (offset if index == 0 else -offset) for index, score in enumerate(SAMPLE_RESULT)]
    return json.dumps(scores, separators=(",", ":"))


class Command(BaseCommand):
    """在 SQLite 玩家库上建 `t_users` / `t_rooms` / `t_games` / `t_games_archive` 并写入样例数据。"""

    help = "为离线 SQLite 玩家库建玩家/房间/对局表并写入样例数据（仅本机开发用）"

    def add_arguments(self, parser: Any) -> None:
        """声明命令行参数。"""
        parser.add_argument(
            "--reset", action="store_true", help="先清空 t_users / t_rooms / t_games 再写入"
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
            for table in GAME_TABLES:
                cursor.execute(CREATE_GAME_TABLE_SQL.format(table=table))
            if options["reset"]:
                cursor.execute("DELETE FROM t_users")
                cursor.execute("DELETE FROM t_rooms")
                for table in GAME_TABLES:
                    cursor.execute(f"DELETE FROM {table}")

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
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                " VALUES (%s, %s, %s, %s, %s, 0,"
                "  %s, '', %s, %s, %s, '', %s, %s, %s, '', %s, %s, %s, '', %s, %s,"
                "  '127.0.0.1', 10000)",
                room_rows,
            )

            # 1) 未销毁房间的"在局"对局记录（t_games）。
            live_rows = self._live_game_rows(rooms=SAMPLE_ROOMS, players=players, now=now)
            self._insert_games(cursor, player_source.GAME_LIVE_TABLE, live_rows)

            # 2) 已销毁房间的归档对局 + 战绩快照（t_users.history）。
            archived_rows, history_updates = self._archived_game_rows(players=players, now=now)
            self._insert_games(cursor, player_source.GAME_ARCHIVE_TABLE, archived_rows)
            for userid, history in history_updates:
                cursor.execute(
                    "UPDATE t_users SET history = %s WHERE userid = %s",
                    (json.dumps(history, separators=(",", ":"), ensure_ascii=False), userid),
                )

            cursor.execute("SELECT COUNT(*) FROM t_users")
            player_total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM t_rooms")
            room_total = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM {player_source.GAME_LIVE_TABLE}")
            live_total = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM {player_source.GAME_ARCHIVE_TABLE}")
            archive_total = cursor.fetchone()[0]

        self.stdout.write(
            self.style.SUCCESS(
                f"已写入样例玩家 {len(player_rows)} 个（t_users 共 {player_total} 行）、"
                f"样例房间 {len(room_rows)} 个（t_rooms 共 {room_total} 行）、"
                f"对局 {live_total + archive_total} 局"
                f"（t_games {live_total} 行 / t_games_archive {archive_total} 行）"
            )
        )
        self.stdout.write("提示：这是本机开发数据，生产环境不要执行本命令。")
        return "ok"

    # ------------------------------------------------------------ 内部工具

    @staticmethod
    def _insert_games(cursor: Any, table: str, rows: list[tuple[Any, ...]]) -> None:
        """批量写对局行。"""
        if not rows:
            return
        cursor.executemany(
            f"INSERT OR REPLACE INTO {table}"
            " (room_uuid, game_index, base_info, create_time, snapshots, action_records, result)"
            " VALUES (%s, %s, %s, %s, NULL, %s, %s)",
            rows,
        )

    def _live_game_rows(
        self,
        *,
        rooms: tuple[tuple[Any, ...], ...],
        players: dict[str, tuple[int, str]],
        now: int,
    ) -> list[tuple[Any, ...]]:
        """未销毁房间里"已在局"的对局行（局数与 `t_rooms.num_of_turns` 对齐）。"""
        rows: list[tuple[Any, ...]] = []
        for index, room in enumerate(rooms):
            room_id, room_type, _base_score, _max_games, num_of_turns, _creator, _seats = room
            # 还没开打的房间不会有对局记录——这正是"14001 查不到"的常见原因。
            for game_index in range(max(int(num_of_turns), 0)):
                rows.append(
                    self._game_row(
                        room_id=room_id,
                        room_type=room_type,
                        game_index=game_index,
                        create_time=now - (index + 1) * 300 + game_index * 240,
                        button=game_index % player_source.ROOM_SEAT_COUNT,
                        score_offset=game_index,
                    )
                )
        return rows

    def _archived_game_rows(
        self,
        *,
        players: dict[str, tuple[int, str]],
        now: int,
    ) -> tuple[list[tuple[Any, ...]], list[tuple[int, list[dict[str, Any]]]]]:
        """已销毁房间的归档对局 + 需要写回 `t_users.history` 的战绩快照。"""
        rows: list[tuple[Any, ...]] = []
        history_updates: list[tuple[int, list[dict[str, Any]]]] = []
        for index, room in enumerate(SAMPLE_ARCHIVED_ROOMS):
            (
                room_id,
                room_type,
                _base_score,
                _max_games,
                _creator,
                seats,
                game_count,
                write_history,
            ) = room
            room_uuid = SAMPLE_UUID_PREFIX + room_id
            create_time = now - (index + 2) * 3600
            for game_index in range(game_count):
                rows.append(
                    self._game_row(
                        room_id=room_id,
                        room_type=room_type,
                        game_index=game_index,
                        create_time=create_time + game_index * 240,
                        # 庄家每局轮换，好把"谁是庄"在每一局里都试出来。
                        button=game_index % player_source.ROOM_SEAT_COUNT,
                        score_offset=game_index,
                    )
                )
            if not write_history:
                # 只在 `numOfGames > 1` 时游戏服才写战绩快照，所以"打了一局就散场"
                # 的房间在库里查不到玩家身份——样例刻意保留这种房间（见模块文档）。
                continue
            history = self._history_entry(
                room_id=room_id,
                room_uuid=room_uuid,
                create_time=create_time,
                seats=seats,
                players=players,
            )
            for account in seats:
                userid, _name = players.get(account, (0, ""))
                if userid:
                    history_updates.append((userid, [history]))
        return rows, history_updates

    def _game_row(
        self,
        *,
        room_id: str,
        room_type: str,
        game_index: int,
        create_time: int,
        button: int,
        score_offset: int = 0,
    ) -> tuple[Any, ...]:
        """拼一行 `t_games` / `t_games_archive` 的 INSERT 参数。"""
        wall = _sample_wall()
        return (
            SAMPLE_UUID_PREFIX + room_id,
            game_index,
            _base_info(wall, room_type, game_index, button),
            create_time,
            _action_records(),
            _result(score_offset),
        )

    @staticmethod
    def _history_entry(
        *,
        room_id: str,
        room_uuid: str,
        create_time: int,
        seats: tuple[str, str, str, str],
        players: dict[str, tuple[int, str]],
    ) -> dict[str, Any]:
        """拼一条 `t_users.history` 的战绩（口径见 `gamemgr.store_history`）。"""
        seat_entries: list[dict[str, Any]] = []
        for index, account in enumerate(seats):
            userid, name = players.get(account, (0, ""))
            seat_entries.append(
                {
                    "userid": userid,
                    "name": _b64(name) if name else "",
                    "score": (2 - index) * 10,
                }
            )
        return {
            "uuid": room_uuid,
            "id": room_id,
            "time": create_time,
            "seats": seat_entries,
        }

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
