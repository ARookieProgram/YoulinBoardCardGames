"""玩家管理接口测试。

覆盖范围：

* 列表：搜索（账号 / 昵称 / 玩家ID）、封禁状态过滤、排序、分页、参数校验；
* 详情：玩家字段 + 封禁流水；不存在时 `12001`；
* 封禁 / 解封：写流水、状态流转、重复操作的业务码、角色下限（`10003`）；
* 概览：玩家总数与封禁中人数；
* 预留端点：充值记录的契约（`reserved: true`）且**不碰玩家库**
  （对局记录已搬到 `apps/games/`，见 `tests/test_games.py`）；
* **只读隔离**：玩家库那条路径上执行的每一条 SQL 都必须是 SELECT。

玩家夹具建在**玩家库别名**（`DATABASES["player"]`）的测试库上：SQLite 下是内存库，
MySQL 下是 `test_db_scmj`，**不会**碰真实的 `db_scmj`。表结构由本文件自己建——
管理平台在玩家库里没有任何模型与迁移，这正是隔离的体现。
"""

from __future__ import annotations

import base64
import unittest
from datetime import timedelta
from typing import Any

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.utils import OperationalError
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AdminUser
from apps.players import player_source
from apps.players.exceptions import PlayerSourceReadOnlyViolation
from apps.players.internal import build_sign
from apps.players.models import PlayerBan

LIST_URL = "/api/players/"
OVERVIEW_URL = "/api/players/overview/"
PASSWORD = "AdminPass!2024"
PLAYER_DB = player_source.PLAYER_DB_ALIAS

#: 建表语句：两种后端各一份（列与 `server/sql/db_babykylin.sql` 对齐）。
CREATE_TABLE_SQL = {
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

INSERT_SQL = (
    "INSERT INTO t_users"
    " (userid, account, name, sex, headimg, lv, exp, coins, gems, roomid, history)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

#: 夹具：(userid, account, 昵称, 等级, 金币, 房卡, 房间号)。
PLAYERS: tuple[tuple[int, str, str, int, int, int, str | None], ...] = (
    (1001, "guest_alpha", "玩家甲", 1, 1000, 21, "526035"),
    (1002, "guest_beta", "玩家乙", 3, 2500, 8, None),
    (1003, "guest_gamma", "玩家丙", 5, 300, 0, None),
    (1004, "wx_openid_004", "玩家丁", 2, 8800, 66, None),
)

#: 昵称在玩家库里是 Base64 存的（见 `utils/db.py` 的 `create_user`）。
def _name_b64(name: str) -> str:
    """按游戏服的入库口径编码昵称。"""
    return base64.b64encode(name.encode("utf-8")).decode("ascii")
def _player_rows() -> list[tuple[Any, ...]]:
    """把夹具转成 INSERT 参数。"""
    return [
        (userid, account, _name_b64(name), 0, None, lv, 0, coins, gems, roomid, "")
        for userid, account, name, lv, coins, gems, roomid in PLAYERS
    ]


class PlayerTestBase(TestCase):
    """建玩家表 + 夹具，并登录一个超级管理员。"""

    databases = {"default", PLAYER_DB}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        connection = connections[PLAYER_DB]
        ddl = CREATE_TABLE_SQL.get(connection.vendor)
        if ddl is None:  # pragma: no cover - 只支持 sqlite / mysql
            raise unittest.SkipTest(f"未支持的玩家库后端：{connection.vendor}")
        with connection.cursor() as cursor:
            cursor.execute(ddl)

    @classmethod
    def tearDownClass(cls) -> None:
        connection = connections[PLAYER_DB]
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS t_users")
        super().tearDownClass()

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = self.create_admin()
        self.client.force_authenticate(self.admin)
        with connections[PLAYER_DB].cursor() as cursor:
            cursor.execute("DELETE FROM t_users")
            cursor.executemany(INSERT_SQL, _player_rows())

    def create_admin(self, **overrides: Any) -> AdminUser:
        """建一个启用中的超级管理员（可覆盖邮箱等字段）。"""
        fields: dict[str, Any] = {
            "username": "admin",
            "password": PASSWORD,
            "email": "admin@platform.local",
            "nickname": "超级管理员",
        }
        fields.update(overrides)
        return AdminUser.objects.create_superuser(**fields)

    def create_operator(self, username: str = "op") -> AdminUser:
        """建一个运营账号（默认角色 `operator`，只能看不能封）。"""
        return AdminUser.objects.create_user(
            username=username,
            password=PASSWORD,
            email=f"{username}@platform.local",
        )

    # ------------------------------------------------------------ 小工具

    def list_players(self, **params: Any) -> dict[str, Any]:
        """打列表接口并返回 `data`。"""
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["code"], 0, body)
        return body["data"]

    def ban(self, player_id: int, **payload: Any) -> Any:
        """打封禁接口。"""
        return self.client.post(f"{LIST_URL}{player_id}/ban/", payload, format="json")

    def unban(self, player_id: int, **payload: Any) -> Any:
        """打解封接口。"""
        return self.client.post(f"{LIST_URL}{player_id}/unban/", payload, format="json")


class PlayerListTests(PlayerTestBase):
    """列表：搜索 / 过滤 / 排序 / 分页。"""

    def test_requires_login(self) -> None:
        """未登录返回 401 + 10002。"""
        client = APIClient()
        response = client.get(LIST_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)

    def test_returns_players_with_gems(self) -> None:
        """默认按 userid 倒序，并带上房卡（gems）数量。"""
        data = self.list_players()
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)
        self.assertEqual(data["pages"], 1)
        self.assertEqual([item["player_id"] for item in data["items"]], [1004, 1003, 1002, 1001])

        top = data["items"][0]
        self.assertEqual(top["account"], "wx_openid_004")
        self.assertEqual(top["gems"], 66)
        self.assertEqual(top["coins"], 8800)
        self.assertFalse(top["banned"])
        self.assertIsNone(top["ban"])

    def test_decodes_base64_nickname(self) -> None:
        """昵称要解码成可读文字，不能把 Base64 原样吐给前端。"""
        data = self.list_players(keyword="guest_beta")
        self.assertEqual(len(data["items"]), 1)
        item = data["items"][0]
        self.assertEqual(item["name"], "玩家乙")
        self.assertNotEqual(item["name"], _name_b64("玩家乙"))

    def test_keyword_by_account_userid_and_nickname(self) -> None:
        """搜索词同时匹配账号、昵称与纯数字 ID。"""
        by_account = self.list_players(keyword="gamma")
        self.assertEqual([item["player_id"] for item in by_account["items"]], [1003])

        by_id = self.list_players(keyword="1002")
        self.assertEqual([item["player_id"] for item in by_id["items"]], [1002])

        # 「玩家」是全部昵称的公共前缀，Base64 之后仍然是公共前缀（6 字节正好对齐）。
        by_name = self.list_players(keyword="玩家")
        self.assertEqual(by_name["total"], 4)

    def test_keyword_no_match(self) -> None:
        """搜索不到时返回空列表而不是报错。"""
        data = self.list_players(keyword="no-such-player")
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_ordering_by_gems(self) -> None:
        """可按房卡数量排序（运营最关心的一项）。"""
        data = self.list_players(ordering="-gems")
        self.assertEqual([item["gems"] for item in data["items"]], [66, 21, 8, 0])

    def test_pagination(self) -> None:
        """分页返回固定键集，第二页接上第一页。"""
        first = self.list_players(page=1, page_size=2)
        second = self.list_players(page=2, page_size=2)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual([item["player_id"] for item in first["items"]], [1004, 1003])
        self.assertEqual([item["player_id"] for item in second["items"]], [1002, 1001])

    def test_invalid_params_rejected(self) -> None:
        """非法参数按参数错误（10001）拒绝，而不是 500。"""
        for params in (
            {"page_size": 0},
            {"page_size": 100000},
            {"page": 0},
            {"ban_state": "whatever"},
            {"ordering": "userid; drop table t_users"},
        ):
            response = self.client.get(LIST_URL, params)
            self.assertEqual(response.status_code, 400, params)
            self.assertEqual(response.json()["code"], 10001, params)

    def test_ban_state_filter(self) -> None:
        """按封禁状态过滤时，玩家来自只读源、状态来自本平台库。"""
        self.ban(1002, reason="测试封禁")
        self.ban(1004, reason="测试封禁")

        banned = self.list_players(ban_state="banned")
        self.assertEqual([item["player_id"] for item in banned["items"]], [1004, 1002])
        self.assertTrue(all(item["banned"] for item in banned["items"]))
        self.assertEqual(banned["items"][0]["ban"]["reason"], "测试封禁")
        self.assertEqual(banned["items"][0]["ban"]["operator_name"], "admin")

        normal = self.list_players(ban_state="normal")
        self.assertEqual([item["player_id"] for item in normal["items"]], [1003, 1001])
        self.assertTrue(all(not item["banned"] for item in normal["items"]))

    def test_ban_state_filter_without_any_ban(self) -> None:
        """一条封禁记录都没有时，"封禁中"必须是空集而不是全表。"""
        data = self.list_players(ban_state="banned")
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_search_and_ban_filter_combined(self) -> None:
        """关键字与封禁状态可以叠加。"""
        self.ban(1003, reason="测试封禁")
        data = self.list_players(keyword="gamma", ban_state="banned")
        self.assertEqual([item["player_id"] for item in data["items"]], [1003])


class PlayerDetailTests(PlayerTestBase):
    """详情。"""

    def test_detail_ok(self) -> None:
        """详情返回玩家字段与（空）封禁流水。"""
        response = self.client.get(f"{LIST_URL}1003/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["player_id"], 1003)
        self.assertEqual(data["name"], "玩家丙")
        self.assertEqual(data["gems"], 0)
        self.assertFalse(data["banned"])
        self.assertEqual(data["ban_records"], [])

    def test_detail_includes_ban_history(self) -> None:
        """封禁 / 解封都进流水，倒序返回。"""
        self.ban(1001, reason="第一次封禁")
        self.unban(1001, reason="申诉通过")
        data = self.client.get(f"{LIST_URL}1001/").json()["data"]
        self.assertFalse(data["banned"])
        self.assertEqual([record["action"] for record in data["ban_records"]], ["unban", "ban"])
        self.assertEqual(data["ban_records"][0]["reason"], "申诉通过")
        self.assertEqual(data["ban_records"][1]["reason"], "第一次封禁")

    def test_detail_not_found(self) -> None:
        """玩家不存在返回 404 + 12001。"""
        response = self.client.get(f"{LIST_URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 12001)

    def test_detail_requires_login(self) -> None:
        """详情也要登录。"""
        response = APIClient().get(f"{LIST_URL}1001/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class PlayerBanTests(PlayerTestBase):
    """封禁 / 解封。"""

    def test_ban_creates_record(self) -> None:
        """封禁写一条流水，并立刻体现在列表与详情里。"""
        response = self.ban(1001, reason="使用外挂")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertTrue(body["data"]["banned"])
        self.assertEqual(body["data"]["ban"]["action"], "ban")
        self.assertIsNone(body["data"]["ban"]["expires_at"])

        record = PlayerBan.objects.get(player_id=1001)
        self.assertEqual(record.account, "guest_alpha")
        self.assertEqual(record.player_name, "玩家甲")
        self.assertEqual(record.reason, "使用外挂")
        self.assertEqual(record.operator_name, "admin")
        self.assertEqual(record.operator, self.admin)

        self.assertTrue(PlayerBan.is_banned(1001))
        self.assertTrue(self.client.get(f"{LIST_URL}1001/").json()["data"]["banned"])

    def test_ban_with_duration_sets_expiry(self) -> None:
        """限时封禁写入自动解封时间。"""
        self.ban(1001, reason="限时封禁", duration_hours=48)
        record = PlayerBan.objects.get(player_id=1001)
        self.assertIsNotNone(record.expires_at)
        assert record.expires_at is not None
        delta = record.expires_at - timezone.now()
        self.assertGreater(delta, timedelta(hours=47))
        self.assertLessEqual(delta, timedelta(hours=48))

    def test_ban_twice_rejected(self) -> None:
        """重复封禁返回 12002。"""
        self.ban(1001, reason="第一次")
        response = self.ban(1001, reason="第二次")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 12002)
        self.assertEqual(PlayerBan.objects.filter(player_id=1001).count(), 1)

    def test_ban_unknown_player(self) -> None:
        """封禁不存在的玩家返回 12001。"""
        response = self.ban(999999, reason="查无此人")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 12001)

    def test_ban_invalid_duration(self) -> None:
        """封禁时长超出上限按参数错误处理。"""
        response = self.ban(1001, duration_hours=24 * 365 + 1)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_unban_creates_record(self) -> None:
        """解封写一条流水，状态回到正常。"""
        self.ban(1001, reason="误封")
        response = self.unban(1001, reason="申诉通过")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertFalse(body["data"]["banned"])
        self.assertEqual(body["data"]["ban"]["action"], "unban")
        self.assertFalse(PlayerBan.is_banned(1001))
        self.assertEqual(PlayerBan.objects.filter(player_id=1001).count(), 2)

    def test_unban_without_ban_rejected(self) -> None:
        """没有封禁就解封返回 12003。"""
        response = self.unban(1001, reason="手滑")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 12003)

    def test_unban_unknown_player_rejected(self) -> None:
        """从没封过的玩家（甚至不存在）解封也是 12003，不是 12001。"""
        response = self.unban(999999)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 12003)

    def test_expired_ban_is_not_banned(self) -> None:
        """限时封禁到期后自动回到正常，且可以直接重新封禁。"""
        PlayerBan.objects.create(
            player_id=1002,
            account="guest_beta",
            player_name="玩家乙",
            action=PlayerBan.Action.BAN,
            reason="历史限时封禁",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(PlayerBan.is_banned(1002))
        self.assertFalse(self.client.get(f"{LIST_URL}1002/").json()["data"]["banned"])
        self.assertEqual(self.list_players(ban_state="banned")["total"], 0)

        response = self.ban(1002, reason="再次违规")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PlayerBan.is_banned(1002))

    def test_ban_requires_admin_role(self) -> None:
        """运营角色只能看，不能封禁 / 解封（10003）。"""
        client = APIClient()
        client.force_authenticate(self.create_operator())

        self.assertEqual(client.get(LIST_URL).status_code, 200)

        ban_response = client.post(f"{LIST_URL}1001/ban/", {"reason": "越权"}, format="json")
        self.assertEqual(ban_response.status_code, 403)
        self.assertEqual(ban_response.json()["code"], 10003)

        self.ban(1001, reason="管理员封的")
        unban_response = client.post(f"{LIST_URL}1001/unban/", {}, format="json")
        self.assertEqual(unban_response.status_code, 403)
        self.assertEqual(unban_response.json()["code"], 10003)


class PlayerOverviewTests(PlayerTestBase):
    """概览数字。"""

    def test_overview_counts(self) -> None:
        """玩家总数来自只读源，封禁数来自本平台库。"""
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(data["total_players"], 4)
        self.assertEqual(data["banned_players"], 0)

        self.ban(1004, reason="测试")
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(data["total_players"], 4)
        self.assertEqual(data["banned_players"], 1)

    def test_overview_requires_login(self) -> None:
        """概览也要登录。"""
        response = APIClient().get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class ReservedEndpointTests(PlayerTestBase):
    """预留入口：充值记录。

    对局记录**已经落地**，不在本应用里——它搬到了 `apps/games/`
    （`/api/games/players/<id>/`），测试见 `tests/test_games.py`。
    """

    def test_recharges_endpoint_contract(self) -> None:
        """充值记录入口同样已预留。"""
        response = self.client.get(f"{LIST_URL}1001/recharges/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIs(data["reserved"], True)
        self.assertEqual(data["feature"], "recharges")
        self.assertEqual(data["items"], [])
        for key in ("items", "total", "page", "page_size", "pages"):
            self.assertIn(key, data)

    def test_games_endpoint_is_gone(self) -> None:
        """`/api/players/<id>/games/` 已经搬走：它不该再是一份"预留"的空壳。"""
        response = self.client.get(f"{LIST_URL}1001/games/")
        self.assertEqual(response.status_code, 404)

    def test_reserved_endpoints_do_not_touch_player_db(self) -> None:
        """预留端点在数据源未接入前**不访问玩家库**（连一条 SQL 都不发）。"""
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            self.client.get(f"{LIST_URL}1001/recharges/")
        self.assertEqual(len(captured.captured_queries), 0)

    def test_reserved_endpoint_validates_pagination(self) -> None:
        """分页参数此刻就校验，接上数据源时前端不用改。"""
        response = self.client.get(f"{LIST_URL}1001/recharges/", {"page_size": 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_reserved_endpoint_requires_login(self) -> None:
        """预留端点同样需要登录。"""
        response = APIClient().get(f"{LIST_URL}1001/recharges/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class PlayerSourceUnavailableTests(PlayerTestBase):
    """玩家库不可用时要给出明确的业务码，而不是 500。"""

    def test_source_unavailable_returns_12004(self) -> None:
        """连不上玩家库 → 503 + 12004。"""
        from unittest.mock import patch

        with patch.object(connections[PLAYER_DB], "cursor", side_effect=OperationalError("boom")):
            response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], 12004)


class PlayerSourceIsolationTests(PlayerTestBase):
    """只读隔离：玩家库这条路径上不允许出现任何写操作。"""

    def test_read_only_guard_rejects_writes(self) -> None:
        """非 SELECT / 多语句 / 写关键字一律抛异常（代码 bug 要立刻炸出来）。"""
        for sql in (
            "UPDATE t_users SET gems = 0",
            "DELETE FROM t_users",
            "INSERT INTO t_users (userid) VALUES (1)",
            "SELECT 1; DROP TABLE t_users",
            "SELECT 1; UPDATE t_users SET gems = 0",
            "  truncate table t_users  ",
        ):
            with self.assertRaises(PlayerSourceReadOnlyViolation, msg=sql):
                player_source._assert_read_only(sql)

    def test_read_only_guard_accepts_generated_sql(self) -> None:
        """模块自己拼出来的 SQL 必须全部通过只读校验。"""
        for ordering in player_source.ORDERING_CHOICES:
            rows, total = player_source.search_players(ordering=ordering, only_ids=[1001])
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["player_id"], 1001)
        player_source._assert_read_only(
            f"SELECT {player_source.PLAYER_COLUMNS} FROM {player_source.PLAYER_TABLE}"
            " WHERE userid = %s LIMIT 1"
        )

    def test_every_player_db_query_is_select(self) -> None:
        """跑一遍列表 / 详情 / 封禁 / 解封，玩家库上执行的每一条 SQL 都是 SELECT。"""
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            self.client.get(LIST_URL)
            self.client.get(f"{LIST_URL}1001/")
            self.client.post(f"{LIST_URL}1001/ban/", {"reason": "测试"}, format="json")
            self.client.post(f"{LIST_URL}1001/unban/", {}, format="json")
            self.client.get(OVERVIEW_URL)

        self.assertGreater(len(captured.captured_queries), 0)
        for query in captured.captured_queries:
            sql = str(query["sql"]).strip()
            self.assertTrue(
                sql.lower().startswith("select"),
                f"玩家库上出现了非 SELECT 语句：{sql}",
            )

    def test_ban_records_live_in_platform_db(self) -> None:
        """封禁记录落在管理平台自己的表上，与玩家表没有外键关系。"""
        self.assertEqual(PlayerBan._meta.db_table, "players_playerban")
        self.ban(1001, reason="测试")
        self.assertEqual(PlayerBan.objects.using("default").count(), 1)
        # 玩家库里仍然只有 t_users（本平台不会往那边建表/写表）。
        connection = connections[PLAYER_DB]
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM t_users")
            self.assertEqual(cursor.fetchone()[0], len(PLAYERS))

    def test_module_does_not_import_game_server_db_layer(self) -> None:
        """不得复用游戏服的访问层（会绕过 Django 的连接与事务边界）。

        用 AST 读真实的 import 语句，而不是在源码文本里找关键字——
        模块文档里正好写了"不 import utils/db.py"这句话。
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(player_source))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertFalse(
            [name for name in imported if name.split(".")[0] == "utils"],
            f"player_source 不应 import 游戏服的模块：{sorted(imported)}",
        )
        self.assertFalse(
            [name for name in imported if name.split(".")[0] == "aiomysql"],
            f"player_source 不应自己开玩家库连接：{sorted(imported)}",
        )


class InitPlayerDevCommandTests(PlayerTestBase):
    """离线开发库的建表命令。"""

    def test_rejects_mysql_player_db(self) -> None:
        """MySQL 玩家库一律拒绝——避免误碰真实数据。"""
        if connections[PLAYER_DB].vendor == "sqlite":
            self.skipTest("SQLite 玩家库正是本命令的适用场景")
        with self.assertRaises(CommandError):
            call_command("init_player_dev")

    def test_seeds_sqlite_player_db(self) -> None:
        """SQLite 玩家库下写入样例玩家，并能被接口查到。"""
        if connections[PLAYER_DB].vendor != "sqlite":
            self.skipTest("本命令只服务 SQLite 离线库")
        call_command("init_player_dev", "--reset")
        data = self.list_players(page_size=100)
        accounts = {item["account"] for item in data["items"]}
        self.assertIn("guest_demo1", accounts)
        self.assertGreater(data["total"], len(PLAYERS))

    def test_seeds_with_query_logging_enabled(self) -> None:
        """命令里的 SQL 必须用 Django 的 `%s` 占位符，而不是 SQLite 的 `?`。

        `?` 只在 `executemany` 下侥幸能用：`execute` 一旦开启查询日志
        （DEBUG=True，或任何 `CaptureQueriesContext`）就会走
        `last_executed_query()` 的 `sql % params`，qmark 占位符会直接抛
        `TypeError: not all arguments converted during string formatting`。
        这个坑只在真实 `runserver`（DEBUG 默认开）下暴露，测试默认 DEBUG=False，
        所以这里显式把查询日志打开。
        """
        if connections[PLAYER_DB].vendor != "sqlite":
            self.skipTest("本命令只服务 SQLite 离线库")
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            call_command("init_player_dev", "--reset")
        self.assertGreater(len(captured.captured_queries), 0)
        # 样例是 6 个玩家（见 init_player_dev.SAMPLE_PLAYERS），`--reset` 之后只剩它们。
        self.assertEqual(self.list_players(page_size=100)["total"], 6)


INTERNAL_KEY = "test-internal-key"
BAN_CHECK_URL = "/api/internal/players/ban-check/"


def _sign(*, account: str = "", player_id: int | None = None, key: str = INTERNAL_KEY) -> str:
    """按内部接口的口径算签名（与游戏服两侧实现共用同一条公式）。"""
    return build_sign(account=account, player_id=player_id, key=key)


@override_settings(PLATFORM_INTERNAL_KEY=INTERNAL_KEY)
class InternalBanCheckTests(PlayerTestBase):
    """内部封禁校验接口：游戏服登录 / 进房前问的就是它。

    这是**游戏服与平台之间唯一的运行时契约**，所以既要钉住签名口径，
    也要钉住"只读、不需要 JWT、查不到就说不认识"这几条行为。
    """

    def setUp(self) -> None:
        super().setUp()
        # 内部接口不认 JWT：一律用没有登录态的客户端调用。
        self.anon = APIClient()

    def check(self, **params: Any) -> Any:
        """调内部接口。"""
        return self.anon.get(BAN_CHECK_URL, params)

    # ------------------------------------------------------------ 签名口径

    def test_sign_matches_reference_vectors(self) -> None:
        """签名必须与 Node 实现算出来的参考向量逐字一致。

        这三个常量是用 Node 的 crypto 算的（密钥取 configs 里的开发默认值），
        拼接顺序或字段标签改一位就会失败。同样的向量也钉在
        server-python/tests/test_protocol.py 与 tools/lib/smoke.mjs 里。
        """
        dev_key = "scmj-ban-check-dev-key"
        self.assertEqual(
            _sign(account="guest_123456", key=dev_key),
            "72977b2a422916d846f1f8b9bb10528d",
        )
        self.assertEqual(
            _sign(player_id=9, key=dev_key),
            "e16efd54aaddb8fb2aada5912ca306cd",
        )
        self.assertEqual(
            _sign(account="guest_123456", player_id=9, key=dev_key),
            "d4cb51c910c644dc4b29a94a62dded4b",
        )

    # ------------------------------------------------------------ 认证

    def test_rejects_missing_sign(self) -> None:
        """没有签名一律拒绝（10003），不放行。"""
        response = self.check(account="guest_alpha")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_rejects_wrong_sign(self) -> None:
        """签名不对（例如两边密钥不一致）返回 10003。"""
        response = self.check(account="guest_alpha", sign="0" * 32)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_rejects_sign_computed_with_other_key(self) -> None:
        """用别的密钥算出来的签名同样无效。"""
        response = self.check(account="guest_alpha", sign=_sign(account="guest_alpha", key="other"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_refuses_when_key_not_configured(self) -> None:
        """平台没配密钥时**拒绝服务**，绝不能变成人人可用的公开查询。"""
        with override_settings(PLATFORM_INTERNAL_KEY=""):
            response = self.check(account="guest_alpha", sign="0" * 32)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], 10500)

    def test_does_not_require_jwt(self) -> None:
        """内部接口不需要管理平台登录态（调用方是游戏服进程）。"""
        response = self.check(account="guest_alpha", sign=_sign(account="guest_alpha"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)

    # ------------------------------------------------------------ 参数

    def test_requires_account_or_player_id(self) -> None:
        """两个身份参数都不给 → 10001。"""
        response = self.check(sign=_sign(account=""))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_rejects_non_numeric_player_id(self) -> None:
        """player_id 必须是数字。"""
        response = self.check(player_id="abc", sign=_sign(account=""))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    # ------------------------------------------------------------ 查询

    def test_by_account_not_banned(self) -> None:
        """没被封的玩家：known=true、banned=false。"""
        data = self.check(account="guest_alpha", sign=_sign(account="guest_alpha")).json()["data"]
        self.assertTrue(data["known"])
        self.assertEqual(data["player_id"], 1001)
        self.assertFalse(data["banned"])
        self.assertEqual(data["reason"], "")
        self.assertIsNone(data["expires_at"])

    def test_by_account_banned(self) -> None:
        """被封的玩家：banned=true，并带上原因与自动解封时间。"""
        self.ban(1001, reason="使用外挂", duration_hours=48)
        data = self.check(account="guest_alpha", sign=_sign(account="guest_alpha")).json()["data"]
        self.assertTrue(data["banned"])
        self.assertEqual(data["player_id"], 1001)
        self.assertEqual(data["reason"], "使用外挂")
        self.assertIsNotNone(data["expires_at"])

    def test_by_player_id(self) -> None:
        """游戏服是从 token 里拿 userId 的，所以按 ID 查也必须可用。"""
        self.ban(1003, reason="恶意挂机")
        data = self.check(player_id=1003, sign=_sign(player_id=1003)).json()["data"]
        self.assertTrue(data["banned"])
        self.assertEqual(data["player_id"], 1003)
        self.assertEqual(data["reason"], "恶意挂机")

    def test_unknown_account(self) -> None:
        """查不到账号：known=false、banned=false（游戏服据此放行）。"""
        data = self.check(account="no-such-account", sign=_sign(account="no-such-account")).json()["data"]
        self.assertFalse(data["known"])
        self.assertIsNone(data["player_id"])
        self.assertFalse(data["banned"])

    def test_unbanned_after_unban(self) -> None:
        """解封之后立刻回答 banned=false，且不回带历史原因。"""
        self.ban(1001, reason="误封")
        self.unban(1001, reason="申诉通过")
        data = self.check(account="guest_alpha", sign=_sign(account="guest_alpha")).json()["data"]
        self.assertFalse(data["banned"])
        self.assertEqual(data["reason"], "")

    def test_expired_ban_is_not_banned(self) -> None:
        """限时封禁到期后自动回答"没封"（不需要定时任务）。"""
        PlayerBan.objects.create(
            player_id=1002,
            account="guest_beta",
            action=PlayerBan.Action.BAN,
            reason="历史限时封禁",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        data = self.check(account="guest_beta", sign=_sign(account="guest_beta")).json()["data"]
        self.assertFalse(data["banned"])

    def test_reads_player_db_read_only(self) -> None:
        """按账号查会回查玩家库，但那也必须全是 SELECT。"""
        with CaptureQueriesContext(connections[PLAYER_DB]) as captured:
            self.check(account="guest_alpha", sign=_sign(account="guest_alpha"))
        self.assertGreater(len(captured.captured_queries), 0)
        for query in captured.captured_queries:
            self.assertTrue(str(query["sql"]).strip().lower().startswith("select"), query["sql"])
