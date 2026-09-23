"""单人模式（人机）的离线测试。

两层证据：

1. **纯策略单测**：定缺、换三张、出牌这些决策是纯函数，直接喂手牌断言，不需要事件循环；
2. **整局模拟**：把 4 个座位全交给 `robotmgr` 驱动，两份 gamemgr 各跑一局到 `game_over_push`。
   这是最有价值的一条——机器人只要有一个钩子点没接上，或者策略把某个座位卡在
   "有操作但不动"的状态上，这一局就跑不完。

模拟部分复用 `tests.test_gamemgr_simulation` 里那套"推送记录器 + 落库 no-op"的桩，
避免两份测试的桩各自漂移。
"""

from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from game_server import mjutils, robotmgr, roommgr, usermgr  # noqa: E402
from shared.domain import GameSeat, RoomConf, RoomInfo, RoomSeat  # noqa: E402
from tests.test_gamemgr_simulation import (  # noqa: E402
    _install_stubs,
    _make_room,
    _Recorder,
    _speed_up_schedule,
)

PY_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _seat(holds: list[int], que: int = -1) -> GameSeat:
    """按手牌造一个最小座位（只填策略真正读的字段）。"""
    count_map: dict[int, int] = {}
    for pai in holds:
        count_map[pai] = count_map.get(pai, 0) + 1
    return GameSeat(holds=list(holds), countMap=count_map, que=que)


class ChooseQueTest(unittest.TestCase):
    def test_picks_the_suit_with_fewest_tiles(self) -> None:
        # 筒 2 张 / 条 5 张 / 万 6 张 → 定缺筒（0）
        holds = [0, 8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23]
        self.assertEqual(robotmgr.choose_que(_seat(holds)), 0)

    def test_picks_the_missing_suit(self) -> None:
        # 一张万都没有 → 定缺万（2）
        holds = [0, 1, 2, 9, 10, 11, 12, 13, 14, 15, 16, 17, 8]
        self.assertEqual(robotmgr.choose_que(_seat(holds)), 2)


class ChooseHuanPaiTest(unittest.TestCase):
    def test_returns_three_tiles_of_one_suit(self) -> None:
        # 筒 4 张（最少）→ 应该从筒里挑三张
        holds = [0, 1, 2, 5, 9, 10, 11, 12, 13, 18, 19, 20, 21]
        picks = robotmgr.choose_huan_pai(_seat(holds))
        self.assertEqual(len(picks), 3)
        suits = {mjutils.get_mj_type(pai) for pai in picks}
        self.assertEqual(suits, {0}, f"换出去的牌不是同一门：{picks}")
        for pai in picks:
            self.assertIn(pai, holds)

    def test_keeps_pairs_and_drops_isolated_tiles(self) -> None:
        # 筒 5 张（0/1/2 + 一对 4）是最少的一门 → 从筒里挑三张，应该挑走孤张而不是拆对子
        holds = [0, 1, 2, 4, 4, 9, 10, 11, 12, 13, 14, 18, 19]
        picks = robotmgr.choose_huan_pai(_seat(holds))
        self.assertEqual(sorted(picks), [0, 1, 2], f"换牌没有优先换孤张：{picks}")


class ChooseDiscardTest(unittest.TestCase):
    def test_discards_que_suit_first(self) -> None:
        # 定缺条（1）→ 必须先从条里打
        holds = [0, 1, 2, 3, 10, 11, 12, 18, 19, 20, 21, 22, 23, 5]
        pai = robotmgr.choose_discard(_seat(holds, que=1))
        self.assertEqual(mjutils.get_mj_type(pai), 1)

    def test_keeps_pairs_drops_isolated_middle_tile(self) -> None:
        # 一对 5 筒、一对 2 条，孤立 7 条；没有缺门时应该打孤立张
        holds = [4, 4, 10, 10, 15, 0, 18, 19, 20, 21, 22, 23, 24]
        pai = robotmgr.choose_discard(_seat(holds, que=-1))
        self.assertNotIn(pai, (4, 10), f"打掉了对子：{pai}")

    def test_hued_player_must_discard_the_last_tile(self) -> None:
        # 血流成河里胡过的人只能打刚摸进来的那一张
        holds = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 12]
        seat = _seat(holds)
        seat.hued = True
        self.assertEqual(robotmgr.choose_discard(seat), 12)

    def test_empty_hand_returns_minus_one(self) -> None:
        self.assertEqual(robotmgr.choose_discard(_seat([])), -1)


class RobotRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        robotmgr.reset()

    def test_allocated_ids_are_unique_and_registered_ids_are_robots(self) -> None:
        ids = robotmgr.allocate_ids(3)
        self.assertEqual(len(set(ids)), 3)
        for user_id in ids:
            self.assertFalse(robotmgr.is_robot(user_id))
            robotmgr.register(user_id)
            self.assertTrue(robotmgr.is_robot(user_id))
            self.assertTrue(usermgr.is_online(user_id))
        self.assertFalse(robotmgr.is_robot(1))


class SeatRobotsTest(unittest.IsolatedAsyncioTestCase):
    """`roommgr._seat_robots` 是"单人房自动匹配三个机器人"的落地点。"""

    async def test_seats_three_robots_leaving_seat_zero_for_the_human(self) -> None:
        recorder = _Recorder()
        _install_stubs(recorder)
        roommgr.reset()
        robotmgr.reset()

        room = RoomInfo(
            uuid="uuid-single",
            id="single01",
            seats=[RoomSeat(seatIndex=i) for i in range(4)],
            conf=RoomConf(type="xzdd", single=1),
        )
        roommgr.rooms[room.id] = room

        await roommgr._seat_robots(room)

        self.assertEqual(room.seats[0].userId, 0, "0 号位必须留给真人")
        for index in (1, 2, 3):
            seat = room.seats[index]
            self.assertGreater(seat.userId, 0)
            self.assertTrue(seat.ready, f"{index} 号位的机器人应当直接是已准备")
            self.assertTrue(robotmgr.is_robot(seat.userId))
            self.assertTrue(usermgr.is_online(seat.userId))
            self.assertEqual(roommgr.get_user_room(seat.userId), room.id)
            self.assertEqual(roommgr.get_user_seat(seat.userId), index)


class SingleRoomRouteTest(unittest.TestCase):
    """大厅服的 `/create_single_room` 必须真的挂上去。

    这里只读源码做文本断言（与 `test_protocol.py` 里扫事件名的做法一致），
    不 import aiohttp 应用：那需要 aiomysql，会让"没有依赖的解释器跑门禁"这一约定失效。
    """

    def test_route_is_registered(self) -> None:
        source = (PY_ROOT / "hall_server" / "client_service.py").read_text(encoding="utf-8")
        self.assertIn('add_get("/create_single_room"', source)
        self.assertIn('conf["single"] = 1', source)


class RobotFullGameTest(unittest.IsolatedAsyncioTestCase):
    """四个座位全交给机器人，把一局牌从 `begin` 打到 `game_over_push`。"""

    async def _run_one(self, module_name: str, room_type: str, hsz: int) -> None:
        module = importlib.import_module(module_name)
        _speed_up_schedule(module)

        recorder = _Recorder()
        _install_stubs(recorder)
        roommgr.reset()
        robotmgr.reset()
        robotmgr.set_think_time(0, 0)

        # 两个 gamemgr 共用模块级状态，跑一份前先清干净
        module._games.clear()  # type: ignore[attr-defined]
        module._game_seats_of_users.clear()  # type: ignore[attr-defined]

        robot_ids = robotmgr.allocate_ids(4)
        for user_id in robot_ids:
            robotmgr.register(user_id)

        room_id = "robottest"
        conf = RoomConf(
            type=room_type,
            baseScore=2,
            zimo=0,
            jiangdui=1,
            hsz=hsz,
            dianganghua=0,
            menqing=1,
            tiandihu=1,
            maxFan=4,
            maxGames=4,
            creator=robot_ids[0],
            single=1,
        )
        _make_room(room_id, conf, robot_ids)

        await module.begin(room_id)

        for _ in range(20000):
            if "game_over_push" in recorder.all_events():
                break
            await asyncio.sleep(0)
        else:
            game = module._games.get(room_id)  # type: ignore[attr-defined]
            detail = "已结束"
            if game is not None:
                detail = (
                    f"state={game.state} turn={game.turn} chuPai={game.chuPai} "
                    f"currentIndex={game.currentIndex}/{len(game.mahjongs)}\n"
                    + "\n".join(
                        f"  座位{s.seatIndex} uid={s.userId} hued={s.hued} que={s.que} "
                        f"holds={len(s.holds)} canHu={s.canHu} canPeng={s.canPeng} "
                        f"canGang={s.canGang} canChuPai={s.canChuPai}"
                        for s in game.gameSeats
                    )
                )
            self.fail(f"{module_name}: 机器人没有把这一局打完（{detail}）")

        over = [payload for _, event, payload in recorder.pushes if event == "game_over_push"]
        self.assertTrue(over, f"{module_name}: game_over_push 没有载荷")
        self.assertEqual(len(over[0]["results"]), 4, f"{module_name}: 结算结果不是 4 家")

    async def test_xzdd_robot_game_without_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xzdd", "xzdd", 0)

    async def test_xzdd_robot_game_with_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xzdd", "xzdd", 1)

    async def test_xlch_robot_game_without_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xlch", "xlch", 0)

    async def test_xlch_robot_game_with_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xlch", "xlch", 1)

    async def test_robots_stay_ready_so_the_next_game_can_start(self) -> None:
        """打完一局后机器人必须仍是"已准备"。

        `do_game_over` 会把四个座位都重置成未准备；如果机器人跟着一起被重置，
        而它们又不会自己点"准备"，第二局就永远开不起来。
        """
        module = importlib.import_module("game_server.gamemgr_xzdd")
        _speed_up_schedule(module)

        recorder = _Recorder()
        _install_stubs(recorder)
        roommgr.reset()
        robotmgr.reset()
        robotmgr.set_think_time(0, 0)
        module._games.clear()  # type: ignore[attr-defined]
        module._game_seats_of_users.clear()  # type: ignore[attr-defined]

        robot_ids = robotmgr.allocate_ids(4)
        for user_id in robot_ids:
            robotmgr.register(user_id)

        conf = RoomConf(
            type="xzdd",
            baseScore=1,
            maxGames=4,
            creator=robot_ids[0],
            single=1,
        )
        room_id = "robotnext"
        room = _make_room(room_id, conf, robot_ids)

        await module.begin(room_id)
        for _ in range(20000):
            if "game_over_push" in recorder.all_events():
                break
            await asyncio.sleep(0)
        self.assertIn("game_over_push", recorder.all_events(), "第一局没有打完")

        self.assertNotIn(room_id, module._games)  # type: ignore[attr-defined]
        for seat in room.seats:
            self.assertTrue(seat.ready, f"座位{seat.seatIndex} 打完一局后没有保持已准备")

        # 真人点了"准备"之后，第二局应当立刻开起来
        await module.set_ready(robot_ids[0])
        self.assertIn(room_id, module._games)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
