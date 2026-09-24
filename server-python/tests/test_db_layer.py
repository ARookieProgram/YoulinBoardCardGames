"""`utils/db.py` 的访问层测试（离线，不连 MySQL）。

**背景（本文件存在的直接原因）**：大厅服的 `/get_games_of_room` 与
`/get_detail_of_game` 从移植第一天起就在调 `db.get_games_of_room` /
`db.get_detail_of_game`，而这两个函数在 `utils/db.py` 里**只有 `__all__` 里的名字、
没有实现**——客户端"战绩 → 回放"拿到的是 `AttributeError` 之后的 500，
而 Node 版一直有这两个函数，所以这是**移植遗漏**，不是有意保留的差异。

四组断言（全部读文本 / 打桩，不碰数据库）：

1. **导出即已实现**：`db.__all__` 里的每个名字都必须真的存在于模块上。
   这条通用断言一次性拦住"导出了但没实现"这一类遗漏——本 bug 就是它的第一个实例；
2. **跨实现同一张表、同一批列**：Python 版拼出来的 `SELECT` 投影，必须也是
   Node 版 `server/utils/db.ts` 里出现过的（两个实现查错表/查错列会立刻红）；
3. **行为契约照抄 Node**：参数为 `None` 时**不发 SQL** 直接返回 `None`；
   查不到行返回 `None`（客户端对 `null` 与空数组一视同仁）；
   详情有行时只取第一行；两个查询都只认归档表 `t_games_archive`；
4. **出错不炸进程**：`DbError` 时返回 `None`（见 `utils/db.py` 模块文档的第 2 条差异）。

运行方式与其它离线测试一致：

    .venv/bin/python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from utils import db  # noqa: E402

PY_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = PY_ROOT.parent
NODE_DB = REPO_ROOT / "server" / "utils" / "db.ts"

#: `SELECT <投影> FROM <表>` 的正则（Node 版的 SQL 是字符串拼接，投影与表名是字面量）。
_NODE_SELECT_RE = re.compile(r"SELECT ([A-Za-z_,]+) FROM (t_[a-z_]+)")

#: 老测试模块（`test_room_state` / `test_gamemgr_simulation` / `test_robot`）会把
#: `db.*` 整体换成桩。这里在 import 时先抓住真实的 `query`，每个用例结束时装回去，
#: 免得本文件把桩留给后面的测试（也会避免自己被别人的桩影响）。
_REAL_QUERY = db.query


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _node_selects() -> set[tuple[str, str]]:
    """Node 版 `db.ts` 里所有 `SELECT 投影 FROM 表` 的 (投影, 表) 组合。"""
    return {(projection.strip(), table) for projection, table in _NODE_SELECT_RE.findall(_read(NODE_DB))}


class DbExportTests(unittest.TestCase):
    """`__all__` 是调用方的契约，里面每个名字都必须真的有实现。"""

    def test_every_exported_name_exists(self) -> None:
        """`__all__` 里的名字一个都不能是"只声明没实现"。"""
        missing = [name for name in db.__all__ if not hasattr(db, name)]
        self.assertEqual(missing, [], f"db.__all__ 里这些名字没有实现：{missing}")

    def test_game_queries_are_asynchronous(self) -> None:
        """两个对局查询必须是协程（调用方是 `await db.…`）。"""
        import inspect

        for name in ("get_games_of_room", "get_detail_of_game"):
            function = getattr(db, name)
            self.assertTrue(inspect.iscoroutinefunction(function), f"{name} 必须是 async def")


class NodeParityTests(unittest.TestCase):
    """两个查询的口径必须与 Node 版一致（表名、投影列、只查归档表）。"""

    def test_projections_exist_in_node_implementation(self) -> None:
        """Python 用到的两个投影，Node 版也查的是同一张表的同一批列。"""
        node = _node_selects()
        self.assertIn(("game_index,create_time,result", "t_games_archive"), node)
        self.assertIn(("base_info,action_records", "t_games_archive"), node)


class _StubbedQueryTestCase(unittest.TestCase):
    """把 `db.query` 换成记录 SQL 的桩；每个用例结束把真实实现装回去。"""

    def setUp(self) -> None:
        self.captured: list[str] = []
        self.rows: list[dict[str, object]] = []
        self.error: Exception | None = None

        async def fake_query(sql: str) -> db.QueryResult:
            self.captured.append(sql)
            if self.error is not None:
                raise self.error
            return db.QueryResult(rows=list(self.rows), rowcount=len(self.rows), insert_id=0)

        db.query = fake_query  # type: ignore[assignment]

    def tearDown(self) -> None:
        db.query = _REAL_QUERY  # type: ignore[assignment]

    def call(self, coroutine: object) -> object:
        """跑一个协程（这些函数都是 `async def`，测试里逐次开事件循环）。"""
        return asyncio.run(coroutine)  # type: ignore[arg-type]


class GetGamesOfRoomTests(_StubbedQueryTestCase):
    """`get_games_of_room`：逐局战绩的三列投影。"""

    def test_none_uuid_does_not_touch_database(self) -> None:
        """uuid 为 None 时不发 SQL，直接返回 None（与 Node 版一致）。"""
        self.assertIsNone(self.call(db.get_games_of_room(None)))
        self.assertEqual(self.captured, [])

    def test_returns_rows_from_archive_table(self) -> None:
        """SQL 只查 `t_games_archive`，并把行原样返回（`result` 仍是 JSON 文本）。"""
        self.rows = [
            {"game_index": 0, "create_time": 1_700_000_000, "result": "[1,-1,0,0]"},
            {"game_index": 1, "create_time": 1_700_000_100, "result": "[0,0,2,-2]"},
        ]
        games = self.call(db.get_games_of_room("1760000000000526035"))
        self.assertEqual(len(self.captured), 1)
        sql = self.captured[0]
        self.assertIn("SELECT game_index,create_time,result FROM t_games_archive", sql)
        self.assertIn('room_uuid = "1760000000000526035"', sql)
        self.assertNotIn("FROM t_games ", sql)
        self.assertEqual([row["game_index"] for row in games], [0, 1])
        self.assertEqual(games[0]["result"], "[1,-1,0,0]")

    def test_empty_result_is_none(self) -> None:
        """查不到行返回 None（客户端对 null 与空数组一视同仁）。"""
        self.assertIsNone(self.call(db.get_games_of_room("1760000000000526035")))

    def test_db_error_is_swallowed(self) -> None:
        """数据库出错时返回 None，不把异常抛给 aiohttp。"""
        self.error = db.DbError("boom", "ER_BAD_FIELD_ERROR")
        self.assertIsNone(self.call(db.get_games_of_room("1760000000000526035")))
        self.assertEqual(len(self.captured), 1)


class GetDetailOfGameTests(_StubbedQueryTestCase):
    """`get_detail_of_game`：开局快照与出牌流水的两列投影。"""

    def test_missing_arguments_do_not_touch_database(self) -> None:
        """uuid / index 缺一就不发 SQL（与 Node 版的判空一致）。"""
        self.assertIsNone(self.call(db.get_detail_of_game(None, 0)))
        self.assertIsNone(self.call(db.get_detail_of_game("1760000000000526035", None)))
        self.assertEqual(self.captured, [])

    def test_returns_first_row_only(self) -> None:
        """主键是 `room_uuid + game_index`，最多一行；有行时取第一行。"""
        self.rows = [
            {"base_info": '{"type":"xzdd"}', "action_records": "[0,1,3]"},
            {"base_info": '{"type":"xlch"}', "action_records": "[]"},
        ]
        detail = self.call(db.get_detail_of_game("1760000000000526035", 1))
        self.assertEqual(len(self.captured), 1)
        sql = self.captured[0]
        self.assertIn("SELECT base_info,action_records FROM t_games_archive", sql)
        self.assertIn('room_uuid = "1760000000000526035"', sql)
        self.assertIn("AND game_index = 1", sql)
        self.assertEqual(detail["base_info"], '{"type":"xzdd"}')
        self.assertEqual(detail["action_records"], "[0,1,3]")

    def test_index_is_interpolated_verbatim(self) -> None:
        """`index` 来自查询串，照原实现直接拼进 SQL（形态不对时由 MySQL 报错）。"""
        self.rows = []
        self.call(db.get_detail_of_game("1760000000000526035", "abc"))
        self.assertIn("AND game_index = abc", self.captured[0])

    def test_empty_result_is_none(self) -> None:
        """没有这一局时返回 None。"""
        self.assertIsNone(self.call(db.get_detail_of_game("1760000000000526035", 3)))

    def test_db_error_is_swallowed(self) -> None:
        """数据库出错时返回 None。"""
        self.error = db.DbError("boom", "ER_BAD_FIELD_ERROR")
        self.assertIsNone(self.call(db.get_detail_of_game("1760000000000526035", 0)))
        self.assertEqual(len(self.captured), 1)


if __name__ == "__main__":  # pragma: no cover - 手工运行入口
    unittest.main()
