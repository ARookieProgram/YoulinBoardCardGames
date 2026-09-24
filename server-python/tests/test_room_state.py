"""解散房间后玩家必须真的从房间里出来（回归测试）。

背景：`roommgr.destroy()` 靠 `db.set_room_id_of_user(userId, None)` 把
`t_users.roomid` 清空。Python 移植版把 `None` 直接拼进 f-string，生成的是
`UPDATE t_users SET roomid = None ...`——MySQL 会把它当成一个不存在的列而报错，
于是"清空"这一步**静默失败**：玩家在库里仍然挂在已经解散的房间上，之后回大厅
再建房/进房会被大厅服以 `user is playing in room now.` 拒绝，看起来就是
"人还留在房间里没出来"。

这里把 `db.query` 换成只记录 SQL 的桩（不碰真实 MySQL），断言清空房间时拼的是
SQL 的 `null` 字面量，而不是 Python 的 `None` 文本，并顺带验证
`roommgr.destroy()` 会把每个座位从内存位置表里摘掉。

运行方式与其它离线测试一致：

    .venv/bin/python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from game_server import roommgr  # noqa: E402
from shared.domain import RoomConf, RoomInfo, RoomSeat  # noqa: E402
from utils import db  # noqa: E402


#: 其它测试模块（`test_gamemgr_simulation` / `test_robot`）会把
#: `db.set_room_id_of_user` / `db.delete_room` 整体换成 no-op 且**不还原**。
#: 这里在 import 时先抓住真实实现（此时还没有任何测试跑过），每个用例开始时装回去，
#: 免得本用例因为文件执行顺序而变成"测了个 no-op"。
_REAL_SET_ROOM_ID_OF_USER = db.set_room_id_of_user
_REAL_DELETE_ROOM = db.delete_room


def _capture_sql() -> list[str]:
    """把 `db.query` 换成记录 SQL 的桩，返回记录列表。"""
    captured: list[str] = []

    async def fake_query(sql: str) -> db.QueryResult:
        captured.append(sql)
        return db.QueryResult(rows=[], rowcount=0, insert_id=0)

    db.query = fake_query  # type: ignore[assignment]
    return captured


class _RealDbWritersMixin(unittest.TestCase):
    """把被其它测试换掉的真实 db 写入函数装回来，并在用例结束后还原现状。"""

    def setUp(self) -> None:
        saved_set = db.set_room_id_of_user
        saved_delete = db.delete_room
        db.set_room_id_of_user = _REAL_SET_ROOM_ID_OF_USER  # type: ignore[assignment]
        db.delete_room = _REAL_DELETE_ROOM  # type: ignore[assignment]

        def restore() -> None:
            db.set_room_id_of_user = saved_set  # type: ignore[assignment]
            db.delete_room = saved_delete  # type: ignore[assignment]

        self.addCleanup(restore)


class SetRoomIdOfUserTest(_RealDbWritersMixin):
    """`set_room_id_of_user` 拼出来的 SQL 必须能被 MySQL 执行。"""

    def setUp(self) -> None:
        super().setUp()
        original = db.query
        self.addCleanup(setattr, db, "query", original)
        self.sql = _capture_sql()

    def test_clearing_the_room_writes_the_sql_null_literal(self) -> None:
        asyncio.run(db.set_room_id_of_user(7, None))

        self.assertEqual(len(self.sql), 1)
        self.assertIn("roomid = null", self.sql[0])
        # Python 的 `None` 不是 SQL 关键字，拼进去就是 Unknown column 'None'。
        self.assertNotIn("None", self.sql[0])

    def test_setting_a_room_quotes_it(self) -> None:
        asyncio.run(db.set_room_id_of_user(7, "123456"))

        self.assertIn('roomid = "123456"', self.sql[0])


class DestroyRoomClearsPlayerStateTest(_RealDbWritersMixin):
    """销毁房间后，座位上的玩家要从内存位置表和库里都出去。"""

    def setUp(self) -> None:
        super().setUp()
        original = db.query
        self.addCleanup(setattr, db, "query", original)
        self.sql = _capture_sql()

        roommgr.reset()
        self.addCleanup(roommgr.reset)

        room = RoomInfo(
            uuid="testuuid",
            id="123456",
            numOfGames=0,
            createTime=0,
            nextButton=0,
            seats=[],
            conf=RoomConf(type="xlch"),
        )
        for index, user_id in enumerate([7, 8, 9, 10]):
            room.seats.append(RoomSeat(userId=user_id, name=f"玩家{index}", seatIndex=index))
            roommgr.user_location[user_id] = roommgr.UserLocation(
                roomId="123456", seatIndex=index
            )
        roommgr.rooms["123456"] = room

    def test_destroy_removes_every_seat_from_memory_and_db(self) -> None:
        asyncio.run(roommgr.destroy("123456"))

        for user_id in (7, 8, 9, 10):
            self.assertIsNone(
                roommgr.get_user_room(user_id), "玩家仍然留在被销毁的房间里"
            )
        self.assertIsNone(roommgr.get_room("123456"))

        clears = [sql for sql in self.sql if sql.startswith("UPDATE t_users SET roomid")]
        self.assertEqual(len(clears), 4, "没有替每个座位清空 t_users.roomid")
        for sql in clears:
            self.assertIn("roomid = null", sql)
            self.assertNotIn("None", sql)


if __name__ == "__main__":
    unittest.main()
