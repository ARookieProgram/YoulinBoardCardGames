"""对局记录接口测试。

覆盖范围：

* 列表：搜索（房间 uuid / 房间号 / 玩家ID / 玩家昵称）、玩法过滤、来源过滤
  （进行中 / 已结束 / 全部）、日期区间、排序、分页、参数校验；
* 概览：总局数、已结束 / 进行中、最近 24 小时；
* 房间对局：按房间号或 uuid 打开，**三种玩家身份来源**（存活房间 / 历史战绩 / 查不到）
  都要正确标注；不存在时 `14001`；
* 单局详情：**出牌记录**（时间线 + 每个玩家自己的出牌顺序 + 被碰标注）、
  开局手牌、牌墙消耗、脏数据只记警告不报错；
* 玩家对局：来自 `t_users.history`，含"我"的座位 / 得分 / 名次与房间局数；
  玩家不存在时 `12001`；
* **只读隔离**：对局这条路径上执行的每一条 SQL 都必须是 SELECT，
  而且 SQL 只能出现在 `player_source.py` 这一条通道里；
* 离线开发命令 `init_player_dev` 也会给对局记录造样例数据。

对局夹具建在**玩家库别名**（`DATABASES["player"]`）的测试库上：SQLite 下是内存库，
MySQL 下是 `test_db_scmj`，**不会**碰真实的 `db_scmj`。表结构由本文件自己建——
管理平台在玩家库里没有任何模型与迁移，这正是隔离的体现。
"""

from __future__ import annotations

import base64
import json
import unittest
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.db import connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import AdminUser
from apps.games import decoding
from apps.players import player_source
from apps.players.exceptions import PlayerSourceReadOnlyViolation

LIST_URL = "/api/games/"
OVERVIEW_URL = "/api/games/overview/"
ROOMS_URL = "/api/games/rooms/"
PLAYERS_URL = "/api/games/players/"
PLAYER_DB = player_source.PLAYER_DB_ALIAS
PASSWORD = "AdminPass!2024"
SITE_TZ = ZoneInfo("Asia/Shanghai")

#: 建表语句：两种后端各一份（列与 `server/sql/db_babykylin.sql` 对齐）。
CREATE_TABLE_SQL = {
    "sqlite": (
        "CREATE TABLE IF NOT EXISTS {table} ("
        "room_uuid CHAR(20) NOT NULL, game_index INTEGER NOT NULL,"
        "base_info TEXT NOT NULL, create_time INTEGER NOT NULL, snapshots TEXT,"
        "action_records TEXT, result TEXT, PRIMARY KEY (room_uuid, game_index))",
        "CREATE TABLE IF NOT EXISTS t_rooms ("
        "uuid CHAR(20) NOT NULL, id CHAR(8) NOT NULL,"
        "base_info TEXT NOT NULL DEFAULT '0', create_time INTEGER NOT NULL,"
        "num_of_turns INTEGER NOT NULL DEFAULT 0, next_button INTEGER NOT NULL DEFAULT 0,"
        "user_id0 INTEGER NOT NULL DEFAULT 0, user_icon0 TEXT NOT NULL DEFAULT '',"
        "user_name0 TEXT NOT NULL DEFAULT '', user_score0 INTEGER NOT NULL DEFAULT 0,"
        "user_id1 INTEGER NOT NULL DEFAULT 0, user_icon1 TEXT NOT NULL DEFAULT '',"
        "user_name1 TEXT NOT NULL DEFAULT '', user_score1 INTEGER NOT NULL DEFAULT 0,"
        "user_id2 INTEGER NOT NULL DEFAULT 0, user_icon2 TEXT NOT NULL DEFAULT '',"
        "user_name2 TEXT NOT NULL DEFAULT '', user_score2 INTEGER NOT NULL DEFAULT 0,"
        "user_id3 INTEGER NOT NULL DEFAULT 0, user_icon3 TEXT NOT NULL DEFAULT '',"
        "user_name3 TEXT NOT NULL DEFAULT '', user_score3 INTEGER NOT NULL DEFAULT 0,"
        "ip TEXT, port INTEGER DEFAULT 0, PRIMARY KEY (uuid), UNIQUE (id))",
        "CREATE TABLE IF NOT EXISTS t_users ("
        "userid INTEGER PRIMARY KEY, account TEXT NOT NULL DEFAULT '', name TEXT,"
        "sex INTEGER DEFAULT 0, headimg TEXT, lv INTEGER DEFAULT 1, exp INTEGER DEFAULT 0,"
        "coins INTEGER DEFAULT 0, gems INTEGER DEFAULT 0, roomid TEXT,"
        "history TEXT NOT NULL DEFAULT '')",
    ),
    "mysql": (
        "CREATE TABLE IF NOT EXISTS {table} ("
        "room_uuid char(20) NOT NULL, game_index smallint(6) NOT NULL,"
        "base_info varchar(1024) NOT NULL, create_time int(11) NOT NULL,"
        "snapshots char(255) DEFAULT NULL, action_records varchar(2048) DEFAULT NULL,"
        "result char(255) DEFAULT NULL, PRIMARY KEY (room_uuid, game_index))"
        " ENGINE=InnoDB DEFAULT CHARSET=utf8",
        "CREATE TABLE IF NOT EXISTS t_rooms ("
        "uuid char(20) NOT NULL, id char(8) NOT NULL,"
        "base_info varchar(256) NOT NULL DEFAULT '0', create_time int(11) NOT NULL,"
        "num_of_turns int(11) NOT NULL DEFAULT 0, next_button int(11) NOT NULL DEFAULT 0,"
        "user_id0 int(11) NOT NULL DEFAULT 0, user_icon0 varchar(128) NOT NULL DEFAULT '',"
        "user_name0 varchar(32) NOT NULL DEFAULT '', user_score0 int(11) NOT NULL DEFAULT 0,"
        "user_id1 int(11) NOT NULL DEFAULT 0, user_icon1 varchar(128) NOT NULL DEFAULT '',"
        "user_name1 varchar(32) NOT NULL DEFAULT '', user_score1 int(11) NOT NULL DEFAULT 0,"
        "user_id2 int(11) NOT NULL DEFAULT 0, user_icon2 varchar(128) NOT NULL DEFAULT '',"
        "user_name2 varchar(32) NOT NULL DEFAULT '', user_score2 int(11) NOT NULL DEFAULT 0,"
        "user_id3 int(11) NOT NULL DEFAULT 0, user_icon3 varchar(128) NOT NULL DEFAULT '',"
        "user_name3 varchar(32) NOT NULL DEFAULT '', user_score3 int(11) NOT NULL DEFAULT 0,"
        "ip varchar(16) DEFAULT NULL, port int(11) DEFAULT 0,"
        "PRIMARY KEY (uuid), UNIQUE KEY id (id)) ENGINE=InnoDB DEFAULT CHARSET=utf8",
        "CREATE TABLE IF NOT EXISTS t_users ("
        "userid int(11) unsigned NOT NULL, account varchar(64) NOT NULL DEFAULT '',"
        "name varchar(32) DEFAULT NULL, sex int(1) DEFAULT NULL, headimg varchar(256) DEFAULT NULL,"
        "lv smallint(6) DEFAULT 1, exp int(11) DEFAULT 0, coins int(11) DEFAULT 0,"
        "gems int(11) DEFAULT 0, roomid varchar(8) DEFAULT NULL,"
        "history varchar(4096) NOT NULL DEFAULT '', PRIMARY KEY (userid),"
        "UNIQUE KEY account (account)) ENGINE=InnoDB DEFAULT CHARSET=utf8",
    ),
}

GAME_TABLES = (player_source.GAME_LIVE_TABLE, player_source.GAME_ARCHIVE_TABLE)

#: 时间锚点：三个房间刻意落在三个不同的自然日（按 Asia/Shanghai）。
LIVE_CREATE = 1_700_000_000
ARCHIVED_CREATE = 1_700_100_000
UNKNOWN_CREATE = 1_700_200_000

#: 房间夹具：一个还在 `t_rooms` 里、一个已销毁（有战绩快照）、一个已销毁（无战绩快照）。
LIVE_UUID = "1760000000000526035"
ARCHIVED_UUID = "1760000000000641280"
UNKNOWN_UUID = "1760000000000593071"

LIVE_SEATS = ((1001, "玩家甲", 20), (1002, "玩家乙", 10), (1003, "玩家丙", 0), (1004, "玩家丁", -10))
ARCHIVED_SEATS = (
    (2001, "归档甲", 30),
    (2002, "归档乙", -10),
    (2003, "归档丙", -10),
    (2004, "归档丁", -10),
)

#: 样例出牌流水（三元组：座位 / 动作 / 牌），六种动作各一次，且"二筒"会被碰。
ACTIONS: tuple[int, ...] = (
    0, decoding.ACTION_CHUPAI, 0,
    1, decoding.ACTION_MOPAI, 9,
    1, decoding.ACTION_CHUPAI, 1,
    2, decoding.ACTION_PENG, 1,
    2, decoding.ACTION_CHUPAI, 18,
    3, decoding.ACTION_MOPAI, 3,
    3, decoding.ACTION_GANG, 3,
    3, decoding.ACTION_CHUPAI, 20,
    0, decoding.ACTION_MOPAI, 8,
    0, decoding.ACTION_ZIMO, 8,
    1, decoding.ACTION_HU, 0,
)

ROOM_COLUMNS = (
    "uuid, id, base_info, create_time, num_of_turns, next_button,"
    " user_id0, user_icon0, user_name0, user_score0,"
    " user_id1, user_icon1, user_name1, user_score1,"
    " user_id2, user_icon2, user_name2, user_score2,"
    " user_id3, user_icon3, user_name3, user_score3, ip, port"
)


def _b64(value: str) -> str:
    """按游戏服的入库口径把昵称编码成 Base64。"""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _site_date(seconds: int) -> str:
    """Unix 秒 → 站点时区下的 `YYYY-MM-DD`（用于日期区间断言）。"""
    return datetime.fromtimestamp(seconds, tz=SITE_TZ).strftime("%Y-%m-%d")


def _wall() -> list[int]:
    """一副确定性的"洗好的牌墙"：`0,0,0,0,1,1,1,1,...,26,26,26,26`。"""
    return [tile for tile in range(27) for _ in range(4)]


def _base_info(*, room_type: str, game_index: int, button: int) -> str:
    """开局快照（牌墙 + 四家起手牌，起手 53 张与真实发牌口径一致）。"""
    wall = _wall()
    hands: list[list[int]] = [[], [], [], []]
    for index in range(53):
        hands[index % 4].append(wall[index])
    return json.dumps(
        {"type": room_type, "button": button, "index": game_index, "mahjongs": wall, "game_seats": hands},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _game(
    *,
    uuid: str,
    game_index: int,
    room_type: str,
    create_time: int,
    button: int = 0,
    result: tuple[int, int, int, int] = (10, -6, -2, -2),
    action_records: str | None = None,
) -> tuple[Any, ...]:
    """一行 `t_games` / `t_games_archive` 的参数。"""
    return (
        uuid,
        game_index,
        _base_info(room_type=room_type, game_index=game_index, button=button),
        create_time,
        None,
        json.dumps(list(ACTIONS), separators=(",", ":")) if action_records is None else action_records,
        json.dumps(list(result), separators=(",", ":")),
    )


def _room_row(
    *,
    uuid: str,
    room_id: str,
    room_type: str,
    create_time: int,
    seats: tuple[tuple[int, str, int], ...],
) -> tuple[Any, ...]:
    """一行 `t_rooms` 的参数。"""
    conf = {
        "type": room_type,
        "baseScore": 1,
        "zimo": 0,
        "jiangdui": False,
        "hsz": False,
        "dianganghua": 0,
        "menqing": False,
        "tiandihu": False,
        "maxFan": 4,
        "maxGames": 4,
        "creator": seats[0][0],
    }
    values: list[Any] = []
    for user_id, name, score in seats:
        values.extend([user_id, "", _b64(name) if name else "", score])
    return (
        uuid,
        room_id,
        json.dumps(conf, separators=(",", ":")),
        create_time,
        2,
        0,
        *values,
        "127.0.0.1",
        10000,
    )


def _history(*, uuid: str, room_id: str, create_time: int, seats: tuple[tuple[int, str, int], ...]) -> str:
    """一条 `t_users.history` 的战绩快照（口径见 `gamemgr.store_history`）。"""
    entry = {
        "uuid": uuid,
        "id": room_id,
        "time": create_time,
        "seats": [
            {"userid": user_id, "name": _b64(name) if name else "", "score": score}
            for user_id, name, score in seats
        ],
    }
    return json.dumps([entry], separators=(",", ":"), ensure_ascii=False)


class GameTestBase(TestCase):
    """建四张玩家库表 + 对局夹具，并登录一个超级管理员。"""

    databases = {"default", PLAYER_DB}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        connection = connections[PLAYER_DB]
        statements = CREATE_TABLE_SQL.get(connection.vendor)
        if statements is None:  # pragma: no cover - 只支持 sqlite / mysql
            raise unittest.SkipTest(f"未支持的玩家库后端：{connection.vendor}")
        game_ddl, room_ddl, player_ddl = statements
        with connection.cursor() as cursor:
            for table in GAME_TABLES:
                cursor.execute(game_ddl.format(table=table))
            cursor.execute(room_ddl)
            cursor.execute(player_ddl)

    @classmethod
    def tearDownClass(cls) -> None:
        connection = connections[PLAYER_DB]
        with connection.cursor() as cursor:
            for table in GAME_TABLES:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
            cursor.execute("DROP TABLE IF EXISTS t_rooms")
            cursor.execute("DROP TABLE IF EXISTS t_users")
        super().tearDownClass()

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = AdminUser.objects.create_superuser(
            username="admin",
            password=PASSWORD,
            email="admin@platform.local",
            nickname="超级管理员",
        )
        self.client.force_authenticate(self.admin)
        self._seed()

    def _seed(self) -> None:
        """写入夹具：三个房间、六局对局、四个有战绩的玩家 + 一个没有战绩的玩家。"""
        with connections[PLAYER_DB].cursor() as cursor:
            for table in GAME_TABLES:
                cursor.execute(f"DELETE FROM {table}")
            cursor.execute("DELETE FROM t_rooms")
            cursor.execute("DELETE FROM t_users")

            cursor.execute(
                f"INSERT INTO t_rooms ({ROOM_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s,"
                " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                _room_row(
                    uuid=LIVE_UUID,
                    room_id="526035",
                    room_type="xzdd",
                    create_time=LIVE_CREATE,
                    seats=LIVE_SEATS,
                ),
            )

            live_rows = [
                _game(
                    uuid=LIVE_UUID,
                    game_index=0,
                    room_type="xzdd",
                    create_time=LIVE_CREATE + 100,
                    button=0,
                ),
                _game(
                    uuid=LIVE_UUID,
                    game_index=1,
                    room_type="xzdd",
                    create_time=LIVE_CREATE + 400,
                    button=1,
                    result=(-4, 4, 0, 0),
                ),
            ]
            archived_rows = [
                _game(
                    uuid=ARCHIVED_UUID,
                    game_index=0,
                    room_type="xlch",
                    create_time=ARCHIVED_CREATE + 100,
                    button=0,
                ),
                _game(
                    uuid=ARCHIVED_UUID,
                    game_index=1,
                    room_type="xlch",
                    create_time=ARCHIVED_CREATE + 400,
                    button=1,
                    result=(0, 0, 5, -5),
                ),
            ]
            # 第三个房间：第一局没有流水（NULL），第二局的流水是坏数据（长度不是 3 的倍数）。
            unknown_rows = [
                _game(
                    uuid=UNKNOWN_UUID,
                    game_index=0,
                    room_type="xzdd",
                    create_time=UNKNOWN_CREATE + 100,
                    action_records="",
                ),
                _game(
                    uuid=UNKNOWN_UUID,
                    game_index=1,
                    room_type="xzdd",
                    create_time=UNKNOWN_CREATE + 400,
                    action_records=json.dumps([0, decoding.ACTION_CHUPAI, 0, 5]),
                ),
            ]
            for table, rows in (
                (player_source.GAME_LIVE_TABLE, live_rows),
                (player_source.GAME_ARCHIVE_TABLE, archived_rows + unknown_rows),
            ):
                cursor.executemany(
                    f"INSERT INTO {table}"
                    " (room_uuid, game_index, base_info, create_time, snapshots, action_records, result)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    rows,
                )

            history = _history(
                uuid=ARCHIVED_UUID,
                room_id="641280",
                create_time=ARCHIVED_CREATE,
                seats=ARCHIVED_SEATS,
            )
            for user_id, name, _score in (*ARCHIVED_SEATS, (3001, "无战绩玩家", 0)):
                cursor.execute(
                    "INSERT INTO t_users (userid, account, name, history) VALUES (%s, %s, %s, %s)",
                    (
                        user_id,
                        f"guest_{user_id}",
                        _b64(name),
                        history if user_id != 3001 else "",
                    ),
                )

    # ------------------------------------------------------------ 小工具

    def list_games(self, **params: Any) -> dict[str, Any]:
        """打列表接口并返回 `data`。"""
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["code"], 0, body)
        return body["data"]

    def detail(self, room_ref: str, game_index: int) -> dict[str, Any]:
        """打单局详情接口并返回 `data`。"""
        response = self.client.get(f"{ROOMS_URL}{room_ref}/{game_index}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def room_games(self, room_ref: str) -> dict[str, Any]:
        """打房间对局接口并返回 `data`。"""
        response = self.client.get(f"{ROOMS_URL}{room_ref}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]


class GameListTests(GameTestBase):
    """列表：搜索 / 过滤 / 排序 / 分页。"""

    def test_requires_login(self) -> None:
        """未登录返回 401 + 10002。"""
        response = APIClient().get(LIST_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)

    def test_returns_games_with_seats_and_actions(self) -> None:
        """默认按本局开始时间倒序，带四家得分与动作统计。"""
        data = self.list_games()
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)
        self.assertEqual(data["pages"], 1)

        first = data["items"][0]
        self.assertEqual(first["room_uuid"], UNKNOWN_UUID)
        self.assertEqual(first["room_id"], "593071")
        self.assertEqual(first["game_index"], 1)
        self.assertEqual(first["round"], 2)
        self.assertEqual(first["source"], "archive")
        self.assertEqual(first["source_label"], "已结束")
        self.assertEqual(first["type"], "xzdd")
        self.assertEqual(first["type_label"], "血战到底")
        self.assertEqual(first["seat_count"], 4)
        self.assertRegex(first["created_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_seat_scores_come_from_result(self) -> None:
        """每一局的分是 `t_games.result`，不是房间累计分。"""
        data = self.list_games(keyword=LIVE_UUID, ordering="create_time")
        first, second = data["items"]
        self.assertEqual([seat["score"] for seat in first["seats"]], [10, -6, -2, -2])
        self.assertEqual([seat["score"] for seat in second["seats"]], [-4, 4, 0, 0])
        # 存活房间的座位还能给出房间累计分（来自 t_rooms.user_scoreN）。
        self.assertEqual([seat["room_score"] for seat in first["seats"]], [20, 10, 0, -10])
        self.assertTrue(first["live"])
        self.assertEqual(first["identity_source"], "rooms")
        self.assertIn("t_rooms", first["identity_note"])
        # 庄家是每一局各自的（button 来自 base_info）。
        self.assertEqual([seat["is_banker"] for seat in first["seats"]], [True, False, False, False])
        self.assertEqual([seat["is_banker"] for seat in second["seats"]], [False, True, False, False])

    def test_action_summary_in_list(self) -> None:
        """列表就带动作条数统计，不用点进详情才知道有没有流水。"""
        item = self.list_games(keyword=LIVE_UUID, ordering="create_time")["items"][0]
        self.assertTrue(item["has_action_records"])
        self.assertEqual(item["action_count"], 11)
        self.assertEqual(
            item["action_summary"],
            {"chupai": 4, "mopai": 3, "peng": 1, "gang": 1, "hu": 1, "zimo": 1},
        )
        self.assertTrue(item["detail_available"])

    def test_unknown_identity_when_no_room_and_no_history(self) -> None:
        """房间已销毁、又没有战绩快照时：只显示座位号，不编造玩家。"""
        data = self.list_games(keyword=UNKNOWN_UUID, ordering="create_time")
        self.assertEqual(data["total"], 2)
        item = data["items"][0]
        self.assertEqual(item["identity_source"], "unknown")
        self.assertIn("无法确认", item["identity_note"])
        self.assertEqual([seat["display_name"] for seat in item["seats"]], ["座位0", "座位1", "座位2", "座位3"])
        self.assertEqual([seat["room_score"] for seat in item["seats"]], [None] * 4)
        self.assertFalse(item["live"])

    def test_identity_from_history_for_archived_room(self) -> None:
        """房间已销毁但有战绩快照时，玩家身份从 `t_users.history` 反查。"""
        item = self.list_games(keyword=ARCHIVED_UUID, ordering="create_time")["items"][0]
        self.assertEqual(item["identity_source"], "history")
        self.assertIn("history", item["identity_note"])
        self.assertEqual(item["room_id"], "641280")
        self.assertEqual(
            [seat["name"] for seat in item["seats"]],
            ["归档甲", "归档乙", "归档丙", "归档丁"],
        )
        self.assertEqual([seat["room_score"] for seat in item["seats"]], [30, -10, -10, -10])

    def test_keyword_by_uuid_room_id_player_id_and_name(self) -> None:
        """四种搜索口径：uuid / 房间号 / 玩家 ID / 玩家昵称。"""
        self.assertEqual(self.list_games(keyword=LIVE_UUID)["total"], 2)
        self.assertEqual(self.list_games(keyword="526035")["total"], 2)
        self.assertEqual(self.list_games(keyword="641280")["total"], 2)
        self.assertEqual(self.list_games(keyword="2001")["total"], 2)
        self.assertEqual(self.list_games(keyword="归档甲")["total"], 2)
        self.assertEqual(self.list_games(keyword="无战绩玩家")["total"], 0)

    def test_keyword_no_match(self) -> None:
        """搜索不到时返回空列表而不是报错。"""
        data = self.list_games(keyword="no-such-room")
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_source_filter(self) -> None:
        """按来源过滤：在局（t_games）/ 归档（t_games_archive）。"""
        self.assertEqual(self.list_games(source="live")["total"], 2)
        self.assertEqual(self.list_games(source="archive")["total"], 4)
        self.assertEqual(self.list_games(source="all")["total"], 6)
        self.assertEqual(self.list_games(source="live", keyword=ARCHIVED_UUID)["total"], 0)

    def test_game_type_filter(self) -> None:
        """按玩法过滤（`conf.type` 落在 base_info 的紧凑 JSON 里）。"""
        self.assertEqual(self.list_games(game_type="xzdd")["total"], 4)
        self.assertEqual(self.list_games(game_type="xlch")["total"], 2)
        self.assertEqual(self.list_games(game_type="")["total"], 6)

    def test_date_range_filter(self) -> None:
        """按本局开始日期过滤（站点时区，闭区间）。"""
        data = self.list_games(
            date_from=_site_date(ARCHIVED_CREATE),
            date_to=_site_date(ARCHIVED_CREATE),
        )
        self.assertEqual(data["total"], 2)
        self.assertTrue(all(item["room_uuid"] == ARCHIVED_UUID for item in data["items"]))
        # 起止反着填按参数错误拒绝。
        response = self.client.get(
            LIST_URL,
            {"date_from": _site_date(UNKNOWN_CREATE), "date_to": _site_date(LIVE_CREATE)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_ordering(self) -> None:
        """四种排序键都是白名单内的固定 SQL。"""
        newest = self.list_games(ordering="-create_time")["items"][0]
        oldest = self.list_games(ordering="create_time")["items"][0]
        self.assertEqual(newest["create_time"], UNKNOWN_CREATE + 400)
        self.assertEqual(oldest["create_time"], LIVE_CREATE + 100)
        self.assertEqual(self.list_games(ordering="-game_index")["items"][0]["game_index"], 1)

    def test_pagination(self) -> None:
        """分页返回固定键集，第二页接上第一页。"""
        first = self.list_games(page=1, page_size=4, ordering="create_time")
        second = self.list_games(page=2, page_size=4, ordering="create_time")
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["items"]), 4)
        self.assertEqual(len(second["items"]), 2)
        self.assertNotEqual(
            first["items"][0]["room_uuid"] + str(first["items"][0]["game_index"]),
            second["items"][0]["room_uuid"] + str(second["items"][0]["game_index"]),
        )

    def test_invalid_params_rejected(self) -> None:
        """非法参数按参数错误（10001）拒绝，而不是 500。"""
        for params in (
            {"page_size": 0},
            {"page_size": 100000},
            {"page": 0},
            {"source": "whatever"},
            {"game_type": "no-such-type"},
            {"ordering": "create_time; drop table t_games"},
            {"date_from": "not-a-date"},
        ):
            response = self.client.get(LIST_URL, params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.json()["code"], 10001, params)


class GameOverviewTests(GameTestBase):
    """概览数字。"""

    def test_overview_counts(self) -> None:
        """总局数 / 已结束 / 进行中；夹具都在 2023 年，所以"最近 24 小时"是 0。"""
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(data["total_games"], 6)
        self.assertEqual(data["archived_games"], 4)
        self.assertEqual(data["live_games"], 2)
        self.assertEqual(data["games_last_24h"], 0)
        self.assertEqual(data["rooms_last_24h"], 0)

    def test_overview_empty(self) -> None:
        """一局都没有时全是 0，不是 null（`SUM` 在空集上返回 NULL）。"""
        with connections[PLAYER_DB].cursor() as cursor:
            for table in GAME_TABLES:
                cursor.execute(f"DELETE FROM {table}")
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(
            data,
            {
                "total_games": 0,
                "archived_games": 0,
                "live_games": 0,
                "games_last_24h": 0,
                "rooms_last_24h": 0,
            },
        )

    def test_overview_requires_login(self) -> None:
        """概览也要登录。"""
        response = APIClient().get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class RoomGameTests(GameTestBase):
    """房间对局：房间号 / uuid 两种取法 + 三种身份来源 + 不存在。"""

    def test_room_games_live(self) -> None:
        """存活房间：房间信息 + 四个座位（含房间累计分）+ 逐局要点。"""
        data = self.room_games("526035")
        self.assertEqual(data["room_id"], "526035")
        self.assertEqual(data["room_uuid"], LIVE_UUID)
        self.assertEqual(data["type"], "xzdd")
        self.assertEqual(data["type_label"], "血战到底")
        self.assertTrue(data["live"])
        self.assertEqual(data["identity_source"], "rooms")
        self.assertEqual([seat["name"] for seat in data["seats"]], ["玩家甲", "玩家乙", "玩家丙", "玩家丁"])
        self.assertEqual(data["game_count"], 2)
        self.assertEqual([game["round"] for game in data["games"]], [1, 2])

    def test_room_games_by_uuid_and_room_id(self) -> None:
        """uuid 与 6 位房间号都能打开同一个已结束房间。"""
        by_uuid = self.room_games(ARCHIVED_UUID)
        by_id = self.room_games("641280")
        self.assertEqual(by_uuid["room_uuid"], by_id["room_uuid"])
        self.assertEqual(by_id["room_id"], "641280")
        self.assertEqual(by_id["identity_source"], "history")
        self.assertEqual(by_id["game_count"], 2)

    def test_room_games_unknown_identity(self) -> None:
        """身份查不到时座位显示成"座位N"，接口照常返回。"""
        data = self.room_games("593071")
        self.assertEqual(data["identity_source"], "unknown")
        self.assertFalse(data["live"])
        self.assertEqual([seat["display_name"] for seat in data["seats"]], ["座位0", "座位1", "座位2", "座位3"])
        self.assertEqual(data["game_count"], 2)

    def test_room_games_not_found(self) -> None:
        """房间没有任何对局记录时 404 + 14001（第一局还没打完时就是这样）。"""
        response = self.client.get(f"{ROOMS_URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 14001)
        self.assertIn("每结束一局", response.json()["message"])

    def test_room_games_invalid_ref(self) -> None:
        """形态不合法（非字母数字）按参数错误处理，而不是去查库。"""
        response = self.client.get(f"{ROOMS_URL}room%20with%20space/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_room_games_requires_login(self) -> None:
        """房间对局也要登录。"""
        response = APIClient().get(f"{ROOMS_URL}526035/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class GameDetailTests(GameTestBase):
    """单局详情：**出牌记录**。"""

    def test_timeline_decodes_tiles_and_actions(self) -> None:
        """时间线按三元组解出座位 / 动作 / 牌面。"""
        data = self.detail("526035", 0)
        self.assertEqual(data["round"], 1)
        self.assertEqual(data["warnings"], [])
        timeline = data["timeline"]
        self.assertEqual(len(timeline), 11)
        self.assertEqual(
            [(item["seq"], item["seat_index"], item["action_label"], item["tile_label"]) for item in timeline[:4]],
            [
                (1, 0, "出牌", "一筒"),
                (2, 1, "摸牌", "一条"),
                (3, 1, "出牌", "二筒"),
                (4, 2, "碰", "二筒"),
            ],
        )
        self.assertEqual(timeline[0]["player_id"], 1001)
        self.assertEqual(timeline[0]["seat_name"], "玩家甲")
        # 牌 id → 客户端图集名，将来要画牌面时直接用。
        self.assertEqual(timeline[0]["tile_code"], "dot_1")
        self.assertEqual(timeline[4]["tile_label"], "一万")
        self.assertEqual(timeline[4]["tile_code"], "character_1")
        self.assertEqual(timeline[-1]["action_label"], "胡")

    def test_discard_taken_by_peng(self) -> None:
        """打出的"二筒"被下家碰走，时间线里要标出来。"""
        timeline = self.detail("526035", 0)["timeline"]
        self.assertEqual(timeline[2]["tile_label"], "二筒")
        taken = timeline[2]["taken_by"]
        self.assertEqual(taken["seat_index"], 2)
        self.assertEqual(taken["name"], "玩家丙")
        self.assertEqual(taken["action_label"], "碰")
        # 没人要的牌不带这个键。
        self.assertNotIn("taken_by", timeline[0])

    def test_seat_actions_are_per_player_play_records(self) -> None:
        """`seat_actions` 是**每个玩家自己的出牌记录**。"""
        data = self.detail("526035", 0)
        seats = {item["seat_index"]: item for item in data["seat_actions"]}
        self.assertEqual([item["tile_label"] for item in seats[0]["folds"]], ["一筒"])
        self.assertEqual([item["tile_label"] for item in seats[1]["folds"]], ["二筒"])
        self.assertEqual([item["tile_label"] for item in seats[2]["folds"]], ["一万"])
        self.assertEqual([item["tile_label"] for item in seats[3]["folds"]], ["三万"])
        self.assertEqual(seats[0]["drawn_text"], "九筒")
        self.assertEqual(seats[0]["win_text"], "九筒")
        self.assertTrue(seats[0]["hued"])
        self.assertTrue(seats[0]["zimo"])
        self.assertTrue(seats[1]["hued"])
        self.assertFalse(seats[1]["zimo"])
        self.assertEqual(seats[2]["pengs_text"], "二筒")
        self.assertEqual(seats[3]["gangs_text"], "四筒")
        self.assertEqual(seats[3]["summary"]["chupai"], 1)
        self.assertEqual(seats[3]["summary"]["gang"], 1)
        self.assertEqual(seats[0]["name"], "玩家甲")
        self.assertEqual(seats[0]["player_id"], 1001)

    def test_initial_hands_and_wall(self) -> None:
        """开局手牌与牌墙消耗都从 `base_info` 推出来。"""
        data = self.detail("526035", 0)
        hands = data["initial_hands"]
        self.assertEqual([hand["tile_count"] for hand in hands], [14, 13, 13, 13])
        self.assertEqual(hands[0]["tiles_text"].split()[0], "一筒")
        self.assertEqual(hands[0]["name"], "玩家甲")
        self.assertEqual(data["wall"]["size"], 108)
        self.assertEqual(data["wall"]["dealt"], 53)
        self.assertEqual(data["wall"]["drawn"], 3)
        self.assertEqual(data["wall"]["remaining"], 52)
        self.assertEqual(len(data["wall"]["tiles"]), 108)
        self.assertEqual(data["initial_hands_text"][0], hands[0]["tiles_text"])

    def test_detail_uses_archive_first(self) -> None:
        """同一局在两张表里都出现时以归档表为准（搬迁途中的一瞬间）。"""
        with connections[PLAYER_DB].cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {player_source.GAME_LIVE_TABLE}"
                " (room_uuid, game_index, base_info, create_time, action_records, result)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (ARCHIVED_UUID, 0, "{}", ARCHIVED_CREATE, "[]", "[99,0,0,0]"),
            )
        data = self.detail(ARCHIVED_UUID, 0)
        self.assertEqual(data["source"], "archive")
        self.assertEqual(data["result"], [10, -6, -2, -2])

    def test_missing_action_records(self) -> None:
        """没有流水（NULL / 空串）时不是错误：时间线为空，按钮不可点。"""
        data = self.detail("593071", 0)
        self.assertEqual(data["timeline"], [])
        self.assertFalse(data["has_action_records"])
        self.assertEqual(data["action_count"], 0)
        self.assertEqual(data["warnings"], [])
        # 没有流水也还有开局快照，所以还是能看起手牌。
        self.assertEqual([hand["tile_count"] for hand in data["initial_hands"]], [14, 13, 13, 13])

    def test_malformed_action_records(self) -> None:
        """脏流水只记警告：长度不是 3 的倍数时只解出完整的那一组。"""
        data = self.detail("593071", 1)
        self.assertEqual(len(data["timeline"]), 1)
        self.assertEqual(data["timeline"][0]["tile_label"], "一筒")
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("3 的整数倍", data["warnings"][0])

    def test_detail_not_found(self) -> None:
        """局号不存在时 404 + 14001，文案里点出"每结束一局才写库"。"""
        response = self.client.get(f"{ROOMS_URL}526035/9/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 14001)

    def test_detail_requires_login(self) -> None:
        """单局详情也要登录。"""
        response = APIClient().get(f"{ROOMS_URL}526035/0/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class PlayerGameTests(GameTestBase):
    """玩家对局：走 `t_users.history`。"""

    def test_player_games_from_history(self) -> None:
        """返回该玩家的房间战绩，标出"我"的座位 / 得分 / 名次，并补上房间局数。"""
        response = self.client.get(f"{PLAYERS_URL}2001/")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["player_id"], 2001)
        self.assertEqual(data["max_entries"], 10)
        self.assertIn("最近", data["note"])

        item = data["items"][0]
        self.assertEqual(item["room_uuid"], ARCHIVED_UUID)
        self.assertEqual(item["room_id"], "641280")
        self.assertEqual(item["my_seat"], 0)
        self.assertEqual(item["my_score"], 30)
        self.assertEqual(item["my_rank"], 1)
        self.assertTrue(item["games_available"])
        self.assertEqual(item["game_count"], 2)
        self.assertEqual([seat["score"] for seat in item["seats"]], [30, -10, -10, -10])
        self.assertEqual(
            [seat["name"] for seat in item["seats"]],
            ["归档甲", "归档乙", "归档丙", "归档丁"],
        )
        self.assertEqual([seat["is_me"] for seat in item["seats"]], [True, False, False, False])
        self.assertRegex(item["created_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_player_without_history(self) -> None:
        """有玩家但没有战绩时返回空列表（不是 404）。"""
        data = self.client.get(f"{PLAYERS_URL}3001/").json()["data"]
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])
        self.assertEqual(data["player_id"], 3001)

    def test_player_not_found(self) -> None:
        """玩家库里没有这个 ID 时 404 + 12001（与玩家管理的口径一致）。"""
        response = self.client.get(f"{PLAYERS_URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 12001)

    def test_player_games_requires_login(self) -> None:
        """玩家对局也要登录。"""
        response = APIClient().get(f"{PLAYERS_URL}2001/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)

    def test_invalid_pagination(self) -> None:
        """分页参数照常校验。"""
        response = self.client.get(f"{PLAYERS_URL}2001/", {"page_size": 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)


class GameSourceIsolationTests(GameTestBase):
    """只读隔离：对局这条路径上不允许出现任何写操作。"""

    def test_read_only_guard_rejects_game_writes(self) -> None:
        """对局相关的写语句会被只读校验拦下（代码 bug 要立刻炸出来）。"""
        for sql in (
            f"UPDATE {player_source.GAME_LIVE_TABLE} SET result = '[0,0,0,0]'",
            f"DELETE FROM {player_source.GAME_ARCHIVE_TABLE} WHERE room_uuid = 'x'",
            f"INSERT INTO {player_source.GAME_LIVE_TABLE} (room_uuid) VALUES ('1')",
            "SELECT 1; DELETE FROM t_games",
        ):
            with self.assertRaises(PlayerSourceReadOnlyViolation, msg=sql):
                player_source._assert_read_only(sql)

    def test_read_only_guard_accepts_generated_game_sql(self) -> None:
        """模块自己拼出来的对局 SQL 必须全部通过只读校验。"""
        for ordering in player_source.GAME_ORDERING_CHOICES:
            rows, total = player_source.search_games(
                keyword="玩家甲",
                game_type="xzdd",
                source=player_source.GAME_SOURCE_ALL,
                created_from=LIVE_CREATE,
                created_to=UNKNOWN_CREATE + 1000,
                ordering=ordering,
            )
            self.assertEqual(total, 2)
            self.assertTrue(rows)
        player_source.game_overview()
        player_source.get_room_games(LIVE_UUID)
        player_source.get_game(LIVE_UUID, 0)
        player_source.count_games_by_room([LIVE_UUID, ARCHIVED_UUID])
        player_source.player_history_entries(2001)
        player_source.resolve_room_ref("526035")
        player_source.resolve_room_uuids("526035")

    def test_every_game_db_query_is_select(self) -> None:
        """跑一遍对局接口，玩家库上执行的每一条 SQL 都是 SELECT。"""
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            self.client.get(LIST_URL)
            self.client.get(OVERVIEW_URL)
            self.client.get(f"{ROOMS_URL}526035/")
            self.client.get(f"{ROOMS_URL}641280/1/")
            self.client.get(f"{PLAYERS_URL}2001/")

        self.assertGreater(len(captured.captured_queries), 0)
        for query in captured.captured_queries:
            sql = str(query["sql"]).strip()
            self.assertTrue(
                sql.lower().startswith("select"),
                f"玩家库上出现了非 SELECT 语句：{sql}",
            )

    def test_union_query_is_still_a_single_select(self) -> None:
        """`UNION ALL` 合并两张表的 SQL 仍然是单条 SELECT（不会被只读校验误伤）。"""
        sql, params = player_source._game_union(
            uuids=[LIVE_UUID],
            game_type="xzdd",
            created_from=None,
            created_to=None,
            columns=player_source.GAME_COLUMNS,
            tail=" ORDER BY create_time DESC",
        )
        player_source._assert_read_only(sql)
        self.assertIn("UNION ALL", sql)
        self.assertEqual(len(params), 4)

    def test_games_app_has_no_own_db_channel(self) -> None:
        """`apps/games` 不得自己连玩家库：SQL 只允许出现在 `player_source.py`。

        用 AST 读真实的 import，而不是在源码文本里找关键字（模块文档里正好写着
        "只执行 SELECT"这类句子）。
        """
        import ast
        import inspect

        from apps.games import serializers as games_serializers
        from apps.games import views as games_views

        banned_roots = {"utils", "aiomysql", "mysql", "pymysql", "django.db"}
        for module in (games_views, games_serializers):
            tree = ast.parse(inspect.getsource(module))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(
                [name for name in imported if name.split(".")[0] in banned_roots],
                f"{module.__name__} 不应自己连玩家库：{sorted(imported)}",
            )
            self.assertNotIn(
                "django.db",
                imported,
                f"{module.__name__} 不应直接使用数据库连接（要走 player_source）",
            )

    def test_games_app_has_no_models(self) -> None:
        """`apps/games` 在玩家库与本平台库上都没有模型（不落任何表）。"""
        from django.apps import apps

        self.assertEqual(list(apps.get_app_config("games").get_models()), [])


class DecodingTests(TestCase):
    """`apps/games/decoding.py` 的纯函数（不碰数据库）。"""

    def test_tile_labels_and_codes(self) -> None:
        """牌 id 的两种形态：中文牌面 + 客户端图集名。"""
        self.assertEqual(decoding.tile_label(0), "一筒")
        self.assertEqual(decoding.tile_label(8), "九筒")
        self.assertEqual(decoding.tile_label(9), "一条")
        self.assertEqual(decoding.tile_label(17), "九条")
        self.assertEqual(decoding.tile_label(18), "一万")
        self.assertEqual(decoding.tile_label(26), "九万")
        self.assertEqual(decoding.tile_code(0), "dot_1")
        self.assertEqual(decoding.tile_code(9), "bamboo_1")
        self.assertEqual(decoding.tile_code(26), "character_9")
        self.assertEqual(decoding.tile_suit(0), 0)
        self.assertEqual(decoding.tile_suit(26), 2)

    def test_invalid_tile_is_reported_as_is(self) -> None:
        """越界的牌不猜：如实写成 `未知牌(x)`，图集名为空。"""
        self.assertEqual(decoding.tile_label(99), "未知牌(99)")
        self.assertEqual(decoding.tile_code(99), "")
        self.assertIsNone(decoding.tile_suit(-1))
        self.assertFalse(decoding.is_valid_tile("一筒"))

    def test_parse_action_records_warnings(self) -> None:
        """脏流水只出警告，不抛异常。"""
        actions, warnings = decoding.decode_action_records("not json")
        self.assertEqual(actions, [])
        self.assertEqual(len(warnings), 1)
        actions, warnings = decoding.decode_action_records(json.dumps([1, 2, 3, 4]))
        self.assertEqual(len(actions), 1)
        self.assertEqual(len(warnings), 1)
        actions, warnings = decoding.decode_action_records(json.dumps(["a", 2, 3]))
        # 座位号不是数字：按"未知"处理并记一条警告，动作与牌面照常解出来。
        self.assertEqual(actions[0]["seat_index"], decoding.NO_TILE)
        self.assertEqual(actions[0]["action_label"], "摸牌")
        self.assertEqual(len(warnings), 1)

    def test_unknown_action_code(self) -> None:
        """不认识的动作用 `未知动作(N)` 表示。"""
        actions, _ = decoding.decode_action_records(json.dumps([0, 7, 5]))
        self.assertEqual(actions[0]["action_label"], "未知动作(7)")
        self.assertEqual(actions[0]["action_short"], "?")

    def test_summarize_actions(self) -> None:
        """统计只数认识的六个动作。"""
        actions, _ = decoding.decode_action_records(json.dumps([0, 1, 2, 0, 7, 3]))
        self.assertEqual(
            decoding.summarize_actions(actions),
            {"chupai": 1, "mopai": 0, "peng": 0, "gang": 0, "hu": 0, "zimo": 0},
        )


class InitPlayerDevGameSeedTests(GameTestBase):
    """离线开发命令也会给对局记录造样例数据。"""

    def test_seeds_games_with_three_identity_sources(self) -> None:
        """SQLite 玩家库下写入样例对局，三种身份来源都能被接口查出来。"""
        if connections[PLAYER_DB].vendor != "sqlite":
            self.skipTest("本命令只服务 SQLite 离线库")
        call_command("init_player_dev", "--reset")

        data = self.list_games(page_size=100)
        self.assertGreaterEqual(data["total"], 6)
        uuid_by_room = {item["room_id"]: item["room_uuid"] for item in data["items"]}
        self.assertIn("526035", uuid_by_room)
        self.assertIn("641280", uuid_by_room)
        self.assertIn("593071", uuid_by_room)

        # 存活房间：身份来自 t_rooms。
        live = self.room_games("526035")
        self.assertEqual(live["identity_source"], "rooms")
        self.assertGreater(live["game_count"], 0)
        # 已销毁 + 有战绩快照：身份来自 t_users.history。
        archived = self.room_games("641280")
        self.assertEqual(archived["identity_source"], "history")
        self.assertEqual(archived["identity_note"].find("history") >= 0, True)
        # 已销毁 + 没战绩快照（只打了一局就散场）：身份查不到。
        unknown = self.room_games("593071")
        self.assertEqual(unknown["identity_source"], "unknown")

        # 样例流水能解出六种动作，且"二筒"被碰。
        detail = self.detail("641280", 0)
        summary = detail["action_summary"]
        self.assertEqual(
            summary,
            {"chupai": 4, "mopai": 3, "peng": 1, "gang": 1, "hu": 1, "zimo": 1},
        )
        self.assertEqual(detail["timeline"][2]["taken_by"]["action_label"], "碰")
        # 玩家战绩快照也能查到（样例给 641280 的四家都写了 history）。
        players = self.client.get(f"{PLAYERS_URL}1001/").json()["data"]
        self.assertGreaterEqual(players["total"], 1)
