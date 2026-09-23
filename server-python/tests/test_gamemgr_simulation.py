"""整局模拟：不用 socket、不用数据库，直接把两份 gamemgr 跑到"牌局结束"。

这是移植后**最有价值的一条测试**：单元测试只能证明某个函数没写错，
只有真的把一局牌从 `begin` 驱动到 `game_over_push`，才能说明流程分支、
听牌判定、结算、落库调用这一整条链路是通的。

做法：

* 把 `usermgr` 的三个推送函数换成"记录下来"的假实现；
* 把 `utils.db` 里 gamemgr 用到的函数换成 no-op（测试不碰真实 MySQL）；
* 在 `roommgr` 里手工摆一个 4 人房间；
* 用一个极简机器人（能胡就胡、有操作就过、否则打第一张）把牌打完；
* 断言：跑到了 `game_over_push`、没有异常、`setTimeout` 里的收尾也执行了。

`xlch` 与 `xzdd` 各跑一遍（两份实现是并行维护的，任何一份跑不通都要拦住）。
"""

from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from game_server import roommgr, usermgr  # noqa: E402
from shared.domain import RoomConf, RoomInfo, RoomSeat  # noqa: E402
from utils import db  # noqa: E402

#: 一局最多走多少轮（真正的卡死判据是下面 400 次无状态变化的守卫）。
MAX_STEPS = 20000


class _Recorder:
    """把推送与踢人记录下来，代替真实 socket。"""

    def __init__(self) -> None:
        self.pushes: list[tuple[int, str, object]] = []
        self.kicks: list[str | None] = []

    async def send_msg(self, user_id: int, event: str, msgdata: object = None) -> None:
        self.pushes.append((user_id, event, msgdata))

    async def broacast_in_room(
        self, event: str, data: object, sender: int, including_sender: bool = False
    ) -> None:
        room_id = roommgr.get_user_room(sender)
        room = roommgr.get_room(room_id) if room_id else None
        if room is None:
            return
        for seat in room.seats:
            if seat.userId == sender and including_sender is not True:
                continue
            if seat.userId > 0:
                self.pushes.append((seat.userId, event, data))

    async def kick_all_in_room(self, room_id: str | None) -> None:
        self.kicks.append(room_id)

    def events_for(self, user_id: int) -> list[str]:
        return [event for uid, event, _ in self.pushes if uid == user_id]

    def all_events(self) -> list[str]:
        return [event for _, event, _ in self.pushes]


async def _noop(*args: object, **kwargs: object) -> bool:
    return True


async def _noop_none(*args: object, **kwargs: object) -> None:
    return None


async def _user_history(*args: object, **kwargs: object) -> list[object]:
    return []


def _install_stubs(recorder: _Recorder) -> None:
    """把 IO 边界都换掉：推送走 recorder，落库走 no-op。"""
    usermgr.send_msg = recorder.send_msg  # type: ignore[assignment]
    usermgr.broacast_in_room = recorder.broacast_in_room  # type: ignore[assignment]
    usermgr.kick_all_in_room = recorder.kick_all_in_room  # type: ignore[assignment]

    db.create_game = _noop_none  # type: ignore[assignment]
    db.update_game_result = _noop  # type: ignore[assignment]
    db.update_game_action_records = _noop  # type: ignore[assignment]
    db.update_num_of_turns = _noop  # type: ignore[assignment]
    db.update_next_button = _noop  # type: ignore[assignment]
    db.cost_gems = _noop  # type: ignore[assignment]
    db.archive_games = _noop  # type: ignore[assignment]
    db.delete_room = _noop  # type: ignore[assignment]
    db.set_room_id_of_user = _noop  # type: ignore[assignment]
    db.update_seat_info = _noop  # type: ignore[assignment]
    db.get_user_history = _user_history  # type: ignore[assignment]
    db.update_user_history = _noop  # type: ignore[assignment]


def _make_room(room_id: str, conf: RoomConf, user_ids: list[int]) -> RoomInfo:
    room = RoomInfo(
        uuid="testuuid" + room_id,
        id=room_id,
        numOfGames=0,
        createTime=0,
        nextButton=0,
        seats=[],
        conf=conf,
        gameMgr=None,
    )
    for index, user_id in enumerate(user_ids):
        room.seats.append(
            RoomSeat(userId=user_id, score=0, name=f"玩家{index}", ready=True, seatIndex=index)
        )
        roommgr.user_location[user_id] = roommgr.UserLocation(roomId=room_id, seatIndex=index)
    roommgr.rooms[room_id] = room
    # `begin()` 之后 gameMgr 才真正被用到，这里按 conf.type 懒加载
    room.gameMgr = roommgr.load_game_manager(conf.type)
    return room


def _speed_up_schedule(module: object) -> None:
    """把 gamemgr 里的 `_schedule(ms, fn)` 换成"立刻跑"。

    原实现用 500ms / 1500ms 的 `setTimeout` 让出牌与结算有个动画间隔；
    测试里等它会让一局牌跑几十秒。逻辑不变，只是不等。
    """

    def fast_schedule(delay_ms: int, fn: object) -> None:
        async def runner() -> None:
            await asyncio.sleep(0)
            await fn()  # type: ignore[operator]

        asyncio.get_running_loop().create_task(runner())

    module._schedule = fast_schedule  # type: ignore[attr-defined]


async def _drive_game(module: object, room_id: str, recorder: _Recorder) -> bool:
    """把一局牌打到结束；返回是否真的收到了 `game_over_push`。

    机器人只有三条规则：能胡就胡、有碰/杠就过、否则打一张牌（已经胡了的座位只能打刚摸的那张）。
    真卡住时会带着现场状态断言失败——这比"超过步数上限"有用得多。
    """
    game = module._games.get(room_id)  # type: ignore[attr-defined]
    last_signature: tuple[object, ...] | None = None
    stalled = 0

    for _ in range(MAX_STEPS):
        if game is None or room_id not in module._games:  # type: ignore[attr-defined]
            break
        if "game_over_push" in recorder.all_events():
            return True

        # 没有任何可观察变化时计数；连续太久说明真的挂住了
        signature = (
            game.state,
            game.turn,
            game.chuPai,
            game.currentIndex,
            tuple((s.canHu, s.canPeng, s.canGang, s.canChuPai, s.hued, len(s.holds)) for s in game.gameSeats),
        )
        stalled = stalled + 1 if signature == last_signature else 0
        last_signature = signature
        if stalled > 400:
            raise AssertionError(
                "牌局卡住（连续 400 次循环没有任何状态变化）："
                f"state={game.state} turn={game.turn} chuPai={game.chuPai} "
                f"currentIndex={game.currentIndex}/{len(game.mahjongs)} "
                f"qiangGangContext={'有' if game.qiangGangContext else '无'}\n"
                + "\n".join(
                    f"  座位{s.seatIndex} uid={s.userId} hued={s.hued} que={s.que} "
                    f"holds={len(s.holds)} folds={len(s.folds)} "
                    f"canHu={s.canHu} canPeng={s.canPeng} canGang={s.canGang} canChuPai={s.canChuPai}"
                    for s in game.gameSeats
                )
            )

        # 换三张
        if game.state == "huanpai":
            for seat in game.gameSeats:
                if seat.huanpais is None:
                    picks = seat.holds[:3]
                    await module.huan_san_zhang(seat.userId, picks[0], picks[1], picks[2])
            await asyncio.sleep(0)
            continue

        # 定缺：四个座位分别定不同的缺门，覆盖三条分支
        if game.state == "dingque":
            for index, seat in enumerate(game.gameSeats):
                if seat.que < 0:
                    await module.ding_que(seat.userId, index % 3)
            await asyncio.sleep(0)
            continue

        if game.state != "playing":
            await asyncio.sleep(0)
            continue

        # 先把所有"挂着操作"的座位处理掉：能胡就胡，否则过。
        # 注意**不能跳过已胡的座位**：血战到底里胡过的人还能继续胡，
        # 引擎会一直等他响应（`checkCanHu` 对四家都跑），跳过就会把牌局挂住。
        acted = False
        for seat in game.gameSeats:
            if seat.canHu:
                await module.hu(seat.userId)
                acted = True
            elif seat.canGang or seat.canPeng:
                await module.guo(seat.userId)
                acted = True
            if acted:
                break
        if acted:
            await asyncio.sleep(0)
            continue

        # 轮到谁就出一张牌
        turn_seat = game.gameSeats[game.turn]
        if turn_seat.canChuPai and turn_seat.holds:
            if turn_seat.hued:
                # 已经胡了的座位只能打"刚摸进来的那一张"（见 gamemgr.chu_pai 里的
                # 'only deal last one when hued.'）；随便打别的会被服务端拒绝、牌局卡死。
                pai = turn_seat.holds[-1]
            else:
                # 优先打缺门牌，便于尽快下叫（打不出来就退化成第一张）
                que = turn_seat.que
                pai = next(
                    (p for p in turn_seat.holds if module.get_mj_type(p) == que),
                    turn_seat.holds[0],
                )
            await module.chu_pai(turn_seat.userId, pai)
            # 让 500ms 的 setTimeout 闭包跑起来
            await asyncio.sleep(0.002)
            continue

        await asyncio.sleep(0)
        game = module._games.get(room_id)  # type: ignore[attr-defined]

    return "game_over_push" in recorder.all_events()


class FullGameSimulationTest(unittest.IsolatedAsyncioTestCase):
    """两份玩法实现各跑一局完整的四人牌。"""

    async def _run_one(self, module_name: str, room_type: str, hsz: int) -> None:
        module = importlib.import_module(module_name)
        _speed_up_schedule(module)

        recorder = _Recorder()
        _install_stubs(recorder)
        roommgr.reset()

        # 两个 gamemgr 共用模块级状态，跑一份前先清干净
        module._games.clear()  # type: ignore[attr-defined]
        module._game_seats_of_users.clear()  # type: ignore[attr-defined]

        room_id = "test01"
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
            creator=1001,
        )
        _make_room(room_id, conf, [1001, 1002, 1003, 1004])

        await module.begin(room_id)
        finished = await _drive_game(module, room_id, recorder)

        events = recorder.all_events()
        self.assertTrue(finished, f"{module_name}: 一局没有打完（共 {len(events)} 条推送）")
        # 开局与结算的关键推送都要出现过
        for expected in ("game_holds_push", "game_num_push", "game_begin_push", "game_over_push"):
            self.assertIn(expected, events, f"{module_name}: 缺少 {expected} 推送")

        # 结算里每个座位都要有一条结果
        over = [payload for _, event, payload in recorder.pushes if event == "game_over_push"]
        self.assertTrue(over, f"{module_name}: game_over_push 没有载荷")
        self.assertEqual(len(over[0]["results"]), 4, f"{module_name}: 结算结果不是 4 家")

    async def test_xlch_full_game_without_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xlch", "xlch", 0)

    async def test_xlch_full_game_with_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xlch", "xlch", 1)

    async def test_xzdd_full_game_without_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xzdd", "xzdd", 0)

    async def test_xzdd_full_game_with_huanpai(self) -> None:
        await self._run_one("game_server.gamemgr_xzdd", "xzdd", 1)


if __name__ == "__main__":
    unittest.main()
