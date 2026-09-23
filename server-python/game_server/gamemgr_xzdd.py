"""另一种玩法实现（`conf.type != "xlch"` 时由 `roommgr` 懒加载这一份）。

与姐姐文件 `gamemgr_xlch.py`（血战到底）约 86% 逐行相同，差异集中在番型判定与流程分支
（结算按 `GameSeat.actions` 流水走、只有三家都胡了才结束、胡了的玩家不再被检查碰杠、
换三张的 `huanpaimethod` 会随同步包下发……）。两份必须同步修改（见 server/AGENTS.md §4）。

与 Node 版（`server/game_server/gamemgr_xzdd.ts`）**有意的差异**（只列这三类，其余逐行对应）：

1. 需要 IO 的函数改成 `async def` + `await`（Node 版是同步函数 + 回调 + `setTimeout`）。
   原来的回调风格 `storeSingleHistory` / `storeHistory` / `storeGame` / `doGameOver` 在这里都是
   协程；原来两处 `setTimeout`（`chuPai` 的 500ms、`doGameOver` 的 1500ms）用模块内的
   `_schedule` 起一个延迟协程任务。`checkCanQiangGang` 因为内部要 `await sendOperations`，
   也一并变成协程。
2. 模块级状态用下划线前缀的模块变量（`_games` / `_games_id_base` / `_game_seats_of_users` /
   `_dissolving_list`），不改成类。
3. 少数地方原本会 `throw` 崩进程（例如继续使用取空的房间/座位对象），Python 版照原样写，
   异常会冒泡到调用它的协程，由 socket 处理器记录日志；**不加**防御性的判空返回来"修"它。
   另外，上线载荷（`actions` 的记录、各种 push 的载荷）一律用普通 dict，以便复现
   "值为 undefined 的键被 `JSON.stringify` 丢掉、值为 null 的键保留"这一行为。

本次移植保持：函数名、常量值、判定顺序、推送事件名与载荷字段、日志文案、
`setTimeout` 延时、以及文件末尾"每秒跑一次 `update()`"的位置都与 TS 实现一致。
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from shared.domain import (
    DissolveRequest,
    GameSeat,
    GameState,
    QiangGangContext,
    RoomInfo,
    TingPaiInfo,
)
from utils import crypto, db
from utils.jscompat import (
    js_index_of,
    js_keys,
    js_parse_int,
    js_pop,
    js_random_index,
    js_str,
    now_ms,
    splice,
)
from game_server import mjutils, roommgr, usermgr

# ---- 模块级状态（与 TS 一一对应）----

#: 一局对局：房间号 -> game。对局结束时 delete。
_games: dict[str, GameState] = {}
_games_id_base = 0

ACTION_CHUPAI = 1
ACTION_MOPAI = 2
ACTION_PENG = 3
ACTION_GANG = 4
ACTION_HU = 5
ACTION_ZIMO = 6

#: 玩家 -> 对局座位。开局时写入，结算时 delete。
_game_seats_of_users: dict[int, GameSeat] = {}


def _schedule(delay_ms: int, fn: Any) -> None:
    """对应 JS 的 setTimeout；fn 是无参协程函数。

    原实现只用在两处：`chuPai` 里"没人有操作时"延迟 500ms 摸牌，`doGameOver` 里
    整局结束后延迟 1500ms 写战绩并解散房间。
    """

    async def runner() -> None:
        await asyncio.sleep(delay_ms / 1000)
        await fn()

    asyncio.get_running_loop().create_task(runner())


def get_mj_type(id: int) -> int | None:
    """牌 id 转花色；范围外没有 return（JS 的 undefined，这里是 None）。"""
    if id >= 0 and id < 9:
        # 筒
        return 0
    elif id >= 9 and id < 18:
        # 条
        return 1
    elif id >= 18 and id < 27:
        # 万
        return 2
    return None


def shuffle(game: GameState) -> None:
    mahjongs = game.mahjongs

    # 原文件此处有一段被注释掉的调试洗牌代码（前 12 张分别为 0/1/2/3，其余位置填 4），
    # 只在本地调试时用过，这里保留说明，不参与运行。

    # 筒 (0 ~ 8 表示筒子
    index = 0
    for i in range(9):
        for c in range(4):
            mahjongs[index] = i
            index += 1

    # 条 9 ~ 17表示条子
    for i in range(9, 18):
        for c in range(4):
            mahjongs[index] = i
            index += 1

    # 万
    # 条 18 ~ 26表示万
    for i in range(18, 27):
        for c in range(4):
            mahjongs[index] = i
            index += 1

    for i in range(len(mahjongs)):
        last_index = len(mahjongs) - 1 - i
        index = js_random_index(last_index)
        t = mahjongs[index]
        mahjongs[index] = mahjongs[last_index]
        mahjongs[last_index] = t


def mopai(game: GameState, seat_index: int) -> int:
    if game.currentIndex == len(game.mahjongs):
        return -1
    data = game.gameSeats[seat_index]
    mahjongs = data.holds
    pai = game.mahjongs[game.currentIndex]
    mahjongs.append(pai)

    # 统计牌的数目 ，用于快速判定（空间换时间）
    c = data.countMap.get(pai)
    if c is None:
        c = 0
    data.countMap[pai] = c + 1
    game.currentIndex += 1
    return pai


def deal(game: GameState) -> None:
    # 强制清0
    game.currentIndex = 0

    # 每人13张 一共 13*4 ＝ 52张 庄家多一张 53张
    seat_index = game.button
    for i in range(52):
        mahjongs = game.gameSeats[seat_index].holds
        if mahjongs is None:
            mahjongs = []
            game.gameSeats[seat_index].holds = mahjongs
        mopai(game, seat_index)
        seat_index += 1
        seat_index %= 4

    # 庄家多摸最后一张
    mopai(game, game.button)
    # 当前轮设置为庄家
    game.turn = game.button


# 检查是否可以碰
def check_can_peng(game: GameState, seat_data: GameSeat, target_pai: int) -> None:
    if get_mj_type(target_pai) == seat_data.que:
        return
    count = seat_data.countMap.get(target_pai)
    if count is not None and count >= 2:
        seat_data.canPeng = True


# 检查是否可以点杠
def check_can_dian_gang(game: GameState, seat_data: GameSeat, target_pai: int) -> None:
    # 检查玩家手上的牌
    # 如果没有牌了，则不能再杠
    if len(game.mahjongs) <= game.currentIndex:
        return
    if get_mj_type(target_pai) == seat_data.que:
        return
    count = seat_data.countMap.get(target_pai)
    if count is not None and count >= 3:
        seat_data.canGang = True
        seat_data.gangPai.append(target_pai)
        return


# 检查是否可以暗杠
def check_can_an_gang(game: GameState, seat_data: GameSeat) -> None:
    # 如果没有牌了，则不能再杠
    if len(game.mahjongs) <= game.currentIndex:
        return

    # 原实现的 for...in 键是字符串，这里用 js_keys 保证整数键升序（会决定 gangPai 的顺序）。
    for key in js_keys(seat_data.countMap):
        pai = key
        if get_mj_type(pai) != seat_data.que:
            c = seat_data.countMap[pai]
            if c is not None and c == 4:
                seat_data.canGang = True
                seat_data.gangPai.append(pai)


# 检查是否可以弯杠(自己摸起来的时候)
# 注意：原实现只声明了两个形参，调用点却传了 3 个（第三个被忽略）；这里补一个未使用的形参
# 让签名对得上，运行时行为不变。
def check_can_wan_gang(game: GameState, seat_data: GameSeat, pai: int | None = None) -> None:
    # 如果没有牌了，则不能再杠
    if len(game.mahjongs) <= game.currentIndex:
        return

    # 从碰过的牌中选
    for i in range(len(seat_data.pengs)):
        # 原实现这里的变量也叫 pai（形参），改名只为避免重复声明，语义不变。
        peng_pai = seat_data.pengs[i]
        if seat_data.countMap[peng_pai] == 1:
            seat_data.canGang = True
            seat_data.gangPai.append(peng_pai)


def check_can_hu(game: GameState, seat_data: GameSeat, target_pai: int) -> None:
    game.lastHuPaiSeat = -1
    if get_mj_type(target_pai) == seat_data.que:
        return
    seat_data.canHu = False
    for k in js_keys(seat_data.tingMap):
        # 原实现的 for...in 键是字符串，直接与数字 targetPai 比较（`==` 会隐式转换）；
        # js_keys 给出的是升序整数键，比较语义不变。
        if target_pai == k:
            seat_data.canHu = True


def clear_all_options(game: GameState, seat_data: GameSeat | None = None) -> None:
    def fn_clear(sd: GameSeat) -> None:
        sd.canPeng = False
        sd.canGang = False
        sd.gangPai = []
        sd.canHu = False
        sd.lastFangGangSeat = -1

    # 原实现写的是 `if(seatData)`；座位对象恒为真，等价于"传了座位就只清这个座位"。
    if seat_data is not None:
        fn_clear(seat_data)
    else:
        game.qiangGangContext = None
        for i in range(len(game.gameSeats)):
            fn_clear(game.gameSeats[i])


# 检查听牌
def check_can_ting_pai(game: GameState, seat_data: GameSeat) -> None:
    seat_data.tingMap = {}

    # 检查手上的牌是不是已打缺，如果未打缺，则不进行判定
    for i in range(len(seat_data.holds)):
        pai = seat_data.holds[i]
        if get_mj_type(pai) == seat_data.que:
            return

    # 检查是否是七对 前提是没有碰，也没有杠 ，即手上拥有13张牌
    if len(seat_data.holds) == 13:
        # 有5对牌
        hu = False
        dan_pai = -1
        pair_count = 0
        # 原实现的 for...in 键是字符串，既拿它当 countMap 的下标、又直接赋给 danPai；
        # 这里用 js_keys 拿升序整数键，语义不变（顺序会影响 danPai 取到哪张单牌）。
        for k in js_keys(seat_data.countMap):
            c = seat_data.countMap[k]
            if c == 2 or c == 3:
                pair_count += 1
            elif c == 4:
                pair_count += 2

            if c == 1 or c == 3:
                # 如果已经有单牌了，表示不止一张单牌，并没有下叫。直接闪
                if dan_pai >= 0:
                    break
                dan_pai = k

        # 检查是否有6对 并且单牌是不是目标牌
        if pair_count == 6:
            # 七对只能和一张，就是手上那张单牌
            # 七对的番数＝ 2番+N个4个牌（即龙七对）
            seat_data.tingMap[dan_pai] = TingPaiInfo(fan=2, pattern="7pairs")
            # 如果是，则直接返回咯

    # 检查是否是对对胡  由于四川麻将没有吃，所以只需要检查手上的牌
    # 对对胡叫牌有两种情况
    # 1、N坎 + 1张单牌
    # 2、N-1坎 + 两对牌
    single_count = 0
    col_count = 0
    pair_count = 0
    arr: list[int] = []
    for k in js_keys(seat_data.countMap):
        # 同上：原实现把 for...in 的字符串键 push 进 arr 再当牌 id 用，这里直接用整数键。
        c = seat_data.countMap[k]
        if c == 1:
            single_count += 1
            arr.append(k)
        elif c == 2:
            pair_count += 1
            arr.append(k)
        elif c == 3:
            col_count += 1
        elif c == 4:
            # 手上有4个一样的牌，在四川麻将中是和不了对对胡的 随便加点东西
            single_count += 1
            pair_count += 2

    if (pair_count == 2 and single_count == 0) or (pair_count == 0 and single_count == 1):
        for i in range(len(arr)):
            # 对对胡1番
            p = arr[i]
            if seat_data.tingMap.get(p) is None:
                seat_data.tingMap[p] = TingPaiInfo(pattern="duidui", fan=1)

    # 原实现在这里有三行被注释掉的调试输出（手牌 / countMap / 单张·坎·对子的计数）。
    # 检查是不是平胡
    if seat_data.que != 0:
        mjutils.check_ting_pai(seat_data, 0, 9)

    if seat_data.que != 1:
        mjutils.check_ting_pai(seat_data, 9, 18)

    if seat_data.que != 2:
        mjutils.check_ting_pai(seat_data, 18, 27)


def get_seat_index(user_id: int) -> int | None:
    seat_index = roommgr.get_user_seat(user_id)
    if seat_index is None:
        return None
    return seat_index


def get_game_by_user_id(user_id: int) -> GameState | None:
    room_id = roommgr.get_user_room(user_id)
    if room_id is None:
        return None
    game = _games.get(room_id)
    return game


def has_operations(seat_data: GameSeat) -> bool:
    if seat_data.canGang or seat_data.canPeng or seat_data.canHu:
        return True
    return False


async def send_operations(game: GameState, seat_data: GameSeat, pai: int) -> None:
    if has_operations(seat_data):
        if pai == -1:
            pai = seat_data.holds[len(seat_data.holds) - 1]

        # 原实现在对象字面量之后才补 data.si，所以这里照原样在后面补。
        data: dict[str, Any] = {
            "pai": pai,
            "hu": seat_data.canHu,
            "peng": seat_data.canPeng,
            "gang": seat_data.canGang,
            "gangpai": seat_data.gangPai,
        }

        # 如果可以有操作，则进行操作
        await usermgr.send_msg(seat_data.userId, "game_action_push", data)

        # 注意：`si` 写在 sendMsg **之后**，所以它从来没被发出去——原实现的历史行为，保留这个死赋值。
        data["si"] = seat_data.seatIndex
    else:
        # 原实现只传两个实参；这里补 None 后函数体内拿到的仍是 undefined，
        # socket.emit(event,undefined) 的行为完全一致。
        await usermgr.send_msg(seat_data.userId, "game_action_push", None)


def move_to_next_user(game: GameState, next_seat: int | None = None) -> None:
    game.fangpaoshumu = 0
    # 找到下一个没有和牌的玩家
    if next_seat is None:
        while True:
            game.turn += 1
            game.turn %= 4
            turn_seat = game.gameSeats[game.turn]
            if turn_seat.hued == False:
                return
    else:
        game.turn = next_seat


async def do_user_mo_pai(game: GameState) -> None:
    game.chuPai = -1
    turn_seat = game.gameSeats[game.turn]
    turn_seat.lastFangGangSeat = -1
    turn_seat.guoHuFan = -1
    pai = mopai(game, game.turn)
    # 牌摸完了，结束
    if pai == -1:
        await do_game_over(game, turn_seat.userId)
        return
    else:
        num_of_mj = len(game.mahjongs) - game.currentIndex
        await usermgr.broacast_in_room("mj_count_push", num_of_mj, turn_seat.userId, True)

    record_game_action(game, game.turn, ACTION_MOPAI, pai)

    # 通知前端新摸的牌
    await usermgr.send_msg(turn_seat.userId, "game_mopai_push", pai)
    # 检查是否可以暗杠或者胡
    # 检查胡，直杠，弯杠
    check_can_an_gang(game, turn_seat)
    check_can_wan_gang(game, turn_seat, pai)

    # 检查看是否可以和
    check_can_hu(game, turn_seat, pai)

    # 广播通知玩家出牌方
    turn_seat.canChuPai = True
    await usermgr.broacast_in_room("game_chupai_push", turn_seat.userId, turn_seat.userId, True)

    # 通知玩家做对应操作
    await send_operations(game, turn_seat, game.chuPai)


def is_same_type(type: int | None, arr: list[int]) -> bool:
    for i in range(len(arr)):
        t = get_mj_type(arr[i])
        if type != -1 and type != t:
            return False
        type = t
    return True


def is_qing_yi_se(game_seat_data: GameSeat) -> bool:
    type = get_mj_type(game_seat_data.holds[0])

    # 检查手上的牌
    if is_same_type(type, game_seat_data.holds) == False:
        return False

    # 检查杠下的牌
    if is_same_type(type, game_seat_data.angangs) == False:
        return False
    if is_same_type(type, game_seat_data.wangangs) == False:
        return False
    if is_same_type(type, game_seat_data.diangangs) == False:
        return False

    # 检查碰牌
    if is_same_type(type, game_seat_data.pengs) == False:
        return False
    return True


def is_men_qing(game_seat_data: GameSeat) -> bool:
    return (
        len(game_seat_data.pengs)
        + len(game_seat_data.wangangs)
        + len(game_seat_data.diangangs)
    ) == 0


def is_zhong_zhang(game_seat_data: GameSeat) -> bool:
    def fn(arr: list[int]) -> bool:
        for i in range(len(arr)):
            pai = arr[i]
            if pai == 0 or pai == 8 or pai == 9 or pai == 17 or pai == 18 or pai == 26:
                return False
        return True

    if fn(game_seat_data.pengs) == False:
        return False
    if fn(game_seat_data.angangs) == False:
        return False
    if fn(game_seat_data.diangangs) == False:
        return False
    if fn(game_seat_data.wangangs) == False:
        return False
    if fn(game_seat_data.holds) == False:
        return False
    return True


def is_jiang_dui(game_seat_data: GameSeat) -> bool:
    def fn(arr: list[int]) -> bool:
        for i in range(len(arr)):
            pai = arr[i]
            if (
                pai != 1
                and pai != 4
                and pai != 7
                and pai != 9
                and pai != 13
                and pai != 16
                and pai != 18
                and pai != 21
                and pai != 25
            ):
                return False
        return True

    if fn(game_seat_data.pengs) == False:
        return False
    if fn(game_seat_data.angangs) == False:
        return False
    if fn(game_seat_data.diangangs) == False:
        return False
    if fn(game_seat_data.wangangs) == False:
        return False
    if fn(game_seat_data.holds) == False:
        return False
    return True


def is_tinged(seat_data: GameSeat) -> bool:
    for _k in js_keys(seat_data.tingMap):
        return True
    return False


def compute_fan_score(game: GameState, fan: int) -> int:
    if fan > game.conf.maxFan:
        fan = game.conf.maxFan
    return (1 << fan) * game.conf.baseScore


# 是否需要查大叫(有两家以上未胡，且有人没有下叫)
def need_cha_da_jiao(game: GameState) -> bool:
    # 查叫
    num_of_hued = 0
    num_of_tinged = 0
    num_of_untinged = 0
    for i in range(len(game.gameSeats)):
        ts = game.gameSeats[i]
        if ts.hued:
            num_of_hued += 1
            num_of_tinged += 1
        elif is_tinged(ts):
            num_of_tinged += 1
        else:
            num_of_untinged += 1

    # 如果三家都胡牌了，不需要查叫
    if num_of_hued == 3:
        return False

    # 如果没有任何一个人叫牌，也没有任何一个胡牌，则不需要查叫
    if num_of_tinged == 0:
        return False

    # 如果都听牌了，也不需要查叫
    if num_of_untinged == 0:
        return False
    return True


def find_max_fan_ting_pai(ts: GameSeat) -> TingPaiInfo | None:
    # 找出最大番
    cur: TingPaiInfo | None = None
    # 原实现用 for...in 遍历 tingMap（整数键升序），并列最大番时取先遇到的那条，
    # 所以这里必须用 js_keys 保持同样的顺序。
    for k in js_keys(ts.tingMap):
        # 原实现直接解引用 tingMap 的值（并断言成带 pai 的类型）；这里取出来比较，运行时对象不变。
        tpai = ts.tingMap[k]
        if cur is None or tpai.fan > cur.fan:
            cur = tpai
    return cur


def find_un_tinged_players(game: GameState) -> list[int]:
    arr: list[int] = []
    for i in range(len(game.gameSeats)):
        ts = game.gameSeats[i]
        # 如果没有胡，且没有听牌
        if not ts.hued and not is_tinged(ts):
            arr.append(i)
            record_user_action(game, ts, "beichadajiao", -1)
    return arr


def cha_jiao(game: GameState) -> None:
    arr = find_un_tinged_players(game)
    for i in range(len(game.gameSeats)):
        ts = game.gameSeats[i]
        # 如果没有胡，但是听牌了，则未叫牌的人要给钱
        if not ts.hued and is_tinged(ts):
            # 已听牌时 find_max_fan_ting_pai 一定返回非 None；这里照原样直接解引用。
            cur = find_max_fan_ting_pai(ts)
            ts.fan = cur.fan
            ts.pattern = cur.pattern
            record_user_action(game, ts, "chadajiao", arr)


def calculate_result(game: GameState, room_info: RoomInfo) -> None:
    is_need_cha_da_jia = need_cha_da_jiao(game)
    if is_need_cha_da_jia:
        cha_jiao(game)

    base_score = game.conf.baseScore
    num_of_hued = 0
    for i in range(len(game.gameSeats)):
        if game.gameSeats[i].hued == True:
            num_of_hued += 1

    for i in range(len(game.gameSeats)):
        sd = game.gameSeats[i]

        # 统计杠的数目
        sd.numAnGang = len(sd.angangs)
        sd.numMingGang = len(sd.wangangs) + len(sd.diangangs)

        # 对所有胡牌的玩家进行统计
        if is_tinged(sd):
            # 统计自己的番子和分数
            # 基础番(平胡0番，对对胡1番、七对2番) + 清一色2番 + 杠+1番
            # 杠上花+1番，杠上炮+1番 抢杠胡+1番，金钩胡+1番，海底胡+1番
            fan = sd.fan
            if is_qing_yi_se(sd):
                sd.qingyise = True
                fan += 2

            num_of_gangs = len(sd.diangangs) + len(sd.wangangs) + len(sd.angangs)
            for j in range(len(sd.pengs)):
                pai = sd.pengs[j]
                if sd.countMap[pai] == 1:
                    num_of_gangs += 1
            for k in js_keys(sd.countMap):
                if sd.countMap[k] == 4:
                    num_of_gangs += 1
            sd.numofgen = num_of_gangs

            # 金钩胡
            if len(sd.holds) == 1 or len(sd.holds) == 2:
                fan += 1
                sd.isJinGouHu = True

            if sd.isHaiDiHu:
                fan += 1

            if game.conf.tiandihu:
                if sd.isTianHu:
                    fan += 3
                elif sd.isDiHu:
                    fan += 2

            isjiangdui = False
            if game.conf.jiangdui:
                if sd.pattern == "7pairs":
                    if sd.numofgen > 0:
                        sd.numofgen -= 1
                        # 原实现这两行写的是 `==`（比较，不是赋值），等于什么都没做；照原样保留。
                        sd.pattern == "l7pairs"
                        isjiangdui = is_jiang_dui(sd)
                        if isjiangdui:
                            sd.pattern == "j7paris"
                            fan += 2
                        else:
                            fan += 1
                elif sd.pattern == "duidui":
                    isjiangdui = is_jiang_dui(sd)
                    if isjiangdui:
                        sd.pattern = "jiangdui"
                        fan += 2

            if game.conf.menqing:
                # 不是将对，才检查中张
                if not isjiangdui:
                    sd.isZhongZhang = is_zhong_zhang(sd)
                    if sd.isZhongZhang:
                        fan += 1

                sd.isMenQing = is_men_qing(sd)
                if sd.isMenQing:
                    fan += 1

            fan += sd.numofgen
            if sd.isGangHu:
                fan += 1
            if sd.isQiangGangHu:
                fan += 1

            # 收杠钱
            additonalscore = 0
            for a in range(len(sd.actions)):
                ac = sd.actions[a]
                if ac["type"] == "fanggang":
                    ts = game.gameSeats[ac["targets"][0]]
                    # 检查放杠的情况，如果目标没有和牌，且没有叫牌，则不算 用于优化前端显示
                    if is_need_cha_da_jia and (ts.hued) == False and (is_tinged(ts) == False):
                        ac["state"] = "nop"
                elif ac["type"] == "angang" or ac["type"] == "wangang" or ac["type"] == "diangang":
                    if ac.get("state") != "nop":
                        acscore = ac["score"]
                        additonalscore += len(ac["targets"]) * acscore * base_score
                        # 扣掉目标方的分
                        for t in range(len(ac["targets"])):
                            six = ac["targets"][t]
                            game.gameSeats[six].score -= acscore * base_score
                elif ac["type"] == "maozhuanyu":
                    # 对于呼叫转移，如果对方没有叫牌，表示不得行
                    # 原实现直接传 ac.owner（没有判空）：owner 为 null 时 is_tinged 会因读
                    # seatData.tingMap 抛异常。这里照原样传入、不做防御性判空——maozhuanyu 记录
                    # 创建时 owner 一定有值，null 只在本分支末尾写入。
                    mao_owner = ac["owner"]
                    if is_tinged(mao_owner):
                        # 如果
                        ref = ac["ref"]
                        acscore = ref["score"]
                        total = len(ref["targets"]) * acscore * base_score
                        additonalscore += total
                        # 扣掉目标方的分
                        if ref.get("payTimes") == 0:
                            for t in range(len(ref["targets"])):
                                six = ref["targets"][t]
                                game.gameSeats[six].score -= acscore * base_score
                        else:
                            # 如果已经被扣过一次了，则由杠牌这家赔
                            mao_owner.score -= total
                        ref["payTimes"] += 1
                        ac["owner"] = None
                        ac["ref"] = None
                elif (
                    ac["type"] == "zimo"
                    or ac["type"] == "hu"
                    or ac["type"] == "ganghua"
                    or ac["type"] == "dianganghua"
                    or ac["type"] == "gangpaohu"
                    or ac["type"] == "qiangganghu"
                    or ac["type"] == "chadajiao"
                ):
                    extra_score = 0
                    if ac.get("iszimo"):
                        if game.conf.zimo == 0:
                            # 自摸加底
                            extra_score = base_score
                        if game.conf.zimo == 1:
                            fan += 1
                        else:
                            # 什么都不做（原实现这里写的就是 "nothing."）
                            pass
                        sd.numZiMo += 1
                    else:
                        if ac["type"] != "chadajiao":
                            sd.numJiePao += 1

                    score = compute_fan_score(game, fan) + extra_score
                    sd.score += score * len(ac["targets"])

                    for t in range(len(ac["targets"])):
                        six = ac["targets"][t]
                        td = game.gameSeats[six]
                        td.score -= score
                        if td != sd:
                            if ac["type"] == "chadajiao":
                                td.numChaJiao += 1
                            elif not ac.get("iszimo"):
                                td.numDianPao += 1

            if fan > game.conf.maxFan:
                fan = game.conf.maxFan
            # 一定要用 += 。 因为此时的sd.score可能是负的
            sd.score += additonalscore
            if sd.pattern is not None:
                sd.fan = fan
        else:
            for a in range(len(sd.actions) - 1, -1, -1):
                ac = sd.actions[a]
                if ac["type"] == "angang" or ac["type"] == "wangang" or ac["type"] == "diangang":
                    # 如果3家都胡牌，则需要结算。否则认为是查叫
                    if num_of_hued < 3:
                        splice(sd.actions, a, 1)
                    else:
                        if ac.get("state") != "nop":
                            acscore = ac["score"]
                            sd.score += len(ac["targets"]) * acscore * base_score
                            # 扣掉目标方的分
                            for t in range(len(ac["targets"])):
                                six = ac["targets"][t]
                                game.gameSeats[six].score -= acscore * base_score


# `game_over_push` 里一局的结算项（`results` 的元素）字段：
# userId / actions / pengs / wangangs / diangangs / angangs / numofgen / holds / fan / score /
# totalscore / qingyise / pattern / isganghu / menqing / zhongzhang / jingouhu / haidihu /
# tianhu / dihu / huorder。xzdd 的结算项**不带** huinfo（xlch 才带），所以这里不写这个键。
#
# `game_over_push` 的 `endinfo` 元素（四家的累计统计）字段：
# numzimo / numjiepao / numdianpao / numangang / numminggang / numchadajiao。


async def do_game_over(game: GameState | None, user_id: int, force_end: bool = False) -> None:
    # 原实现这里的两个 `!` 只是为了让下面闭包里的引用不必重复断言；运行时的判空与 return 与原来完全一致。
    room_id = roommgr.get_user_room(user_id)
    if room_id is None:
        return
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return

    results: list[dict[str, Any]] = []
    dbresult = [0, 0, 0, 0]

    async def fn_notice_result(is_end: bool) -> None:
        endinfo: list[dict[str, Any]] | None = None
        if is_end:
            endinfo = []
            for i in range(len(room_info.seats)):
                rs = room_info.seats[i]
                endinfo.append({
                    "numzimo": rs.numZiMo,
                    "numjiepao": rs.numJiePao,
                    "numdianpao": rs.numDianPao,
                    "numangang": rs.numAnGang,
                    "numminggang": rs.numMingGang,
                    "numchadajiao": rs.numChaJiao,
                })
        await usermgr.broacast_in_room(
            "game_over_push", {"results": results, "endinfo": endinfo}, user_id, True
        )
        # 如果局数已够，则进行整体结算，并关闭房间
        if is_end:

            async def on_later() -> None:
                if room_info.numOfGames > 1:
                    await store_history(room_info)

                await usermgr.kick_all_in_room(room_id)
                await roommgr.destroy(room_id)
                await db.archive_games(room_info.uuid)

            _schedule(1500, on_later)

    if game is not None:
        if not force_end:
            calculate_result(game, room_info)

        for i in range(len(room_info.seats)):
            rs = room_info.seats[i]
            sd = game.gameSeats[i]

            rs.ready = False
            rs.score += sd.score
            rs.numZiMo += sd.numZiMo
            rs.numJiePao += sd.numJiePao
            rs.numDianPao += sd.numDianPao
            rs.numAnGang += sd.numAnGang
            rs.numMingGang += sd.numMingGang
            rs.numChaJiao += sd.numChaJiao

            # 原实现的对象字面量里，只有 `pattern` / `isganghu` / `fan`（begin 里初始化过）
            # 与 `huorder` 是稳定存在的；其余"未赋值"的字段在 Node 里是 undefined，
            # `JSON.stringify` 会把整个键丢掉。所以这里按"原实现是否会写入"来决定加不加键，
            # 与 `gamemgr_xlch.py` 的处理保持一致（两份必须同步修改）。
            user_rt: dict[str, Any] = {
                "userId": sd.userId,
                "pengs": sd.pengs,
                "actions": [],
                "wangangs": sd.wangangs,
                "diangangs": sd.diangangs,
                "angangs": sd.angangs,
                "holds": sd.holds,
                "fan": sd.fan,
                "score": sd.score,
                "totalscore": rs.score,
                "pattern": sd.pattern,
                "isganghu": sd.isGangHu,
                "huorder": js_index_of(game.hupaiList, i),
            }
            # numofgen 只在"已听牌"的那个分支里被赋值。
            if is_tinged(sd):
                user_rt["numofgen"] = sd.numofgen
            if sd.qingyise:
                user_rt["qingyise"] = True
            if game.conf.menqing:
                # isMenQing / isZhongZhang 只在 conf.menqing 为真时才被赋值，值可能是 False。
                user_rt["menqing"] = sd.isMenQing
                # 说明：原实现在"不是将对"时才写 isZhongZhang，本函数里已经拿不到那个局部量，
                # 这里用真值判断近似——值为 False 时键会消失。客户端对这两个字段都只做真值判断，
                # 因此不产生可观察差异（见 server-python/AGENTS.md §4）。
                if sd.isZhongZhang:
                    user_rt["zhongzhang"] = True
            if sd.isJinGouHu:
                user_rt["jingouhu"] = True
            # haidihu 只在 hu() 里被赋值，也就是只有胡过的座位才有这个键。
            if sd.hued:
                user_rt["haidihu"] = sd.isHaiDiHu
            if sd.isTianHu:
                user_rt["tianhu"] = True
            if sd.isDiHu:
                user_rt["dihu"] = True

            # 原实现用 for...in 遍历数组（下标按升序枚举），这里用 range 保持同样的顺序，
            # actions 也是按下标 0..n-1 依次写入的，所以顺序追加即可。
            for action_index in range(len(sd.actions)):
                user_rt["actions"].append({"type": sd.actions[action_index]["type"]})
            results.append(user_rt)

            dbresult[i] = sd.score
            # 对应 delete gameSeatsOfUsers[sd.userId]（键不存在时是空操作）。
            _game_seats_of_users.pop(sd.userId, None)

        # 对应 delete games[roomId]（键不存在时是空操作）。
        _games.pop(room_id, None)

        old = room_info.nextButton
        if game.yipaoduoxiang >= 0:
            room_info.nextButton = game.yipaoduoxiang
        elif game.firstHupai >= 0:
            room_info.nextButton = game.firstHupai
        else:
            room_info.nextButton = (game.turn + 1) % 4

        if old != room_info.nextButton:
            await db.update_next_button(room_id, room_info.nextButton)

    if force_end or game is None:
        await fn_notice_result(True)
    else:
        # 保存游戏
        await store_game(game)

        await db.update_game_result(room_info.uuid, game.gameIndex, dbresult)

        # 记录打牌信息
        action_str = json.dumps(game.actionList, separators=(",", ":"))
        await db.update_game_action_records(room_info.uuid, game.gameIndex, action_str)

        # 保存游戏局数
        await db.update_num_of_turns(room_id, room_info.numOfGames)

        # 如果是第一次，并且不是强制解散 则扣除房卡
        if room_info.numOfGames == 1:
            cost = 2
            if room_info.conf.maxGames == 8:
                cost = 3
            await db.cost_gems(game.gameSeats[0].userId, cost)

        is_end = room_info.numOfGames >= room_info.conf.maxGames
        await fn_notice_result(is_end)


def record_user_action(
    game: GameState,
    seat_data: GameSeat,
    type: str,
    target: int | list[int] | None = None,
) -> dict[str, Any]:
    """`record_user_action` 新建的记录：一定有 `type` 与 `targets`。"""
    d: dict[str, Any] = {"type": type, "targets": []}
    if target is not None:
        # 对应 JS 的 `typeof(target) == 'number'`。
        if isinstance(target, (int, float)):
            d["targets"].append(target)
        else:
            d["targets"] = target
    else:
        for i in range(len(game.gameSeats)):
            s = game.gameSeats[i]
            if i != seat_data.seatIndex and s.hued == False:
                d["targets"].append(i)

    seat_data.actions.append(d)
    return d


def record_game_action(game: GameState, si: int, action: int, pai: int | None = None) -> None:
    game.actionList.append(si)
    game.actionList.append(action)
    if pai is not None:
        game.actionList.append(pai)


# `game_sync_push` 里一个座位的同步数据字段：
# userid / folds / angangs / diangangs / wangangs / pengs / que / hued / iszimo，
# 自己的座位再带 holds 与 huanpais，别人只带 huanpais（有换牌记录时是 []，否则 null）。
# xzdd 的同步座位**不带** huinfo（xlch 才带），所以这里不写这个键。
#
# `game_sync_push` 的载荷字段：state / numofmj / button / turn / chuPai /
# huanpaimethod（xzdd 独有：本局换三张的换牌方式，0 对家 / 1 下家 / 2 上家）/ seats。


async def set_ready(user_id: int, callback: Any = None) -> None:
    room_id = roommgr.get_user_room(user_id)
    if room_id is None:
        return
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return

    roommgr.set_ready(user_id, True)

    game = _games.get(room_id)
    if game is None:
        if len(room_info.seats) == 4:
            for i in range(len(room_info.seats)):
                # 原实现这里的变量也叫 s（与下面同步载荷的对象重名），改成 rs 只是为了过 TS 的
                # 重复声明检查，语义不变。
                rs = room_info.seats[i]
                if rs.ready == False or usermgr.is_online(rs.userId) == False:
                    return
            # 4个人到齐了，并且都准备好了，则开始新的一局
            await begin(room_id)
    else:
        num_of_mj = len(game.mahjongs) - game.currentIndex
        # 原实现算出了剩余局数却从未使用；保留这一行以对应原文。
        remaining_games = room_info.conf.maxGames - room_info.numOfGames

        # 原实现在对象字面量之后才补 data.seats，所以这里照原样在后面补。
        data: dict[str, Any] = {
            "state": game.state,
            "numofmj": num_of_mj,
            "button": game.button,
            "turn": game.turn,
            "chuPai": game.chuPai,
            "huanpaimethod": game.huanpaiMethod,
        }

        data["seats"] = []
        seat_data: GameSeat | None = None
        for i in range(4):
            sd = game.gameSeats[i]

            s: dict[str, Any] = {
                "userid": sd.userId,
                "folds": sd.folds,
                "angangs": sd.angangs,
                "diangangs": sd.diangangs,
                "wangangs": sd.wangangs,
                "pengs": sd.pengs,
                "que": sd.que,
                "hued": sd.hued,
                "iszimo": sd.iszimo,
            }
            if sd.userId == user_id:
                s["holds"] = sd.holds
                s["huanpais"] = sd.huanpais
                seat_data = sd
            else:
                # 原实现是 `sd.huanpais? []:null`；JS 里数组（包括空数组）恒为真，
                # 所以这里判空必须用 is not None，而不是 Python 的真值判断。
                s["huanpais"] = [] if sd.huanpais is not None else None
            data["seats"].append(s)

        # 同步整个信息给客户端
        await usermgr.send_msg(user_id, "game_sync_push", data)
        # 循环里必然有一次命中自己的座位；这里照原样直接传。
        await send_operations(game, seat_data, game.chuPai)


# 战绩里一个座位的记录字段：userid / name / score。
# 一局房间的最终战绩（`store_history` 写入 `t_users.history`）字段：uuid / id / time / seats。


async def store_single_history(user_id: int, history: dict[str, Any]) -> None:
    data = await db.get_user_history(user_id)
    if data is None:
        data = []
    while len(data) >= 10:
        # 对应 Array.prototype.shift()
        data.pop(0)
    data.append(history)
    await db.update_user_history(user_id, data)


async def store_history(room_info: RoomInfo) -> None:
    seats = room_info.seats
    history: dict[str, Any] = {
        "uuid": room_info.uuid,
        "id": room_info.id,
        "time": room_info.createTime,
        "seats": [None] * 4,
    }

    for i in range(len(seats)):
        rs = seats[i]
        # 原实现从空对象开始逐个字段赋值；这里新建一个 dict 再逐个字段写。
        hs: dict[str, Any] = {}
        history["seats"][i] = hs
        hs["userid"] = rs.userId
        hs["name"] = crypto.to_base64(rs.name)
        hs["score"] = rs.score

    for i in range(len(seats)):
        s = seats[i]
        await store_single_history(s.userId, history)


def construct_game_base_info(game: GameState) -> None:
    base_info: dict[str, Any] = {
        "type": game.conf.type,
        "button": game.button,
        "index": game.gameIndex,
        "mahjongs": game.mahjongs,
        "game_seats": [None] * 4,
    }

    for i in range(4):
        base_info["game_seats"][i] = game.gameSeats[i].holds
    # 与 `JSON.stringify` 一致：紧凑分隔符、不转义非 ASCII。
    game.baseInfoJson = json.dumps(base_info, separators=(",", ":"), ensure_ascii=False)


async def store_game(game: GameState) -> int | None:
    return await db.create_game(game.roomInfo.uuid, game.gameIndex, game.baseInfoJson)


# 开始新的一局
async def begin(room_id: str) -> None:
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return
    seats = room_info.seats

    # 原实现的对象里没有 lastHuPaiSeat / qiangGangContext / huanpaiMethod / baseInfoJson 这几个
    # 字段（它们由后续流程补上），所以这里列出原对象真正写入的那些字段，其余交给 GameState 的默认值。
    game = GameState(
        conf=room_info.conf,
        roomInfo=room_info,
        gameIndex=room_info.numOfGames,

        button=room_info.nextButton,
        # 对应 new Array<number>(108)：先开一个 108 长的数组，随后由 shuffle 填满。
        mahjongs=[0] * 108,
        currentIndex=0,
        # 对应 new Array<GameSeat>(4)：下面循环 append 四次，长度同样是 4。
        gameSeats=[],

        numOfQue=0,
        turn=0,
        chuPai=-1,
        state="idle",
        firstHupai=-1,
        yipaoduoxiang=-1,
        fangpaoshumu=-1,
        actionList=[],
        hupaiList=[],
        chupaiCnt=0,
    )

    room_info.numOfGames += 1

    for i in range(4):
        # 原实现从空对象开始逐个字段赋值；这里用 GameSeat 的默认值起步，再逐个字段赋值。
        data = GameSeat()
        game.gameSeats.append(data)

        data.game = game

        data.seatIndex = i

        data.userId = seats[i].userId
        # 持有的牌
        data.holds = []
        # 打出的牌
        data.folds = []
        # 暗杠的牌
        data.angangs = []
        # 点杠的牌
        data.diangangs = []
        # 弯杠的牌
        data.wangangs = []
        # 碰了的牌
        data.pengs = []
        # 缺一门
        data.que = -1

        # 换三张的牌
        data.huanpais = None

        # 玩家手上的牌的数目，用于快速判定碰杠
        data.countMap = {}
        # 玩家听牌，用于快速判定胡了的番数
        data.tingMap = {}
        data.pattern = ""

        # 是否可以杠
        data.canGang = False
        # 用于记录玩家可以杠的牌
        data.gangPai = []

        # 是否可以碰
        data.canPeng = False
        # 是否可以胡
        data.canHu = False
        # 是否可以出牌
        data.canChuPai = False

        # 如果guoHuFan >=0 表示处于过胡状态，
        # 如果过胡状态，那么只能胡大于过胡番数的牌
        data.guoHuFan = -1

        # 是否胡了
        data.hued = False
        # 是否是自摸
        data.iszimo = False

        data.isGangHu = False

        #
        data.actions = []

        data.fan = 0
        data.score = 0
        data.lastFangGangSeat = -1

        # 统计信息
        data.numZiMo = 0
        data.numJiePao = 0
        data.numDianPao = 0
        data.numAnGang = 0
        data.numMingGang = 0
        data.numChaJiao = 0

        _game_seats_of_users[data.userId] = data
    _games[room_id] = game
    # 洗牌
    shuffle(game)
    # 发牌
    deal(game)

    num_of_mj = len(game.mahjongs) - game.currentIndex
    huansanzhang = room_info.conf.hsz

    for i in range(len(seats)):
        # 开局时，通知前端必要的数据
        s = seats[i]
        # 通知玩家手牌
        await usermgr.send_msg(s.userId, "game_holds_push", game.gameSeats[i].holds)
        # 通知还剩多少张牌
        await usermgr.send_msg(s.userId, "mj_count_push", num_of_mj)
        # 通知还剩多少局
        await usermgr.send_msg(s.userId, "game_num_push", room_info.numOfGames)
        # 通知游戏开始
        await usermgr.send_msg(s.userId, "game_begin_push", game.button)

        # 原实现写的是 `huansanzhang == true`（hsz 是数字）；这里 `== 1` 与之等价
        # （true 转成 1），语义不变。
        if huansanzhang == 1:
            game.state = "huanpai"
            # 通知准备换牌
            await usermgr.send_msg(s.userId, "game_huanpai_push", None)
        else:
            game.state = "dingque"
            # 通知准备定缺
            await usermgr.send_msg(s.userId, "game_dingque_push", None)


# `huanpai_notify` 与 `game_huanpai_over_push` 的载荷字段：
# si / huanpais / method（原实现在这几处复用了同一个变量名 rd，这里也沿用同一个 dict 名）。


async def huan_san_zhang(user_id: int, p1: int, p2: int, p3: int) -> None:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    game = seat_data.game
    if game.state != "huanpai":
        print("can't recv huansanzhang when game.state == " + game.state)
        return

    if seat_data.huanpais is not None:
        print("player has done this action.")
        return

    if seat_data.countMap.get(p1) is None or seat_data.countMap.get(p1) == 0:
        return
    seat_data.countMap[p1] -= 1

    if seat_data.countMap.get(p2) is None or seat_data.countMap.get(p2) == 0:
        seat_data.countMap[p1] += 1
        return
    seat_data.countMap[p2] -= 1

    if seat_data.countMap.get(p3) is None or seat_data.countMap.get(p3) == 0:
        seat_data.countMap[p1] += 1
        seat_data.countMap[p2] += 1
        return

    seat_data.countMap[p1] += 1
    seat_data.countMap[p2] += 1

    seat_data.huanpais = [p1, p2, p3]

    for i in range(len(seat_data.huanpais)):
        p = seat_data.huanpais[i]
        idx = js_index_of(seat_data.holds, p)
        splice(seat_data.holds, idx, 1)
        seat_data.countMap[p] -= 1
    await usermgr.send_msg(seat_data.userId, "game_holds_push", seat_data.holds)

    for i in range(len(game.gameSeats)):
        sd = game.gameSeats[i]
        if sd == seat_data:
            rd: dict[str, Any] = {
                "si": seat_data.userId,
                "huanpais": seat_data.huanpais,
            }
            await usermgr.send_msg(sd.userId, "huanpai_notify", rd)
        else:
            rd = {
                "si": seat_data.userId,
                "huanpais": [],
            }
            await usermgr.send_msg(sd.userId, "huanpai_notify", rd)

    # 如果还有未换牌的玩家，则继承等待
    for i in range(len(game.gameSeats)):
        if game.gameSeats[i].huanpais is None:
            return

    # 换牌函数
    def fn(s1: GameSeat, huanjin: list[int]) -> None:
        for i in range(len(huanjin)):
            p = huanjin[i]
            s1.holds.append(p)
            if s1.countMap.get(p) is None:
                s1.countMap[p] = 0
            s1.countMap[p] += 1

    # 开始换牌
    f = random.random()
    s = game.gameSeats
    huanpai_method = 0
    # 对家换牌
    # 上面已经确认过四家的 huanpais 都非空；这里照原样直接解引用。
    if f < 0.33:
        fn(s[0], s[2].huanpais)
        fn(s[1], s[3].huanpais)
        fn(s[2], s[0].huanpais)
        fn(s[3], s[1].huanpais)
        huanpai_method = 0
    # 换下家的牌
    elif f < 0.66:
        fn(s[0], s[1].huanpais)
        fn(s[1], s[2].huanpais)
        fn(s[2], s[3].huanpais)
        fn(s[3], s[0].huanpais)
        huanpai_method = 1
    # 换上家的牌
    else:
        fn(s[0], s[3].huanpais)
        fn(s[1], s[0].huanpais)
        fn(s[2], s[1].huanpais)
        fn(s[3], s[2].huanpais)
        huanpai_method = 2

    rd = {
        "method": huanpai_method,
    }
    game.huanpaiMethod = huanpai_method

    game.state = "dingque"
    for i in range(len(s)):
        user_id = s[i].userId
        await usermgr.send_msg(user_id, "game_huanpai_over_push", rd)

        await usermgr.send_msg(user_id, "game_holds_push", s[i].holds)
        # 通知准备定缺
        await usermgr.send_msg(user_id, "game_dingque_push", None)


async def ding_que(user_id: int, type: int) -> None:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    game = seat_data.game
    if game.state != "dingque":
        print("can't recv dingQue when game.state == " + game.state)
        return

    if seat_data.que < 0:
        game.numOfQue += 1

    seat_data.que = type

    # 检查玩家可以做的动作
    # 如果4个人都定缺了，通知庄家出牌
    if game.numOfQue == 4:
        construct_game_base_info(game)
        arr = [1, 1, 1, 1]
        for i in range(len(game.gameSeats)):
            arr[i] = game.gameSeats[i].que
        await usermgr.broacast_in_room("game_dingque_finish_push", arr, seat_data.userId, True)
        await usermgr.broacast_in_room("game_playing_push", None, seat_data.userId, True)

        # 进行听牌检查
        for i in range(len(game.gameSeats)):
            duoyu = -1
            gs = game.gameSeats[i]
            if len(gs.holds) == 14:
                # 原实现直接把 pop() 的结果当数字用（14 张时必然有值）；这里照原样直接使用。
                duoyu = js_pop(gs.holds)
                gs.countMap[duoyu] -= 1
            check_can_ting_pai(game, gs)
            if duoyu >= 0:
                gs.holds.append(duoyu)
                gs.countMap[duoyu] += 1

        turn_seat = game.gameSeats[game.turn]
        game.state = "playing"
        # 通知玩家出牌方
        turn_seat.canChuPai = True
        await usermgr.broacast_in_room("game_chupai_push", turn_seat.userId, turn_seat.userId, True)
        # 检查是否可以暗杠或者胡
        # 直杠
        check_can_an_gang(game, turn_seat)
        # 检查胡 用最后一张来检查
        check_can_hu(game, turn_seat, turn_seat.holds[len(turn_seat.holds) - 1])
        # 通知前端
        await send_operations(game, turn_seat, game.chuPai)
    else:
        await usermgr.broacast_in_room(
            "game_dingque_notify_push", seat_data.userId, seat_data.userId, True
        )


async def chu_pai(user_id: int, pai: int) -> None:
    # 原实现是 Number.parseInt(pai)；pai 是数字，parseInt 内部同样先转字符串，
    # 显式 String(pai) 后结果完全一致。
    pai = int(js_parse_int(js_str(pai)))
    # 下面的 setTimeout 闭包里还要用 seat_data，所以这里照原样先取出来再判空。
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    game = seat_data.game
    seat_index = seat_data.seatIndex
    # 如果不该他出，则忽略
    if game.turn != seat_data.seatIndex:
        print("not your turn.")
        return

    if seat_data.hued:
        print('you have already hued. no kidding plz.')
        return

    if seat_data.canChuPai == False:
        print('no need chupai.')
        return

    if has_operations(seat_data):
        print('plz guo before you chupai.')
        return

    # 从此人牌中扣除
    index = js_index_of(seat_data.holds, pai)
    if index == -1:
        print("holds:" + js_str(seat_data.holds))
        print("can't find mj." + js_str(pai))
        return

    seat_data.canChuPai = False
    game.chupaiCnt += 1
    seat_data.guoHuFan = -1

    splice(seat_data.holds, index, 1)
    seat_data.countMap[pai] -= 1
    game.chuPai = pai
    record_game_action(game, seat_data.seatIndex, ACTION_CHUPAI, pai)
    check_can_ting_pai(game, seat_data)

    await usermgr.broacast_in_room(
        "game_chupai_notify_push", {"userId": seat_data.userId, "pai": pai}, seat_data.userId, True
    )

    # 如果出的牌可以胡，则算过胡
    # 原实现做了两次下标访问（第二次在 if 为真时必然存在）；这里取一次到局部变量，语义不变。
    ting_pai_of_chu_pai = seat_data.tingMap.get(game.chuPai)
    if ting_pai_of_chu_pai is not None:
        seat_data.guoHuFan = ting_pai_of_chu_pai.fan

    # 检查是否有人要胡，要碰 要杠
    has_actions = False
    for i in range(len(game.gameSeats)):
        # 玩家自己不检查
        if game.turn == i:
            continue
        ddd = game.gameSeats[i]
        # 已经和牌的不再检查
        if ddd.hued:
            continue

        check_can_hu(game, ddd, pai)
        if seat_data.lastFangGangSeat == -1:
            # ddd.canHu 为真说明 check_can_hu 刚在 tingMap 里命中了 pai；这里照原样直接解引用。
            if ddd.canHu and ddd.guoHuFan >= 0 and ddd.tingMap[pai].fan <= ddd.guoHuFan:
                print("ddd.guoHuFan:" + js_str(ddd.guoHuFan))
                ddd.canHu = False
                await usermgr.send_msg(ddd.userId, "guohu_push", None)
        check_can_peng(game, ddd, pai)
        check_can_dian_gang(game, ddd, pai)
        if has_operations(ddd):
            await send_operations(game, ddd, game.chuPai)
            has_actions = True

    # 如果没有人有操作，则向下一家发牌，并通知他出牌
    if not has_actions:

        async def on_later() -> None:
            await usermgr.broacast_in_room(
                "guo_notify_push",
                {"userId": seat_data.userId, "pai": game.chuPai},
                seat_data.userId,
                True,
            )
            seat_data.folds.append(game.chuPai)
            game.chuPai = -1
            move_to_next_user(game)
            await do_user_mo_pai(game)

        _schedule(500, on_later)


async def peng(user_id: int) -> None:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    game = seat_data.game

    # 如果是他出的牌，则忽略
    if game.turn == seat_data.seatIndex:
        print("it's your turn.")
        return

    # 如果没有碰的机会，则不能再碰
    if seat_data.canPeng == False:
        print("seatData.peng == false")
        return

    # 和的了，就不要再来了
    if seat_data.hued:
        print('you have already hued. no kidding plz.')
        return

    # 如果有人可以胡牌，则需要等待
    i = game.turn
    while True:
        i = (i + 1) % 4
        if i == game.turn:
            break
        else:
            ddd = game.gameSeats[i]
            if ddd.canHu and i != seat_data.seatIndex:
                return

    clear_all_options(game)

    # 验证手上的牌的数目
    pai = game.chuPai
    c = seat_data.countMap.get(pai)
    if c is None or c < 2:
        print("pai:" + js_str(pai) + ",count:" + js_str(c))
        print(js_str(seat_data.holds))
        print("lack of mj.")
        return

    # 进行碰牌处理
    # 扣掉手上的牌
    # 从此人牌中扣除
    for i in range(2):
        index = js_index_of(seat_data.holds, pai)
        if index == -1:
            print("can't find mj.")
            return
        splice(seat_data.holds, index, 1)
        seat_data.countMap[pai] -= 1
    seat_data.pengs.append(pai)
    game.chuPai = -1

    record_game_action(game, seat_data.seatIndex, ACTION_PENG, pai)

    # 广播通知其它玩家
    await usermgr.broacast_in_room(
        "peng_notify_push", {"userid": seat_data.userId, "pai": pai}, seat_data.userId, True
    )

    # 碰的玩家打牌
    move_to_next_user(game, seat_data.seatIndex)

    # 广播通知玩家出牌方
    seat_data.canChuPai = True
    await usermgr.broacast_in_room("game_chupai_push", seat_data.userId, seat_data.userId, True)


def is_playing(user_id: int) -> bool:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        return False

    game = seat_data.game

    if game.state == "idle":
        return False
    return True


async def check_can_qiang_gang(
    game: GameState, turn_seat: GameSeat, seat_data: GameSeat, pai: int
) -> bool:
    has_actions = False
    for i in range(len(game.gameSeats)):
        # 杠牌者不检查
        if seat_data.seatIndex == i:
            continue
        ddd = game.gameSeats[i]
        # 已经和牌的不再检查
        if ddd.hued:
            continue

        check_can_hu(game, ddd, pai)
        if ddd.canHu:
            await send_operations(game, ddd, pai)
            has_actions = True
    if has_actions:
        game.qiangGangContext = QiangGangContext(
            turnSeat=turn_seat,
            seatData=seat_data,
            pai=pai,
            isValid=True,
        )
    else:
        game.qiangGangContext = None
    return game.qiangGangContext is not None


async def do_gang(
    game: GameState,
    turn_seat: GameSeat,
    seat_data: GameSeat,
    gangtype: str,
    num_of_cnt: int,
    pai: int,
) -> None:
    seat_index = seat_data.seatIndex
    game_turn = turn_seat.seatIndex

    is_zhuan_shou_gang = False
    if gangtype == "wangang":
        idx = js_index_of(seat_data.pengs, pai)
        if idx >= 0:
            splice(seat_data.pengs, idx, 1)

        # 如果最后一张牌不是杠的牌，则认为是转手杠
        if seat_data.holds[len(seat_data.holds) - 1] != pai:
            is_zhuan_shou_gang = True
    # 进行碰牌处理
    # 扣掉手上的牌
    # 从此人牌中扣除
    for i in range(num_of_cnt):
        index = js_index_of(seat_data.holds, pai)
        if index == -1:
            print(js_str(seat_data.holds))
            print("can't find mj.")
            return
        splice(seat_data.holds, index, 1)
        seat_data.countMap[pai] -= 1

    record_game_action(game, seat_data.seatIndex, ACTION_GANG, pai)

    # 记录下玩家的杠牌
    if gangtype == "angang":
        seat_data.angangs.append(pai)
        ac = record_user_action(game, seat_data, "angang")
        ac["score"] = game.conf.baseScore * 2
    elif gangtype == "diangang":
        seat_data.diangangs.append(pai)
        ac = record_user_action(game, seat_data, "diangang", game_turn)
        ac["score"] = game.conf.baseScore * 2
        fs = turn_seat
        record_user_action(game, fs, "fanggang", seat_index)
    elif gangtype == "wangang":
        seat_data.wangangs.append(pai)
        if is_zhuan_shou_gang == False:
            ac = record_user_action(game, seat_data, "wangang")
            ac["score"] = game.conf.baseScore
        else:
            record_user_action(game, seat_data, "zhuanshougang")

    check_can_ting_pai(game, seat_data)
    # 通知其他玩家，有人杠了牌
    await usermgr.broacast_in_room(
        "gang_notify_push",
        {"userid": seat_data.userId, "pai": pai, "gangtype": gangtype},
        seat_data.userId,
        True,
    )

    # 变成自己的轮子
    move_to_next_user(game, seat_index)
    # 再次摸牌
    await do_user_mo_pai(game)

    # 只能放在这里。因为过手就会清除杠牌标记
    seat_data.lastFangGangSeat = game_turn


async def gang(user_id: int, pai: int) -> None:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    seat_index = seat_data.seatIndex
    game = seat_data.game

    # 如果没有杠的机会，则不能再杠
    if seat_data.canGang == False:
        print("seatData.gang == false")
        return

    # 和的了，就不要再来了
    if seat_data.hued:
        print('you have already hued. no kidding plz.')
        return

    if js_index_of(seat_data.gangPai, pai) == -1:
        print("the given pai can't be ganged.")
        return

    # 如果有人可以胡牌，则需要等待
    i = game.turn
    while True:
        i = (i + 1) % 4
        if i == game.turn:
            break
        else:
            ddd = game.gameSeats[i]
            if ddd.canHu and i != seat_data.seatIndex:
                return

    num_of_cnt = seat_data.countMap.get(pai)

    gangtype = ""
    # 弯杠 去掉碰牌
    if num_of_cnt == 1:
        gangtype = "wangang"
    elif num_of_cnt == 3:
        gangtype = "diangang"
    elif num_of_cnt == 4:
        gangtype = "angang"
    else:
        print("invalid pai count.")
        return

    game.chuPai = -1
    clear_all_options(game)
    seat_data.canChuPai = False

    await usermgr.broacast_in_room("hangang_notify_push", seat_index, seat_data.userId, True)

    # 如果是弯杠，则需要检查是否可以抢杠
    turn_seat = game.gameSeats[game.turn]
    if num_of_cnt == 1:
        can_qiang_gang = await check_can_qiang_gang(game, turn_seat, seat_data, pai)
        if can_qiang_gang:
            return

    await do_gang(game, turn_seat, seat_data, gangtype, num_of_cnt, pai)


async def hu(user_id: int) -> None:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    seat_index = seat_data.seatIndex
    game = seat_data.game

    # 如果他不能和牌，那和个啥啊
    if seat_data.canHu == False:
        print("invalid request.")
        return

    # 和的了，就不要再来了
    if seat_data.hued:
        print('you have already hued. no kidding plz.')
        return

    # 标记为和牌
    seat_data.hued = True
    hupai = game.chuPai
    is_zimo = False

    turn_seat = game.gameSeats[game.turn]
    seat_data.isGangHu = turn_seat.lastFangGangSeat >= 0
    notify = -1

    if game.qiangGangContext is not None:
        gang_seat = game.qiangGangContext.seatData
        hupai = game.qiangGangContext.pai
        notify = hupai
        ac = record_user_action(game, seat_data, "qiangganghu", gang_seat.seatIndex)
        ac["iszimo"] = False
        record_game_action(game, seat_index, ACTION_HU, hupai)
        seat_data.isQiangGangHu = True
        game.qiangGangContext.isValid = False

        idx = js_index_of(gang_seat.holds, hupai)
        if idx != -1:
            splice(gang_seat.holds, idx, 1)
            gang_seat.countMap[hupai] -= 1
            await usermgr.send_msg(gang_seat.userId, "game_holds_push", gang_seat.holds)
        # 将牌添加到玩家的手牌列表，供前端显示
        seat_data.holds.append(hupai)
        if seat_data.countMap.get(hupai):
            seat_data.countMap[hupai] += 1
        else:
            seat_data.countMap[hupai] = 1

        record_user_action(game, gang_seat, "beiqianggang", seat_index)
    elif game.chuPai == -1:
        hupai = seat_data.holds[len(seat_data.holds) - 1]
        notify = -1
        if seat_data.isGangHu:
            if turn_seat.lastFangGangSeat == seat_index:
                ac = record_user_action(game, seat_data, "ganghua")
                ac["iszimo"] = True
            else:
                diangganghua_zimo = game.conf.dianganghua == 1
                if diangganghua_zimo:
                    ac = record_user_action(game, seat_data, "dianganghua")
                    ac["iszimo"] = True
                else:
                    ac = record_user_action(game, seat_data, "dianganghua", turn_seat.lastFangGangSeat)
                    ac["iszimo"] = False
        else:
            ac = record_user_action(game, seat_data, "zimo")
            ac["iszimo"] = True

        is_zimo = True
        record_game_action(game, seat_index, ACTION_ZIMO, hupai)
    else:
        notify = game.chuPai
        # 将牌添加到玩家的手牌列表，供前端显示
        seat_data.holds.append(game.chuPai)
        if seat_data.countMap.get(game.chuPai):
            seat_data.countMap[game.chuPai] += 1
        else:
            seat_data.countMap[game.chuPai] = 1

        print(js_str(seat_data.holds))

        at = "hu"
        # 炮胡
        if turn_seat.lastFangGangSeat >= 0:
            at = "gangpaohu"

        ac = record_user_action(game, seat_data, at, game.turn)
        ac["iszimo"] = False

        # 毛转雨
        if turn_seat.lastFangGangSeat >= 0:
            for i in range(len(turn_seat.actions) - 1, -1, -1):
                t = turn_seat.actions[i]
                if t["type"] == "diangang" or t["type"] == "wangang" or t["type"] == "angang":
                    t["state"] = "nop"
                    t["payTimes"] = 0

                    nac = {
                        "type": "maozhuanyu",
                        "owner": turn_seat,
                        "ref": t,
                    }
                    seat_data.actions.append(nac)
                    break

        # 记录玩家放炮信息
        fs = game.gameSeats[game.turn]
        record_user_action(game, fs, "fangpao", seat_index)

        record_game_action(game, seat_index, ACTION_HU, hupai)

        game.fangpaoshumu += 1

        if game.fangpaoshumu > 1:
            game.yipaoduoxiang = seat_index

    if game.firstHupai < 0:
        game.firstHupai = seat_index

    # 保存番数
    # check_can_hu 刚命中过这张牌，tingMap 里一定有它；这里照原样直接解引用。
    ti = seat_data.tingMap[hupai]
    seat_data.fan = ti.fan
    seat_data.pattern = ti.pattern
    seat_data.iszimo = is_zimo
    # 如果是最后一张牌，则认为是海底胡
    seat_data.isHaiDiHu = game.currentIndex == len(game.mahjongs)
    game.hupaiList.append(seat_data.seatIndex)

    if game.conf.tiandihu:
        if game.chupaiCnt == 0 and game.button == seat_data.seatIndex and game.chuPai == -1:
            seat_data.isTianHu = True
        elif (
            game.chupaiCnt == 1
            and game.turn == game.button
            and game.button != seat_data.seatIndex
            and game.chuPai != -1
        ):
            seat_data.isDiHu = True

    clear_all_options(game, seat_data)

    # 通知前端，有人和牌了
    await usermgr.broacast_in_room(
        "hu_push", {"seatindex": seat_index, "iszimo": is_zimo, "hupai": notify}, seat_data.userId, True
    )

    #
    if game.lastHuPaiSeat == -1:
        game.lastHuPaiSeat = seat_index
    else:
        # 原实现这里读的是 game.lastFangGangSeat——GameState 上从未被写入的字段，运行结果是 NaN，
        # 于是 `cur > lp` 恒为 false。这里如实写出"不赋值"，不要凭空造一个字段。
        pass

    # 如果只有一家没有胡，则结束
    num_of_hued = 0
    for i in range(len(game.gameSeats)):
        ddd = game.gameSeats[i]
        if ddd.hued:
            num_of_hued += 1
    # 和了三家
    if num_of_hued == 3:
        await do_game_over(game, seat_data.userId)
        return

    # 清空所有非胡牌操作
    for i in range(len(game.gameSeats)):
        ddd = game.gameSeats[i]
        ddd.canPeng = False
        ddd.canGang = False
        ddd.canChuPai = False
        await send_operations(game, ddd, hupai)

    # 如果还有人可以胡牌，则等待
    for i in range(len(game.gameSeats)):
        ddd = game.gameSeats[i]
        if ddd.canHu:
            return

    # 和牌的下家继续打
    clear_all_options(game)
    game.turn = game.lastHuPaiSeat
    move_to_next_user(game)
    await do_user_mo_pai(game)


async def guo(user_id: int) -> None:
    seat_data = _game_seats_of_users.get(user_id)
    if seat_data is None:
        print("can't find user game data.")
        return

    seat_index = seat_data.seatIndex
    game = seat_data.game

    # 如果玩家没有对应的操作，则也认为是非法消息
    if (seat_data.canGang or seat_data.canPeng or seat_data.canHu) == False:
        print("no need guo.")
        return

    # 如果是玩家自己的轮子，不是接牌，则不需要额外操作
    do_nothing = game.chuPai == -1 and game.turn == seat_index

    await usermgr.send_msg(seat_data.userId, "guo_result", None)
    clear_all_options(game, seat_data)

    # 这里还要处理过胡的情况
    # 注意：clear_all_options 刚把 canHu 置成 False，所以这个分支运行时永远不会成立——
    # 原实现如此，照原样保留（不要"顺手修"）。
    if game.chuPai >= 0 and seat_data.canHu:
        # 原实现直接解引用 tingMap[game.chuPai]；这里照原样直接解引用。
        seat_data.guoHuFan = seat_data.tingMap[game.chuPai].fan

    if do_nothing:
        return

    # 如果还有人可以操作，则等待
    for i in range(len(game.gameSeats)):
        ddd = game.gameSeats[i]
        if has_operations(ddd):
            return

    # 如果是已打出的牌，则需要通知。
    if game.chuPai >= 0:
        uid = game.gameSeats[game.turn].userId
        await usermgr.broacast_in_room(
            "guo_notify_push", {"userId": uid, "pai": game.chuPai}, seat_data.userId, True
        )
        seat_data.folds.append(game.chuPai)
        game.chuPai = -1

    qiang_gang_context = game.qiangGangContext
    # 清除所有的操作
    clear_all_options(game)

    if qiang_gang_context is not None and qiang_gang_context.isValid:
        await do_gang(
            game,
            qiang_gang_context.turnSeat,
            qiang_gang_context.seatData,
            "wangang",
            1,
            qiang_gang_context.pai,
        )
    else:
        # 下家摸牌
        move_to_next_user(game)
        await do_user_mo_pai(game)


def has_began(room_id: str) -> bool:
    game = _games.get(room_id)
    if game is not None:
        return True
    room_info = roommgr.get_room(room_id)
    if room_info is not None:
        return room_info.numOfGames > 0
    return False


_dissolving_list: list[str] = []


async def do_dissolve(room_id: str) -> None:
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return None

    game = _games.get(room_id)
    await do_game_over(game, room_info.seats[0].userId, True)


def dissolve_request(room_id: str, user_id: int) -> RoomInfo | None:
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return None

    if room_info.dr is not None:
        return None

    seat_index = roommgr.get_user_seat(user_id)
    if seat_index is None:
        return None

    room_info.dr = DissolveRequest(
        endTime=now_ms() + 30000,
        states=[False, False, False, False],
    )
    room_info.dr.states[seat_index] = True

    _dissolving_list.append(room_id)

    return room_info


def dissolve_agree(room_id: str, user_id: int, agree: bool) -> RoomInfo | None:
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return None

    if room_info.dr is None:
        return None

    seat_index = roommgr.get_user_seat(user_id)
    if seat_index is None:
        return None

    if agree:
        room_info.dr.states[seat_index] = True
    else:
        room_info.dr = None
        idx = js_index_of(_dissolving_list, room_id)
        if idx != -1:
            splice(_dissolving_list, idx, 1)
    return room_info


async def _update() -> None:
    for i in range(len(_dissolving_list) - 1, -1, -1):
        room_id = _dissolving_list[i]

        room_info = roommgr.get_room(room_id)
        if room_info is not None and room_info.dr is not None:
            if now_ms() > room_info.dr.endTime:
                print("delete room and games")
                await do_dissolve(room_id)
                splice(_dissolving_list, i, 1)
        else:
            splice(_dissolving_list, i, 1)


async def _update_loop() -> None:
    """对应 TS 末尾的 `setInterval(update,1000)`：每 1000ms 跑一次 `_update()`。"""
    while True:
        await asyncio.sleep(1)
        await _update()


# 原文件末尾有一段被注释掉的调试代码（mokgame / mokseat 手写座位，用来单独试 checkCanAnGang），
# 只在本地调试时用过，这里保留说明，不参与运行。

# 自检：本模块必须提供 roommgr 通过 `GameManagerProtocol` 调用的全部函数。
# 对应 TS 末尾的 `_gameManagerContract`（Node 版由 tsc 在编译期检查；Python 没有编译期检查，
# 这里改成 import 时的一次运行时自检，缺了哪个函数就直接报出来）。
for _required in (
    "set_ready",
    "begin",
    "huan_san_zhang",
    "ding_que",
    "chu_pai",
    "peng",
    "is_playing",
    "gang",
    "hu",
    "guo",
    "has_began",
    "do_dissolve",
    "dissolve_request",
    "dissolve_agree",
):
    if not callable(globals().get(_required)):
        raise RuntimeError("gamemgr_xzdd 缺少房间管理需要的接口：" + _required)
del _required

# 对应 TS 末尾的 `setInterval(update,1000)`：模块被 import 时起一次，之后每秒跑一次。
# 这正是 `roommgr.load_game_manager` 必须懒加载的原因（两份 gamemgr 都起定时器就重复了）。
try:
    asyncio.get_running_loop().create_task(_update_loop())
except RuntimeError:
    pass  # 没有事件循环时（同步 import）不起定时器
