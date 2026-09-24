"""房间管理接口测试。

覆盖范围：

* 列表：搜索（房间号 / uuid / 座位玩家 ID / 座位昵称）、玩法过滤、状态过滤、
  排序、分页、参数校验；
* 详情：房间配置 + 四个座位 + 预留入口说明；不存在时 `13001`；非法房间号 `10001`；
* 概览：总数 / 满座 / 未满座 / 最近 24 小时新建；
* 预留的解散入口：契约（`reserved: true`）、角色下限（`10003`）、
  **调用它不会改动房间数据**；
* **只读隔离**：房间这条路径上执行的每一条 SQL 都必须是 SELECT，
  而且 SQL 只能出现在 `player_source.py` 这一条通道里；
* 离线开发命令 `init_player_dev` 也会给房间管理造样例房间。

房间夹具建在**玩家库别名**（`DATABASES["player"]`）的测试库上：SQLite 下是内存库，
MySQL 下是 `test_db_scmj`，**不会**碰真实的 `db_scmj`。表结构由本文件自己建——
管理平台在玩家库里没有任何模型与迁移，这正是隔离的体现。
"""

from __future__ import annotations

import base64
import json
import time
import unittest
from typing import Any

from django.core.management import call_command
from django.db import connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import AdminUser
from apps.players import player_source
from apps.players.exceptions import PlayerSourceReadOnlyViolation

LIST_URL = "/api/rooms/"
OVERVIEW_URL = "/api/rooms/overview/"
PLAYER_DB = player_source.PLAYER_DB_ALIAS
PASSWORD = "AdminPass!2024"

#: 建表语句：两种后端各一份（列与 `server/sql/db_babykylin.sql` 对齐）。
#: `t_users` 只为"两条业务线共用同一条只读通道"那条断言准备，本文件不写它。
CREATE_TABLE_SQL = {
    "sqlite": (
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
        "ip TEXT, port INTEGER DEFAULT 0, PRIMARY KEY (uuid), UNIQUE (id))"
    ),
    "mysql": (
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
        "PRIMARY KEY (uuid), UNIQUE KEY id (id)) ENGINE=InnoDB DEFAULT CHARSET=utf8"
    ),
}

#: `t_users`：只为验证"玩家与房间走同一条只读通道"，本文件不往里写数据。
CREATE_PLAYER_TABLE_SQL = {
    "sqlite": (
        "CREATE TABLE IF NOT EXISTS t_users ("
        "userid INTEGER PRIMARY KEY, account TEXT NOT NULL DEFAULT '', name TEXT,"
        "sex INTEGER DEFAULT 0, headimg TEXT, lv INTEGER DEFAULT 1, exp INTEGER DEFAULT 0,"
        "coins INTEGER DEFAULT 0, gems INTEGER DEFAULT 0, roomid TEXT,"
        "history TEXT NOT NULL DEFAULT '')"
    ),
    "mysql": (
        "CREATE TABLE IF NOT EXISTS t_users ("
        "userid int(11) unsigned NOT NULL, account varchar(64) NOT NULL DEFAULT '',"
        "name varchar(32) DEFAULT NULL, sex int(1) DEFAULT NULL, headimg varchar(256) DEFAULT NULL,"
        "lv smallint(6) DEFAULT 1, exp int(11) DEFAULT 0, coins int(11) DEFAULT 0,"
        "gems int(11) DEFAULT 0, roomid varchar(8) DEFAULT NULL,"
        "history varchar(4096) NOT NULL DEFAULT '', PRIMARY KEY (userid),"
        "UNIQUE KEY account (account)) ENGINE=InnoDB DEFAULT CHARSET=utf8"
    ),
}

ROOM_COLUMNS = (
    "uuid, id, base_info, create_time, num_of_turns, next_button,"
    " user_id0, user_icon0, user_name0, user_score0,"
    " user_id1, user_icon1, user_name1, user_score1,"
    " user_id2, user_icon2, user_name2, user_score2,"
    " user_id3, user_icon3, user_name3, user_score3, ip, port"
)

INSERT_SQL = (
    f"INSERT INTO t_rooms ({ROOM_COLUMNS})"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
    " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _b64(name: str) -> str:
    """按游戏服的入库口径编码昵称（`t_rooms.user_nameN` 也是 Base64）。"""
    return base64.b64encode(name.encode("utf-8")).decode("ascii")


def _room(
    *,
    room_id: str,
    room_type: str,
    base_score: int,
    max_games: int,
    num_of_turns: int,
    creator: int,
    create_time: int,
    seats: tuple[tuple[int, str, int], ...],
) -> dict[str, Any]:
    """造一个房间夹具（`seats` 固定 4 项，空座位用 `(0, "", 0)`）。"""
    return {
        "uuid": f"1760000000000{room_id}",
        "room_id": room_id,
        "create_time": create_time,
        "num_of_turns": num_of_turns,
        "seats": seats,
        "conf": {
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
            "creator": creator,
        },
    }


#: 夹具：一个满座在打的房间、一个等玩家的房间、一个空房间。
#: `create_time` 递增顺序与列表里的房间号顺序**刻意相反**，好把排序测出来。
#: 第三个房间用"刚刚创建"的时间，用来验证概览里的"最近 24 小时"。
ROOMS: tuple[dict[str, Any], ...] = (
    _room(
        room_id="526035",
        room_type="xzdd",
        base_score=1,
        max_games=4,
        num_of_turns=2,
        creator=1001,
        create_time=1_700_000_000,
        seats=((1001, "玩家甲", 20), (1002, "玩家乙", 10), (1003, "玩家丙", 0), (1004, "玩家丁", -10)),
    ),
    _room(
        room_id="730112",
        room_type="xlch",
        base_score=2,
        max_games=8,
        num_of_turns=0,
        creator=1005,
        create_time=1_700_100_000,
        seats=((1005, "玩家戊", 0), (1006, "玩家己", 0), (0, "", 0), (0, "", 0)),
    ),
    _room(
        room_id="418899",
        room_type="xzdd",
        base_score=5,
        max_games=8,
        num_of_turns=0,
        creator=1003,
        create_time=int(time.time()) - 60,
        seats=((0, "", 0), (0, "", 0), (0, "", 0), (0, "", 0)),
    ),
)


def _room_rows() -> list[tuple[Any, ...]]:
    """把房间夹具转成 INSERT 参数。"""
    rows: list[tuple[Any, ...]] = []
    for room in ROOMS:
        seats: list[Any] = []
        for user_id, name, score in room["seats"]:
            seats.extend([user_id, "", _b64(name) if name else "", score])
        rows.append(
            (
                room["uuid"],
                room["room_id"],
                json.dumps(room["conf"], separators=(",", ":")),
                room["create_time"],
                room["num_of_turns"],
                0,
                *seats,
                "127.0.0.1",
                10000,
            )
        )
    return rows


class RoomTestBase(TestCase):
    """建房间表 + 夹具，并登录一个超级管理员。"""

    databases = {"default", PLAYER_DB}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        connection = connections[PLAYER_DB]
        ddl = CREATE_TABLE_SQL.get(connection.vendor)
        player_ddl = CREATE_PLAYER_TABLE_SQL.get(connection.vendor)
        if ddl is None or player_ddl is None:  # pragma: no cover - 只支持 sqlite / mysql
            raise unittest.SkipTest(f"未支持的玩家库后端：{connection.vendor}")
        with connection.cursor() as cursor:
            cursor.execute(ddl)
            cursor.execute(player_ddl)

    @classmethod
    def tearDownClass(cls) -> None:
        connection = connections[PLAYER_DB]
        with connection.cursor() as cursor:
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
        with connections[PLAYER_DB].cursor() as cursor:
            cursor.execute("DELETE FROM t_rooms")
            cursor.executemany(INSERT_SQL, _room_rows())

    def create_operator(self, username: str = "op") -> AdminUser:
        """建一个运营账号（默认角色 `operator`，只能看不能动房间）。"""
        return AdminUser.objects.create_user(
            username=username,
            password=PASSWORD,
            email=f"{username}@platform.local",
        )

    # ------------------------------------------------------------ 小工具

    def list_rooms(self, **params: Any) -> dict[str, Any]:
        """打列表接口并返回 `data`。"""
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["code"], 0, body)
        return body["data"]

    def room_ids(self, **params: Any) -> list[str]:
        """列表接口返回的房间号（按返回顺序）。"""
        return [item["room_id"] for item in self.list_rooms(**params)["items"]]

    def room_count(self) -> int:
        """测试库 `t_rooms` 的当前行数。"""
        with connections[PLAYER_DB].cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM t_rooms")
            return int(cursor.fetchone()[0])


class RoomListTests(RoomTestBase):
    """列表：搜索 / 过滤 / 排序 / 分页。"""

    def test_requires_login(self) -> None:
        """未登录返回 401 + 10002。"""
        response = APIClient().get(LIST_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)

    def test_returns_rooms_with_seats(self) -> None:
        """默认按创建时间倒序，并带上玩法 / 状态 / 座位 / 配置。"""
        data = self.list_rooms()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)
        self.assertEqual(data["pages"], 1)
        self.assertEqual([item["room_id"] for item in data["items"]], ["418899", "730112", "526035"])

        playing = next(item for item in data["items"] if item["room_id"] == "526035")
        self.assertEqual(playing["type"], "xzdd")
        self.assertEqual(playing["type_label"], "血战到底")
        self.assertEqual(playing["state"], "playing")
        self.assertEqual(playing["occupied_seats"], 4)
        self.assertEqual(playing["seat_count"], 4)
        self.assertEqual(playing["num_of_turns"], 2)
        self.assertEqual(playing["ip"], "127.0.0.1")
        self.assertEqual(playing["port"], 10000)
        self.assertEqual(playing["conf"]["base_score"], 1)
        self.assertEqual(playing["conf"]["max_games"], 4)
        self.assertEqual(playing["conf"]["creator"], 1001)
        self.assertEqual(
            [seat["name"] for seat in playing["seats"]],
            ["玩家甲", "玩家乙", "玩家丙", "玩家丁"],
        )
        self.assertEqual([seat["score"] for seat in playing["seats"]], [20, 10, 0, -10])
        self.assertTrue(all(seat["occupied"] for seat in playing["seats"]))
        # 时间戳是 Unix 秒，出参里已经格式化好（前端不做时区换算）。
        self.assertEqual(playing["create_time"], 1_700_000_000)
        self.assertRegex(playing["created_at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_decodes_base64_seat_name(self) -> None:
        """座位昵称要解码成可读文字，不能把 Base64 原样吐给前端。"""
        data = self.list_rooms(keyword="730112")
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["seats"][0]["name"], "玩家戊")
        self.assertNotEqual(data["items"][0]["seats"][0]["name"], _b64("玩家戊"))

    def test_empty_room_state(self) -> None:
        """一个座位都没人的房间是"未满座"，空座位的 player_id 是 0。"""
        item = self.list_rooms(keyword="418899")["items"][0]
        self.assertEqual(item["state"], "waiting")
        self.assertEqual(item["occupied_seats"], 0)
        self.assertEqual([seat["player_id"] for seat in item["seats"]], [0, 0, 0, 0])
        self.assertEqual([seat["occupied"] for seat in item["seats"]], [False] * 4)

    def test_keyword_by_room_id_uuid_and_seat_player(self) -> None:
        """搜索词命中房间号、uuid、座位上的玩家 ID 三种口径。"""
        self.assertEqual(self.room_ids(keyword="730112"), ["730112"])
        self.assertEqual(self.room_ids(keyword="1760000000000730112"), ["730112"])
        self.assertEqual(self.room_ids(keyword="1005"), ["730112"])
        # 1003 同时是房间 526035 的 2 号座位与房间 418899 的房主，命中前者的座位。
        self.assertEqual(self.room_ids(keyword="1003"), ["526035"])

    def test_keyword_by_seat_name(self) -> None:
        """非数字搜索词按座位昵称匹配（Base64 之后仍是前缀）。"""
        self.assertEqual(self.room_ids(keyword="玩家戊"), ["730112"])
        # 「玩家」是所有座位昵称的公共前缀，命中两个有人的房间。
        self.assertEqual(sorted(self.room_ids(keyword="玩家")), ["526035", "730112"])

    def test_keyword_no_match(self) -> None:
        """搜索不到时返回空列表而不是报错。"""
        data = self.list_rooms(keyword="no-such-room")
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_room_type_filter(self) -> None:
        """按玩法过滤（`conf.type` 落在 `base_info` 的紧凑 JSON 里）。"""
        self.assertEqual(self.room_ids(room_type="xlch"), ["730112"])
        self.assertEqual(sorted(self.room_ids(room_type="xzdd")), ["418899", "526035"])
        self.assertEqual(self.list_rooms(room_type="")["total"], 3)

    def test_state_filter(self) -> None:
        """按座位占用过滤。"""
        self.assertEqual(self.room_ids(state="playing"), ["526035"])
        self.assertEqual(sorted(self.room_ids(state="waiting")), ["418899", "730112"])
        self.assertEqual(self.list_rooms(state="all")["total"], 3)

    def test_filter_combined(self) -> None:
        """关键字、玩法、状态可以叠加。"""
        data = self.list_rooms(keyword="玩家", room_type="xzdd", state="playing")
        self.assertEqual([item["room_id"] for item in data["items"]], ["526035"])

    def test_ordering(self) -> None:
        """四种排序键都是白名单内的固定 SQL。"""
        self.assertEqual(self.room_ids(ordering="create_time"), ["526035", "730112", "418899"])
        self.assertEqual(self.room_ids(ordering="-num_of_turns")[0], "526035")
        self.assertEqual(self.room_ids(ordering="num_of_turns"), ["418899", "730112", "526035"])

    def test_pagination(self) -> None:
        """分页返回固定键集，第二页接上第一页。"""
        first = self.list_rooms(page=1, page_size=2)
        second = self.list_rooms(page=2, page_size=2)
        self.assertEqual(first["pages"], 2)
        self.assertEqual([item["room_id"] for item in first["items"]], ["418899", "730112"])
        self.assertEqual([item["room_id"] for item in second["items"]], ["526035"])

    def test_invalid_params_rejected(self) -> None:
        """非法参数按参数错误（10001）拒绝，而不是 500。"""
        for params in (
            {"page_size": 0},
            {"page_size": 100000},
            {"page": 0},
            {"state": "whatever"},
            {"room_type": "no-such-type"},
            {"ordering": "create_time; drop table t_rooms"},
        ):
            response = self.client.get(LIST_URL, params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.json()["code"], 10001, params)


class RoomDetailTests(RoomTestBase):
    """详情：房间号 / uuid 两种取法，以及预留入口说明。"""

    def test_detail_by_room_id(self) -> None:
        """按 6 位房间号取详情。"""
        response = self.client.get(f"{LIST_URL}526035/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["room_id"], "526035")
        self.assertEqual(data["type_label"], "血战到底")
        self.assertEqual(data["conf"]["max_games"], 4)
        self.assertEqual([seat["name"] for seat in data["seats"]], ["玩家甲", "玩家乙", "玩家丙", "玩家丁"])
        # 预留的运维入口在详情里就说明清楚，前端不必先点一次才知道。
        dissolve = data["actions"]["dissolve"]
        self.assertIs(dissolve["reserved"], True)
        self.assertIs(dissolve["available"], False)
        self.assertEqual(dissolve["feature"], "dissolve")
        self.assertIn("游戏服", dissolve["source"])

    def test_detail_by_uuid(self) -> None:
        """排查问题时手上可能只有 uuid，也要能查。"""
        data = self.client.get(f"{LIST_URL}1760000000000730112/").json()["data"]
        self.assertEqual(data["room_id"], "730112")
        self.assertEqual(data["uuid"], "1760000000000730112")

    def test_detail_not_found(self) -> None:
        """房间不存在返回 404 + 13001（房间打完后会从库里删掉，这是常态）。"""
        response = self.client.get(f"{LIST_URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 13001)

    def test_detail_invalid_room_ref(self) -> None:
        """形态不合法（非字母数字）按参数错误处理，而不是去查库。"""
        response = self.client.get(f"{LIST_URL}room%20with%20space/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_detail_requires_login(self) -> None:
        """详情也要登录。"""
        response = APIClient().get(f"{LIST_URL}526035/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class RoomOverviewTests(RoomTestBase):
    """概览数字。"""

    def test_overview_counts(self) -> None:
        """总数 / 满座 / 未满座 / 最近 24 小时新建。"""
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(data["total_rooms"], 3)
        self.assertEqual(data["playing_rooms"], 1)
        self.assertEqual(data["waiting_rooms"], 2)
        # 只有第三个房间是"刚刚创建"的，另外两个的时间戳在两年前。
        self.assertEqual(data["created_last_24h"], 1)

    def test_overview_empty(self) -> None:
        """一个房间都没有时全是 0，不是 null（`SUM` 在空集上返回 NULL）。"""
        with connections[PLAYER_DB].cursor() as cursor:
            cursor.execute("DELETE FROM t_rooms")
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(
            data,
            {"total_rooms": 0, "playing_rooms": 0, "waiting_rooms": 0, "created_last_24h": 0},
        )

    def test_overview_requires_login(self) -> None:
        """概览也要登录。"""
        response = APIClient().get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class RoomDissolveReservedTests(RoomTestBase):
    """预留的强制解散入口：契约、权限、以及"它什么都没做"。"""

    def test_returns_reserved_contract(self) -> None:
        """管理员调用返回 `reserved: true` 与计划实现。"""
        response = self.client.post(f"{LIST_URL}526035/dissolve/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertIs(data["reserved"], True)
        self.assertEqual(data["feature"], "dissolve")
        self.assertEqual(data["room_id"], "526035")
        self.assertEqual(data["uuid"], "1760000000000526035")
        self.assertIn("游戏服", data["source"])
        self.assertIn("预留", data["message"])

    def test_does_not_touch_the_room(self) -> None:
        """预留入口不写库：房间行必须原样还在。"""
        before = self.room_count()
        self.client.post(f"{LIST_URL}526035/dissolve/", {}, format="json")
        self.assertEqual(self.room_count(), before)
        self.assertEqual(self.room_ids(keyword="526035"), ["526035"])

    def test_unknown_room_rejected(self) -> None:
        """房间不在库里时返回 13001，而不是假装"已预留"。"""
        response = self.client.post(f"{LIST_URL}999999/dissolve/", {}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 13001)

    def test_requires_admin_role(self) -> None:
        """运营角色能看房间，但不能调解散入口（10003）。"""
        client = APIClient()
        client.force_authenticate(self.create_operator())

        self.assertEqual(client.get(LIST_URL).status_code, 200)

        response = client.post(f"{LIST_URL}526035/dissolve/", {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_requires_login(self) -> None:
        """未登录返回 401 + 10002。"""
        response = APIClient().post(f"{LIST_URL}526035/dissolve/", {}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class RoomSourceIsolationTests(RoomTestBase):
    """只读隔离：房间这条路径上不允许出现任何写操作。"""

    def test_read_only_guard_rejects_room_writes(self) -> None:
        """房间相关的写语句会被只读校验拦下（代码 bug 要立刻炸出来）。"""
        for sql in (
            "UPDATE t_rooms SET num_of_turns = 1",
            "DELETE FROM t_rooms WHERE id = '526035'",
            "INSERT INTO t_rooms (uuid, id) VALUES ('1', '2')",
            "SELECT 1; DELETE FROM t_rooms",
        ):
            with self.assertRaises(PlayerSourceReadOnlyViolation, msg=sql):
                player_source._assert_read_only(sql)

    def test_read_only_guard_accepts_generated_room_sql(self) -> None:
        """模块自己拼出来的房间 SQL 必须全部通过只读校验。"""
        for ordering in player_source.ROOM_ORDERING_CHOICES:
            rows, total = player_source.search_rooms(
                ordering=ordering, keyword="玩家", room_type="xzdd", state="playing"
            )
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["room_id"], "526035")
        player_source.room_overview()
        player_source.count_rooms()
        player_source.get_room("526035")
        player_source._assert_read_only(
            f"SELECT {player_source.ROOM_COLUMNS} FROM {player_source.ROOM_TABLE} LIMIT 1"
        )

    def test_every_room_db_query_is_select(self) -> None:
        """跑一遍房间接口，玩家库上执行的每一条 SQL 都是 SELECT。"""
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            self.client.get(LIST_URL)
            self.client.get(f"{LIST_URL}526035/")
            self.client.post(f"{LIST_URL}526035/dissolve/", {}, format="json")
            self.client.get(OVERVIEW_URL)

        self.assertGreater(len(captured.captured_queries), 0)
        for query in captured.captured_queries:
            sql = str(query["sql"]).strip()
            self.assertTrue(
                sql.lower().startswith("select"),
                f"玩家库上出现了非 SELECT 语句：{sql}",
            )

    def test_rooms_app_has_no_own_db_channel(self) -> None:
        """`apps/rooms` 不得自己连玩家库：SQL 只允许出现在 `player_source.py`。

        用 AST 读真实的 import，而不是在源码文本里找关键字（模块文档里正好写着
        "不 import 游戏服的访问层"这类句子）。
        """
        import ast
        import inspect

        from apps.rooms import serializers as rooms_serializers
        from apps.rooms import views as rooms_views

        banned_roots = {"utils", "aiomysql", "mysql", "pymysql"}
        for module in (rooms_views, rooms_serializers):
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


class InitPlayerDevRoomSeedTests(RoomTestBase):
    """离线开发命令也会给房间管理造样例数据。"""

    def test_seeds_rooms_on_sqlite(self) -> None:
        """SQLite 玩家库下写入样例房间，并能被接口查到。"""
        if connections[PLAYER_DB].vendor != "sqlite":
            self.skipTest("本命令只服务 SQLite 离线库")
        call_command("init_player_dev", "--reset")
        data = self.list_rooms(page_size=100)
        room_ids = {item["room_id"] for item in data["items"]}
        self.assertIn("526035", room_ids)
        self.assertIn("730112", room_ids)
        # 样例数据里刻意造了两种状态，方便把状态过滤试出来。
        self.assertGreaterEqual(self.list_rooms(state="playing")["total"], 1)
        self.assertGreaterEqual(self.list_rooms(state="waiting")["total"], 1)
        self.assertGreater(self.client.get(OVERVIEW_URL).json()["data"]["created_last_24h"], 0)


class RoomPlayerCrossCheckTests(RoomTestBase):
    """房间与玩家两条路径读的是**同一个玩家库**，但各查各的表。"""

    def test_player_db_still_only_used_read_only_across_apps(self) -> None:
        """房间接口跑完后，玩家库连接上依然只有 SELECT（含 players 那条路径）。"""
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            self.client.get("/api/players/")
            self.client.get(LIST_URL)
        self.assertGreater(len(captured.captured_queries), 0)
        for query in captured.captured_queries:
            self.assertTrue(str(query["sql"]).strip().lower().startswith("select"), query["sql"])
