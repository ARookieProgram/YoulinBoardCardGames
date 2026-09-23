"""单人模式的机器人（人机）驱动。

服务端没有"AI 玩家"这种实体，机器人就是**没有 socket 的普通座位**：

* `roommgr.create_room` 在建单人房时把它们安排到 1~3 号座位（0 号留给真人），
  `ready=True` 并写进 `user_location`，所以 `roommgr.get_user_room` 之类的查询照常可用；
* `usermgr.is_online` 对它们返回 True——否则 `gamemgr.set_ready` 里"四人齐且都在线"的
  判断永远过不去、牌局开不了；但它们的推送会因为在线的 socket 表里查不到连接而被静默丢弃，
  机器人不需要收推送；
* 真正的动作由本模块在**固定的流程钩子点**被唤醒：gamemgr 在"某个座位被要求做决定"时调用
  `schedule(game, seat, actions)`（见 `send_operations` / `begin` / `huan_san_zhang` / `peng`），
  本模块延迟一小段时间后按下面的策略回调 gamemgr 的动作函数。

策略刻意做得简单且**确定性**（不掷骰子）：

1. 能胡就胡；
2. 有别人能胡时先过（`peng`/`gang` 在游戏里本来就会被"有人能胡"挡回来，必须先判，
   否则机器人会卡在"有操作但不动"的状态上把牌局挂住）；
3. 能杠就杠、能碰就碰；
4. 出牌先打缺门，否则打"最没用"的一张（孤张优先，留对子/刻子/搭子）。

它们的作用是**把牌局推下去**，不是打得好看。要打得聪明需要牌型评估，属于后续增强。

> 这个文件目前只在 `server-python/` 有对应实现（Node 版 `server/` 尚未实现单人模式）。
> 若以后要补 Node 版，本文件的策略与钩子点可以逐个照搬。
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from game_server import mjutils
from shared.domain import GameSeat, GameState

if TYPE_CHECKING:
    from shared.domain import RoomInfo

#: gamemgr 的动作函数（都是协程），由各份 gamemgr 在文件末尾组装成 `RobotActions` 传进来。
RobotAction = Callable[..., Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class RobotActions:
    """机器人可以回调的对局动作，与 `GameManagerProtocol` 里同名的那几个一一对应。"""

    huan_san_zhang: RobotAction
    ding_que: RobotAction
    chu_pai: RobotAction
    peng: RobotAction
    gang: RobotAction
    hu: RobotAction
    guo: RobotAction


#: 机器人 userId 的起始值。真实用户的 userid 是 `t_users` 的自增主键（从 1 开始），
#: 这里取一个远大于它、又没有超出 INT 范围的偏移量，两边不会撞号。
ROBOT_ID_BASE = 900000

#: 座位上的显示名（1~3 号机器人按顺序取）。
ROBOT_NAMES = ("机器人·东风", "机器人·南风", "机器人·西风")

_robots: set[int] = set()
_next_robot_id = ROBOT_ID_BASE

#: 已经排了决定、还没开始执行的座位（同一座位同时只排一个）。
_pending: set[int] = set()
#: 后台任务的强引用（不保留引用的话任务可能被 GC 掉）。
_tasks: set[asyncio.Task[None]] = set()

#: 机器人"思考"的延迟。延迟有两个作用：让牌局看起来不像瞬间跑完；
#: 把"出牌 → 下一家摸牌 → 再出牌"的递归变成异步，避免深递归。
_THINK_MS = 900
_JITTER_MS = 300


def allocate_ids(count: int) -> list[int]:
    """分配 `count` 个机器人 userId（同一进程内不重复）。"""
    global _next_robot_id
    ids: list[int] = []
    for _ in range(count):
        ids.append(_next_robot_id)
        _next_robot_id += 1
    return ids


def robot_name(index: int) -> str:
    """第 `index`（从 0 起）个机器人的显示名。"""
    if 0 <= index < len(ROBOT_NAMES):
        return ROBOT_NAMES[index]
    return "机器人" + str(index + 1)


def register(user_id: int) -> None:
    """把一个 userId 标记成机器人（建房落座时调用）。"""
    _robots.add(user_id)


def is_robot(user_id: int) -> bool:
    """这个 userId 是不是机器人（`usermgr.is_online` 也查它）。"""
    return user_id in _robots


def set_think_time(think_ms: int, jitter_ms: int = 0) -> None:
    """改机器人思考延迟（只给测试用：设成 0 就不用等）。"""
    global _THINK_MS, _JITTER_MS
    _THINK_MS = think_ms
    _JITTER_MS = jitter_ms


def reset() -> None:
    """清空机器人表与调度状态（只给测试用；进程里靠房间销毁）。"""
    global _next_robot_id
    _robots.clear()
    _pending.clear()
    _next_robot_id = ROBOT_ID_BASE


def auto_agree_dissolve(room_info: RoomInfo) -> bool:
    """让房间里所有机器人座位立刻同意当前的解散申请。

    机器人没有 socket，`dissolve_request` 之后**不会有任何 `dissolve_agree` 上来**：
    真人是房主时，四个 `states` 永远停在三个 `False` 上，解散只能靠
    `gamemgr._update()` 熬满 30 秒超时才生效。这里把机器人座位直接置为已同意，
    把"机器人玩家自动同意"变成一次即时判断。

    只在 `room_info.dr` 存在时改写；返回**是否四家都已同意**——调用方据此决定
    要不要马上走 `do_dissolve`（不能再等超时，否则客户端那三个"[待确认]"会白挂 30 秒）。
    """
    dr = room_info.dr
    if dr is None:
        return False

    for seat in room_info.seats:
        if seat.seatIndex >= len(dr.states):
            continue
        if is_robot(seat.userId):
            dr.states[seat.seatIndex] = True

    return all(dr.states)


# ---------------------------------------------------------------------------
# 决策（纯函数，不碰 IO，可直接单测）
# ---------------------------------------------------------------------------


def count_by_suit(holds: list[int]) -> list[int]:
    """三门（筒/条/万）各自的张数。"""
    counts = [0, 0, 0]
    for pai in holds:
        suit = mjutils.get_mj_type(pai)
        if suit is not None:
            counts[suit] += 1
    return counts


def choose_que(seat: GameSeat) -> int:
    """定缺：张数最少的一门（并列时取靠前的一门）。"""
    counts = count_by_suit(seat.holds)
    return min(range(3), key=lambda suit: (counts[suit], suit))


def choose_huan_pai(seat: GameSeat) -> tuple[int, int, int]:
    """换三张：从"张数最少的那一门"里挑三张最没用的换出去。

    规则要求三张同花色；13 张牌分三门，必有一门 >= 5 张（抽屉原理），所以一定选得出来。
    """
    holds = seat.holds
    counts = count_by_suit(holds)
    suits = [suit for suit in range(3) if counts[suit] >= 3]
    if not suits:
        # 理论上到不了这里；真到了就退化成"随便三张"，不抛异常把牌局挂住。
        return holds[0], holds[1], holds[2]
    target = min(suits, key=lambda suit: (counts[suit], suit))
    tiles = [pai for pai in holds if mjutils.get_mj_type(pai) == target]
    tiles.sort(key=lambda pai: (tile_score(seat, pai), pai))
    return tiles[0], tiles[1], tiles[2]


def choose_gang(seat: GameSeat) -> int:
    """挑一张能杠的牌：能暗杠优先（4 张在手），其次是弯杠/点杠。"""
    for pai in seat.gangPai:
        if seat.countMap.get(pai) == 4:
            return pai
    return seat.gangPai[0]


def should_peng(seat: GameSeat) -> bool:
    """要不要碰。

    这里刻意只用"能碰就碰"这一条：机器人不是来打好看牌的，是要把牌局推下去。
    真正的取舍（碰了会不会拆搭子、会不会失去门清）需要牌型评估，属于后续增强。
    """
    return True


def choose_discard(seat: GameSeat) -> int:
    """出牌：胡了只能打刚摸的那张；否则先打缺门，再从候选里挑最没用的一张。

    :return: 牌 id；手上没牌时返回 -1（调用方据此跳过出牌）。
    """
    holds = seat.holds
    if not holds:
        return -1

    # 血流成河（xlch）里胡过的玩家还要继续打，且只能打刚摸进来的那一张
    # （见 gamemgr_xlch.chu_pai 的 'only deal last one when hued.'）。
    if seat.hued:
        return holds[-1]

    que = seat.que
    que_tiles = [pai for pai in holds if mjutils.get_mj_type(pai) == que]
    candidates = que_tiles if que_tiles else holds
    return min(
        candidates,
        key=lambda pai: (tile_score(seat, pai), seat.countMap.get(pai, 0), pai),
    )


def tile_score(seat: GameSeat, pai: int) -> int:
    """一张牌的"用处"打分：分越低越该打出去。

    * 对子 / 刻子 / 杠 加分（留着）；
    * 同花色相邻或隔一张的牌加分（搭子）；
    * 幺九张减分（边张，价值低）。
    """
    count_map = seat.countMap
    count = count_map.get(pai, 0)
    score = 0
    if count >= 2:
        score += 8
    if count >= 3:
        score += 4
    if count >= 4:
        score += 4

    suit = mjutils.get_mj_type(pai)
    for offset in (-2, -1, 1, 2):
        neighbor = pai + offset
        # 隔门不算搭子（例如 8 筒 + 9 条）
        if mjutils.get_mj_type(neighbor) != suit:
            continue
        if count_map.get(neighbor, 0) > 0:
            score += 4 if (offset == -1 or offset == 1) else 2

    rank = pai % 9
    if rank == 0 or rank == 8:
        score -= 1
    return score


# ---------------------------------------------------------------------------
# 调度：gamemgr 在"该某个座位做决定"时调用 schedule()
# ---------------------------------------------------------------------------


def schedule(game: GameState, seat: GameSeat | None, actions: RobotActions) -> None:
    """把"这个座位该做决定了"排进机器人队列。

    * 不是机器人、或 `seat` 已经换了一局（`begin` 会重建座位对象）→ 什么都不做；
    * 同一座位已经排了一个还没开始执行的决定 → 跳过。后发生的决定不需要单独排队：
      那个任务执行时会读到最新状态，自然把它一起处理掉。
    """
    if seat is None or not is_robot(seat.userId):
        return
    if seat.game is not game:
        return
    if seat.userId in _pending:
        return

    _pending.add(seat.userId)
    delay = (_THINK_MS + random.random() * _JITTER_MS) / 1000
    task = asyncio.get_running_loop().create_task(_run_later(delay, game, seat, actions))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run_later(
    delay: float, game: GameState, seat: GameSeat, actions: RobotActions
) -> None:
    await asyncio.sleep(delay)
    # 先解除"已排队"标记再执行：机器人自己的动作可能立刻又给它排一个新的决定
    # （例如"过"之后轮到自己出牌就是这么走的），带着标记执行会把那次调度丢掉、把牌局挂住。
    _pending.discard(seat.userId)
    await take_action(game, seat, actions)


async def take_action(game: GameState, seat: GameSeat, actions: RobotActions) -> None:
    """按当前对局状态执行一次决定：只做判断并回调 gamemgr，不直接改对局数据。"""
    if not is_robot(seat.userId) or seat.game is not game:
        return

    # ---- 开局阶段：换三张 / 定缺 ----
    if game.state == "huanpai":
        if seat.huanpais is None:
            p1, p2, p3 = choose_huan_pai(seat)
            await actions.huan_san_zhang(seat.userId, p1, p2, p3)
        return

    if game.state == "dingque":
        if seat.que < 0:
            await actions.ding_que(seat.userId, choose_que(seat))
        return

    if game.state != "playing":
        return

    # ---- 对局中 ----
    # 1) 能胡就胡
    if seat.canHu:
        await actions.hu(seat.userId)
        return

    # 2) 轮到自己出牌（摸完牌）：这个状态下引擎保证没有别人在等胡，不用避让
    if seat.canChuPai:
        if seat.canGang and seat.gangPai:
            await actions.gang(seat.userId, choose_gang(seat))
            return
        if seat.canPeng or seat.canGang:
            # 有操作但都不做：必须先过，`chu_pai` 里"有操作就不许出牌"的检查才过得去。
            # 过完还是自己的回合（`guo` 对"自己回合"只清操作、不推进），接着出牌。
            await actions.guo(seat.userId)
        pai = choose_discard(seat)
        if pai >= 0:
            await actions.chu_pai(seat.userId, pai)
        return

    # 3) 接别人打出的牌
    #    有别人能胡时不碰不杠：`peng` / `gang` 里本来就会因为"有人能胡"直接返回，
    #    机器人必须先判这一步，否则会停在"有操作但没动作"的状态上，牌局没人再推。
    if _others_can_hu(game, seat):
        if seat.canPeng or seat.canGang:
            await actions.guo(seat.userId)
        return

    # 4) 能杠就杠
    if seat.canGang and seat.gangPai:
        await actions.gang(seat.userId, choose_gang(seat))
        return

    # 5) 能碰就碰
    if seat.canPeng and should_peng(seat):
        await actions.peng(seat.userId)
        return

    # 6) 有操作但都不做 → 过（过完牌局由引擎推进到下一家）
    if seat.canPeng or seat.canGang:
        await actions.guo(seat.userId)


def _others_can_hu(game: GameState, seat: GameSeat) -> bool:
    """除自己以外，是否还有座位处于"可以胡"的等待状态。"""
    for other in game.gameSeats:
        if other is seat:
            continue
        if other.canHu:
            return True
    return False


__all__ = [
    "ROBOT_ID_BASE",
    "ROBOT_NAMES",
    "RobotActions",
    "allocate_ids",
    "auto_agree_dissolve",
    "choose_discard",
    "choose_gang",
    "choose_huan_pai",
    "choose_que",
    "count_by_suit",
    "is_robot",
    "register",
    "reset",
    "robot_name",
    "schedule",
    "set_think_time",
    "should_peng",
    "take_action",
    "tile_score",
]
