"""血战到底玩法实现（`conf.type == "xlch"` 时由 `roommgr` 懒加载这一份）。

对应 `server/game_server/gamemgr_xlch.ts`（2488 行），逐行移植：函数名、常量值、判定顺序、
推送事件名与载荷字段、日志文案、`setTimeout` 延时都与原实现一致。

与 Node 版**有意**的差异：

1. 需要 IO 的函数改成 `async def` + `await`（Node 版是同步函数 + 回调 + `setTimeout`）。
   `db.*` / `usermgr.send_msg` / `usermgr.broacast_in_room` / `usermgr.kick_all_in_room` /
   `roommgr.destroy` 都是协程，必须 await；`roommgr.get_room` / `get_user_room` / `get_user_seat`
   / `set_ready` / `is_creator`、`mjutils.*`、`crypto.*` 是同步的。
2. `setTimeout` 用模块内的 `_schedule(delay_ms, fn)`（内部 `asyncio.sleep` + `create_task`）代替；
   调用点写 `_schedule(500, on_later)`，`on_later` 是无参协程函数。延时值不变（500ms / 1500ms）。
3. 模块级状态用下划线前缀的模块变量（`_games` / `_game_seats_of_users` / `_dissolving_list`），
   不改成类。
4. 少数地方原本会 `throw` 崩进程（例如 `calculateResult` 里 `isTinged(ac.owner)` 在 owner 为
   null 时读属性、`isQingYiSe` 里读空 holds 的第 0 张），Python 版照原样写，异常冒泡到调用它的
   协程（socket 处理器会记录日志）。**不要加防御性判空返回来"修"它**。
5. 上线载荷（`huInfo` 的元素、`actions` 的记录、`game_over_push` 的 results/endinfo、
   `game_sync_push` 的 seats 等）一律用**普通 dict**：`JSON.stringify` 会丢掉值为 `undefined`
   的键、保留 `null`，只有 dict 才能逐字复现"哪些键出现、哪些键不出现"。
   `GameSeat.huInfo` / `GameSeat.actions` 因此是 `list[dict]`。
6. 末尾的 `setInterval(update,1000)` 改成 import 时创建一次 `_update_loop()` 任务（没有事件
   循环时[同步 import]跳过）。**这正是 `roommgr.load_game_manager` 必须懒加载的原因**。
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
    """对应 JS 的 `setTimeout`；`fn` 是无参协程函数。

    原实现里 `setTimeout` 是同步注册、异步执行；这里 `_schedule` 本身也是同步的，
    只在内部把"睡够 delay_ms 再执行 fn"做成一个任务，调用点的时机一致。
    """

    async def runner() -> None:
        await asyncio.sleep(delay_ms / 1000)
        await fn()

    asyncio.get_running_loop().create_task(runner())


def get_mj_type(pai: int) -> int | None:
    if pai >= 0 and pai < 9:
        # 筒
        return 0
    elif pai >= 9 and pai < 18:
        # 条
        return 1
    elif pai >= 18 and pai < 27:
        # 万
        return 2
    return None


def shuffle(game: GameState) -> None:
    mahjongs = game.mahjongs

    # 原实现这里有一段被注释掉的调试发牌代码（前 12 张筒、12 张条、12 张万、12 张 3，
    # 其余全部填 4，然后直接 return）；正式发牌不走那一段，这里只留说明。

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

    for key in js_keys(seat_data.countMap):
        pai = int(key)
        if get_mj_type(pai) != seat_data.que:
            # for...in 的键是字符串，原实现写成 countMap[key]；换成已经取整的 pai，语义不变。
            c = seat_data.countMap.get(pai)
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
        # 原实现这里的变量也叫 pai（形参），改名只为过 TS 的重复声明检查，语义不变。
        peng_pai = seat_data.pengs[i]
        if seat_data.countMap.get(peng_pai) == 1:
            seat_data.canGang = True
            seat_data.gangPai.append(peng_pai)


def check_can_hu(game: GameState, seat_data: GameSeat, target_pai: int) -> None:
    game.lastHuPaiSeat = -1
    if get_mj_type(target_pai) == seat_data.que:
        return
    seat_data.canHu = False
    for k in js_keys(seat_data.tingMap):
        # for...in 的键是字符串，原实现直接与数字 targetPai 比较（`==` 会隐式转换）；
        # 显式取整后语义不变。
        if target_pai == int(k):
            seat_data.canHu = True


def clear_all_options(game: GameState, seat_data: GameSeat | None = None) -> None:
    def fn_clear(sd: GameSeat) -> None:
        sd.canPeng = False
        sd.canGang = False
        sd.gangPai = []
        sd.canHu = False
        sd.lastFangGangSeat = -1

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
        # 原实现声明了一个局部变量 hu = false，但从未使用；保留占位。
        hu = False
        dan_pai = -1
        pair_count = 0
        for k in js_keys(seat_data.countMap):
            # for...in 的键是字符串，原实现既拿它当 countMap 的下标、又直接赋给 danPai；
            # 这里统一用取整后的数字，语义不变（对象键本来就是字符串）。
            c = seat_data.countMap[int(k)]
            if c == 2 or c == 3:
                pair_count += 1
            elif c == 4:
                pair_count += 2

            if c == 1 or c == 3:
                # 如果已经有单牌了，表示不止一张单牌，并没有下叫。直接闪
                if dan_pai >= 0:
                    break
                dan_pai = int(k)

        # 检查是否有6对 并且单牌是不是目标牌
        if pair_count == 6:
            # 七对只能和一张，就是手上那张单牌
            # 七对的番数＝ 2番+N个4个牌（即龙七对）
            seat_data.tingMap[dan_pai] = TingPaiInfo(pattern="7pairs", fan=2)
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
        # 同上：原实现把 for...in 的字符串键 push 进 arr 再当牌 id 用，这里显式转数字。
        c = seat_data.countMap[int(k)]
        if c == 1:
            single_count += 1
            arr.append(int(k))
        elif c == 2:
            pair_count += 1
            arr.append(int(k))
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

    # 原实现这里有三行被注释掉的 console.log 调试输出（holds / countMap / 计数汇总）。
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

        # 原实现在对象字面量之后才补 data.si，所以这里不在字面量里写 si。
        data = {
            "pai": pai,
            "hu": seat_data.canHu,
            "peng": seat_data.canPeng,
            "gang": seat_data.canGang,
            "gangpai": seat_data.gangPai,
        }

        # 如果可以有操作，则进行操作
        await usermgr.send_msg(seat_data.userId, 'game_action_push', data)

        # 原实现把 data.si 写在 sendMsg 之后，所以 si 从来没被发出去——保留这个死赋值。
        # （send_msg 内部先序列化再 await 写出，因此这里改 dict 影响不到已经发出的包。）
        data["si"] = seat_data.seatIndex
    else:
        # 原实现只传两个实参（载荷为 undefined）；usermgr.send_msg(uid, 事件, None)
        # 在线上同样是 [事件,null]，与 socket.emit(事件,undefined) 一致。
        await usermgr.send_msg(seat_data.userId, 'game_action_push', None)


def move_to_next_user(game: GameState, next_seat: int | None = None) -> None:
    game.fangpaoshumu = 0
    # 找到下一个没有和牌的玩家
    if next_seat is None:
        game.turn += 1
        game.turn %= 4
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
        await usermgr.broacast_in_room('mj_count_push', num_of_mj, turn_seat.userId, True)

    record_game_action(game, game.turn, ACTION_MOPAI, pai)

    # 通知前端新摸的牌
    await usermgr.send_msg(turn_seat.userId, 'game_mopai_push', pai)
    # 检查是否可以暗杠或者胡
    # 检查胡，直杠，弯杠
    if not turn_seat.hued:
        check_can_an_gang(game, turn_seat)

    # 如果未胡牌，或者摸起来的牌可以杠，才检查弯杠
    if (not turn_seat.hued) or turn_seat.holds[len(turn_seat.holds) - 1] == pai:
        check_can_wan_gang(game, turn_seat, pai)

    # 检查看是否可以和
    check_can_hu(game, turn_seat, pai)

    # 广播通知玩家出牌方
    turn_seat.canChuPai = True
    await usermgr.broacast_in_room('game_chupai_push', turn_seat.userId, turn_seat.userId, True)

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


# 是否需要查大叫(有人没有下叫)
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

    # 如果没有任何一个人叫牌，则不需要查叫
    if num_of_tinged == 0:
        return False

    # 如果都听牌了，也不需要查叫
    if num_of_untinged == 0:
        return False
    return True


def find_max_fan_ting_pai(ts: GameSeat) -> TingPaiInfo | None:
    # 找出最大番
    cur: TingPaiInfo | None = None
    for k in js_keys(ts.tingMap):
        # 原实现直接解引用 tingMap 的值，并就地给它补一个 pai 字段；这里对象不变。
        tpai = ts.tingMap[int(k)]
        if cur is None or tpai.fan > cur.fan:
            cur = tpai
            cur.pai = int(k)
    return cur


def find_un_tinged_players(game: GameState) -> list[int]:
    arr: list[int] = []
    for i in range(len(game.gameSeats)):
        ts = game.gameSeats[i]
        # 如果没有胡，且没有听牌
        if not ts.hued and not is_tinged(ts):
            arr.append(i)
    return arr


def get_num_of_gen(seat_data: GameSeat) -> int:
    num_of_gangs = (
        len(seat_data.diangangs) + len(seat_data.wangangs) + len(seat_data.angangs)
    )
    for k in range(len(seat_data.pengs)):
        pai = seat_data.pengs[k]
        if seat_data.countMap.get(pai) == 1:
            num_of_gangs += 1
    # 原实现在这里复用了同名的 k（数字 -> 字符串），改成 key 只是为了过 TS 的重复声明检查。
    for key in js_keys(seat_data.countMap):
        if seat_data.countMap.get(int(key)) == 4:
            num_of_gangs += 1
    return num_of_gangs


def cha_jiao(game: GameState) -> None:
    arr = find_un_tinged_players(game)
    if len(arr) == 0:
        return
    for i in range(len(game.gameSeats)):
        ts = game.gameSeats[i]
        # 如果听牌了，则未叫牌的人要给钱
        if is_tinged(ts):
            # 已听牌时 find_max_fan_ting_pai 一定返回非 None。
            cur = find_max_fan_ting_pai(ts)
            ts.huInfo.append(
                {
                    "ishupai": True,
                    "action": "chadajiao",
                    "fan": cur.fan,
                    "pattern": cur.pattern,
                    "pai": cur.pai,
                    "numofgen": get_num_of_gen(ts),
                }
            )

            for j in range(len(arr)):
                game.gameSeats[arr[j]].huInfo.append(
                    {
                        "action": "beichadajiao",
                        "target": i,
                        "index": len(ts.huInfo) - 1,
                    }
                )


def calculate_result(game: GameState, room_info: RoomInfo) -> None:
    is_need_cha_da_jia = need_cha_da_jiao(game)
    if is_need_cha_da_jia:
        cha_jiao(game)

    base_score = game.conf.baseScore

    for i in range(len(game.gameSeats)):
        sd = game.gameSeats[i]
        # 对所有胡牌的玩家进行统计
        if is_tinged(sd):
            # 收杠钱
            additonalscore = 0
            for a in range(len(sd.actions)):
                # 下面按类型读 targets / score（这些记录一定带这两样）；运行时对象不变。
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
                    # 原实现直接传 ac.owner：owner 为 null/undefined 时 is_tinged 会因读
                    # seat_data.tingMap 抛 AttributeError（owner 只在本分支末尾被置 null），
                    # 这里照原样保留该行为，不加判空。
                    mao_owner = ac.get("owner")
                    if is_tinged(mao_owner):
                        # 如果
                        ref = ac.get("ref")
                        acscore = ref["score"]
                        total = len(ref["targets"]) * acscore * base_score
                        additonalscore += total
                        # 扣掉目标方的分
                        if ref["payTimes"] == 0:
                            for t in range(len(ref["targets"])):
                                six = ref["targets"][t]
                                game.gameSeats[six].score -= acscore * base_score
                        else:
                            # 如果已经被扣过一次了，则由杠牌这家赔
                            mao_owner.score -= total
                        ref["payTimes"] += 1
                        ac["owner"] = None
                        ac["ref"] = None

            if is_qing_yi_se(sd):
                sd.qingyise = True

            if game.conf.menqing:
                sd.isMenQing = is_men_qing(sd)

            # 金钩胡
            if len(sd.holds) == 1 or len(sd.holds) == 2:
                sd.isJinGouHu = True

            sd.numAnGang = len(sd.angangs)
            sd.numMingGang = len(sd.wangangs) + len(sd.diangangs)

            # 进行胡牌结算
            for j in range(len(sd.huInfo)):
                # ishupai 的记录按下方的写入形状一定带 fan / pai / numofgen 等字段。
                # 注意：beichadajiao / beiqianggang / fangpao 这些记录**没有** ishupai 键，
                # JS 读到的是 undefined（假值）；这里必须用 get，否则会 KeyError。
                info = sd.huInfo[j]
                if not info.get("ishupai"):
                    sd.numDianPao += 1
                    continue
                # 统计自己的番子和分数
                # 基础番(平胡0番，对对胡1番、七对2番) + 清一色2番 + 杠+1番
                # 杠上花+1番，杠上炮+1番 抢杠胡+1番，金钩胡+1番，海底胡+1番
                fan = info["fan"]
                sd.holds.append(info["pai"])
                if sd.countMap.get(info["pai"]) is not None:
                    sd.countMap[info["pai"]] += 1
                else:
                    sd.countMap[info["pai"]] = 1

                if sd.qingyise:
                    fan += 2

                # 金钩胡
                if sd.isJinGouHu:
                    fan += 1

                # chadajiao 记录没有 isHaiDiHu / isTianHu / isDiHu / iszimo / target 这些键，
                # JS 读到 undefined（假值），所以一律用 get。
                if info.get("isHaiDiHu"):
                    fan += 1

                if game.conf.tiandihu:
                    if info.get("isTianHu"):
                        fan += 3
                    elif info.get("isDiHu"):
                        fan += 2

                isjiangdui = False
                if game.conf.jiangdui:
                    if info["pattern"] == "7pairs":
                        if info["numofgen"] > 0:
                            info["numofgen"] -= 1
                            # 原实现这两行写的是 `==`（比较，不是赋值），等于什么都没做；照原样保留。
                            info["pattern"] == "l7pairs"
                            isjiangdui = is_jiang_dui(sd)
                            if isjiangdui:
                                info["pattern"] == "j7paris"
                                fan += 2
                            else:
                                fan += 1
                    elif info["pattern"] == "duidui":
                        isjiangdui = is_jiang_dui(sd)
                        if isjiangdui:
                            info["pattern"] = "jiangdui"
                            fan += 2

                if game.conf.menqing:
                    # 不是将对，才检查中张
                    if not isjiangdui:
                        sd.isZhongZhang = is_zhong_zhang(sd)
                        if sd.isZhongZhang:
                            fan += 1

                    if sd.isMenQing:
                        fan += 1

                fan += info["numofgen"]

                if (
                    info["action"] == "ganghua"
                    or info["action"] == "dianganghua"
                    or info["action"] == "gangpaohu"
                    or info["action"] == "qiangganghu"
                ):
                    fan += 1

                extra_score = 0
                if info.get("iszimo"):
                    if game.conf.zimo == 0:
                        # 自摸加底
                        extra_score = base_score
                    elif game.conf.zimo == 1:
                        fan += 1
                    else:
                        # nothing.
                        pass
                # 和牌的玩家才加这个分
                score = compute_fan_score(game, fan) + extra_score
                if info["action"] == "chadajiao":
                    # 收所有没有叫牌的人的钱
                    for t in range(len(game.gameSeats)):
                        if not is_tinged(game.gameSeats[t]):
                            game.gameSeats[t].score -= score
                            sd.score += score
                            # 被查叫次数
                            if game.gameSeats[t] != sd:
                                game.gameSeats[t].numChaJiao += 1
                elif info.get("iszimo"):
                    # 收所有人的钱
                    sd.score += score * len(game.gameSeats)
                    for t in range(len(game.gameSeats)):
                        game.gameSeats[t].score -= score
                    sd.numZiMo += 1
                else:
                    # 收放炮者的钱
                    sd.score += score
                    game.gameSeats[info["target"]].score -= score
                    sd.numJiePao += 1

                # 撤除胡的那张牌
                sd.holds.pop()
                sd.countMap[info["pai"]] -= 1

                if fan > game.conf.maxFan:
                    fan = game.conf.maxFan
                info["fan"] = fan
            # 一定要用 += 。 因为此时的sd.score可能是负的
            sd.score += additonalscore
        else:
            for a in range(len(sd.actions) - 1, -1, -1):
                ac = sd.actions[a]
                if ac["type"] == "angang" or ac["type"] == "wangang" or ac["type"] == "diangang":
                    # 如果3家都胡牌，则需要结算。否则认为是查叫
                    if is_need_cha_da_jia:
                        splice(sd.actions, a, 1)
                    else:
                        if ac.get("state") != "nop":
                            acscore = ac["score"]
                            sd.score += len(ac["targets"]) * acscore * base_score
                            # 扣掉目标方的分
                            for t in range(len(ac["targets"])):
                                six = ac["targets"][t]
                                game.gameSeats[six].score -= acscore * base_score


async def do_game_over(game: GameState | None, user_id: int, force_end: bool | None = None) -> None:
    # 运行时的判空与 return 与原来完全一致（原实现的 `!` 只是给 TS 看的）。
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
                endinfo.append(
                    {
                        "numzimo": rs.numZiMo,
                        "numjiepao": rs.numJiePao,
                        "numdianpao": rs.numDianPao,
                        "numangang": rs.numAnGang,
                        "numminggang": rs.numMingGang,
                        "numchadajiao": rs.numChaJiao,
                    }
                )

        await usermgr.broacast_in_room(
            'game_over_push', {"results": results, "endinfo": endinfo}, user_id, True
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

            # 原实现的对象字面量里，qingyise / menqing / jingouhu 的值可能是 undefined，
            # `JSON.stringify` 会把它们整个键丢掉；所以这里按"原实现是否会写入"来决定加不加键。
            user_rt: dict[str, Any] = {
                "userId": sd.userId,
                "actions": [],
                "pengs": sd.pengs,
                "wangangs": sd.wangangs,
                "diangangs": sd.diangangs,
                "angangs": sd.angangs,
                "holds": sd.holds,
                "score": sd.score,
                "totalscore": rs.score,
            }
            if sd.qingyise:
                user_rt["qingyise"] = True
            if game.conf.menqing:
                # sd.isMenQing 只在 conf.menqing 为真时被赋值，值可能是 False——那也要出现。
                user_rt["menqing"] = sd.isMenQing
            if sd.isJinGouHu:
                user_rt["jingouhu"] = True
            user_rt["huinfo"] = sd.huInfo

            for k in range(len(sd.actions)):
                # 原实现是 for...in 遍历数组（下标按数值升序），把 `actions[actionIndex]`
                # 逐个填上；等价于按顺序 append。
                user_rt["actions"].append({"type": sd.actions[k]["type"]})
            results.append(user_rt)

            dbresult[i] = sd.score
            _game_seats_of_users.pop(sd.userId, None)
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
        _ret = await store_game(game)
        await db.update_game_result(room_info.uuid, game.gameIndex, dbresult)

        # 记录玩家操作
        action_str = json.dumps(game.actionList, separators=(",", ":"))
        await db.update_game_action_records(room_info.uuid, game.gameIndex, action_str)

        # 保存游戏局数
        await db.update_num_of_turns(room_id, room_info.numOfGames)

        # 如果是第一次，则扣除房卡
        if room_info.numOfGames == 1:
            cost = 2
            if room_info.conf.maxGames == 8:
                cost = 3
            # 返回值被忽略（原实现如此）。
            await db.cost_gems(game.gameSeats[0].userId, cost)

        is_end = room_info.numOfGames >= room_info.conf.maxGames
        await fn_notice_result(is_end)


def record_user_action(
    game: GameState,
    seat_data: GameSeat,
    type: str,
    target: int | list[int] | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {"type": type, "targets": []}
    if target is not None:
        if isinstance(target, int):
            d["targets"].append(target)
        else:
            d["targets"] = target
    else:
        for i in range(len(game.gameSeats)):
            s = game.gameSeats[i]
            # 血流成河，所有自摸，暗杠，弯杠，都算三家
            if i != seat_data.seatIndex:  # && s.hued == false
                d["targets"].append(i)

    seat_data.actions.append(d)
    return d


def record_game_action(game: GameState, si: int, action: int, pai: int | None = None) -> None:
    game.actionList.append(si)
    game.actionList.append(action)
    if pai is not None:
        game.actionList.append(pai)


async def set_ready(user_id: int, callback: Any = None) -> None:
    # `callback` 在签名里保留（对应原实现的 callback?），但没有任何调用点会传它。
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
        remaining_games = room_info.conf.maxGames - room_info.numOfGames

        # 原实现在对象字面量之后才补 data.seats，所以这里不在字面量里写 seats。
        data: dict[str, Any] = {
            "state": game.state,
            "numofmj": num_of_mj,
            "button": game.button,
            "turn": game.turn,
            "chuPai": game.chuPai,
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
                "huinfo": sd.huInfo,
                "iszimo": sd.iszimo,
            }
            if sd.userId == user_id:
                s["holds"] = sd.holds
                s["huanpais"] = sd.huanpais
                seat_data = sd
            else:
                # 原实现是 `sd.huanpais ? [] : null`；JS 里空数组也是真值，所以要用 is not None。
                s["huanpais"] = [] if sd.huanpais is not None else None
            data["seats"].append(s)

        # 同步整个信息给客户端
        await usermgr.send_msg(user_id, 'game_sync_push', data)
        # 循环里必然有一次命中自己的座位。
        await send_operations(game, seat_data, game.chuPai)


async def store_single_history(user_id: int, history: dict[str, Any]) -> None:
    data = await db.get_user_history(user_id)
    if data is None:
        data = []
    while len(data) >= 10:
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
        # 原实现从空对象开始逐个字段赋值，这里同样从一个空 dict 开始。
        hs: dict[str, Any] = {}
        history["seats"][i] = hs
        hs["userid"] = rs.userId
        hs["name"] = crypto.to_base64(rs.name)
        hs["score"] = rs.score

    for i in range(len(seats)):
        s = seats[i]
        await store_single_history(s.userId, history)


def construct_game_base_info(game: GameState) -> None:
    base_info = {
        "type": game.conf.type,
        "button": game.button,
        "index": game.gameIndex,
        "mahjongs": game.mahjongs,
        "game_seats": [None] * 4,
    }
    for i in range(4):
        base_info["game_seats"][i] = game.gameSeats[i].holds
    game.baseInfoJson = json.dumps(base_info, separators=(",", ":"))


async def store_game(game: GameState) -> int | None:
    # 原实现把回调透传给 db.create_game；这里直接 await，返回自增主键。
    return await db.create_game(game.roomInfo.uuid, game.gameIndex, game.baseInfoJson)


# 开始新的一局
async def begin(room_id: str) -> None:
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return
    seats = room_info.seats

    # 原实现的对象里没有 lastHuPaiSeat / qiangGangContext / huanpaiMethod / baseInfoJson 这几个
    # 字段（它们由后续流程补上）；这里用 GameState 的默认值覆盖同一批字段。
    # `actionList: []` 这样的空数组也照原样。
    game = GameState(
        conf=room_info.conf,
        roomInfo=room_info,
        gameIndex=room_info.numOfGames,
        button=room_info.nextButton,
        mahjongs=[0] * 108,
        currentIndex=0,
        gameSeats=[None] * 4,
        numOfQue=0,
        turn=0,
        chuPai=-1,
        state="idle",
        firstHupai=-1,
        yipaoduoxiang=-1,
        fangpaoshumu=-1,
        actionList=[],
        chupaiCnt=0,
    )

    room_info.numOfGames += 1

    for i in range(4):
        # 原实现从空对象开始逐个字段赋值；这里同样从一个空 GameSeat 开始。
        data = GameSeat()
        game.gameSeats[i] = data

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
        #
        data.actions = []

        # 是否是自摸
        data.iszimo = False
        data.isGangHu = False
        data.fan = 0
        data.score = 0
        data.huInfo = []

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
        await usermgr.send_msg(s.userId, 'game_holds_push', game.gameSeats[i].holds)
        # 通知还剩多少张牌
        await usermgr.send_msg(s.userId, 'mj_count_push', num_of_mj)
        # 通知还剩多少局
        await usermgr.send_msg(s.userId, 'game_num_push', room_info.numOfGames)
        # 通知游戏开始
        await usermgr.send_msg(s.userId, 'game_begin_push', game.button)

        # 原实现写的是 `huansanzhang == true`（hsz 是数字）；`== 1` 与之等价（true 转成 1），
        # 语义不变。
        if huansanzhang == 1:
            game.state = "huanpai"
            # 通知准备换牌
            await usermgr.send_msg(s.userId, 'game_huanpai_push', None)
        else:
            game.state = "dingque"
            # 通知准备定缺
            await usermgr.send_msg(s.userId, 'game_dingque_push', None)


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
    await usermgr.send_msg(seat_data.userId, 'game_holds_push', seat_data.holds)

    for i in range(len(game.gameSeats)):
        sd = game.gameSeats[i]
        if sd == seat_data:
            rd = {
                "si": seat_data.userId,
                "huanpais": seat_data.huanpais,
            }
            await usermgr.send_msg(sd.userId, 'huanpai_notify', rd)
        else:
            rd = {
                "si": seat_data.userId,
                "huanpais": [],
            }
            await usermgr.send_msg(sd.userId, 'huanpai_notify', rd)

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
    # Math.random()（jscompat 没有单独的助手，标准库 random.random() 分布一致）。
    f = random.random()
    s = game.gameSeats
    huanpai_method = 0
    # 对家换牌
    # 上面已经确认过四家的 huanpais 都非空。
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
        # 原实现复用同名的 var userId（函数作用域），这里用 uid；之后不再使用 userId，语义不变。
        uid = s[i].userId
        await usermgr.send_msg(uid, 'game_huanpai_over_push', rd)

        await usermgr.send_msg(uid, 'game_holds_push', s[i].holds)
        # 通知准备定缺
        await usermgr.send_msg(uid, 'game_dingque_push', None)


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
        await usermgr.broacast_in_room('game_dingque_finish_push', arr, seat_data.userId, True)
        await usermgr.broacast_in_room('game_playing_push', None, seat_data.userId, True)

        # 进行听牌检查
        for i in range(len(game.gameSeats)):
            duoyu = -1
            gs = game.gameSeats[i]
            if len(gs.holds) == 14:
                # 原实现直接把 pop() 的结果当数字用（14 张时必然有值）。
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
        await usermgr.broacast_in_room('game_chupai_push', turn_seat.userId, turn_seat.userId, True)
        # 检查是否可以暗杠或者胡
        # 直杠
        check_can_an_gang(game, turn_seat)
        # 检查胡 用最后一张来检查
        check_can_hu(game, turn_seat, turn_seat.holds[len(turn_seat.holds) - 1])
        # 通知前端
        await send_operations(game, turn_seat, game.chuPai)
    else:
        await usermgr.broacast_in_room(
            'game_dingque_notify_push', seat_data.userId, seat_data.userId, True
        )


async def chu_pai(user_id: int, pai: int) -> None:
    # 原实现是 Number.parseInt(pai)；pai 是数字，parseInt 内部同样先转字符串，
    # 显式 String(pai) 后结果完全一致（js_parse_int 内部就做 String 转换）。
    pai = int(js_parse_int(pai))
    # 下面的 setTimeout 闭包里还要用 seat_data，所以这里先取出来，运行时的判空与 return 原样保留。
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

    if seat_data.canChuPai == False:
        print('no need chupai.')
        return

    if has_operations(seat_data):
        print('plz guo before you chupai.')
        return

    # 如果是胡了的人，则只能打最后一张牌
    if seat_data.hued:
        if seat_data.holds[len(seat_data.holds) - 1] != pai:
            print('only deal last one when hued.')
            return

    # 从此人牌中扣除
    index = js_index_of(seat_data.holds, pai)
    if index == -1:
        # 原实现是字符串拼接；JS 里数组转字符串是逗号连接。
        print("holds:" + ",".join(js_str(x) for x in seat_data.holds))
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
        'game_chupai_notify_push', {"userId": seat_data.userId, "pai": pai}, seat_data.userId, True
    )

    # 如果出的牌可以胡，则算过胡
    # 原实现做了两次下标访问（第二次在 if 为真时必然存在）；取一次到局部变量，语义不变。
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
        # 未胡牌的才检查杠和碰
        if not ddd.hued:
            check_can_peng(game, ddd, pai)
            check_can_dian_gang(game, ddd, pai)

        check_can_hu(game, ddd, pai)
        if seat_data.lastFangGangSeat == -1:
            # ddd.canHu 为真说明 check_can_hu 刚在 tingMap 里命中了 pai。
            if ddd.canHu and ddd.guoHuFan >= 0 and ddd.tingMap[pai].fan <= ddd.guoHuFan:
                print("ddd.guoHuFan:" + js_str(ddd.guoHuFan))
                ddd.canHu = False
                await usermgr.send_msg(ddd.userId, 'guohu_push', None)

        if has_operations(ddd):
            await send_operations(game, ddd, game.chuPai)
            has_actions = True

    # 如果没有人有操作，则向下一家发牌，并通知他出牌
    if not has_actions:

        async def on_later() -> None:
            await usermgr.broacast_in_room(
                'guo_notify_push',
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
    # 原实现循环里又写了一次 `var i`（函数作用域，同一个变量），这里就是普通的重新赋值。
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
        print(seat_data.holds)
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
        'peng_notify_push', {"userid": seat_data.userId, "pai": pai}, seat_data.userId, True
    )

    # 碰的玩家打牌
    move_to_next_user(game, seat_data.seatIndex)

    # 广播通知玩家出牌方
    seat_data.canChuPai = True
    await usermgr.broacast_in_room(
        'game_chupai_push', seat_data.userId, seat_data.userId, True
    )


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
        check_can_hu(game, ddd, pai)
        if ddd.canHu:
            await send_operations(game, ddd, pai)
            has_actions = True
    if has_actions:
        # 原实现这段赋值语句结尾没有分号（ASI），语义就是在那个分支里赋值，照抄语义。
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
            print(seat_data.holds)
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
        'gang_notify_push',
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

    num_of_cnt = seat_data.countMap.get(pai)

    # 胡了的，只能直杠
    if num_of_cnt != 1 and seat_data.hued:
        print('you have already hued. no kidding plz.')
        return

    if js_index_of(seat_data.gangPai, pai) == -1:
        print("the given pai can't be ganged.")
        return

    # 如果有人可以胡牌，则需要等待
    # 原实现循环里又写了一次 `var i`（函数作用域，同一个变量），这里就是普通的重新赋值。
    i = game.turn
    while True:
        i = (i + 1) % 4
        if i == game.turn:
            break
        else:
            ddd = game.gameSeats[i]
            if ddd.canHu and i != seat_data.seatIndex:
                return

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

    await usermgr.broacast_in_room(
        'hangang_notify_push', seat_index, seat_data.userId, True
    )

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

    # 标记为和牌
    seat_data.hued = True
    hupai = game.chuPai
    is_zimo = False

    turn_seat = game.gameSeats[game.turn]

    hu_data: dict[str, Any] = {
        "ishupai": True,
        "pai": -1,
        "action": None,
        "isGangHu": False,
        "isQiangGangHu": False,
        "iszimo": False,
        "target": -1,
        "fan": 0,
        "pattern": None,
        "isHaiDiHu": False,
        "isTianHu": False,
        "isDiHu": False,
    }

    hu_data["numofgen"] = get_num_of_gen(seat_data)

    seat_data.huInfo.append(hu_data)

    hu_data["isGangHu"] = turn_seat.lastFangGangSeat >= 0
    notify = -1

    if game.qiangGangContext is not None:
        hupai = game.qiangGangContext.pai
        gang_seat = game.qiangGangContext.seatData
        notify = hupai
        hu_data["iszimo"] = False
        hu_data["action"] = "qiangganghu"
        hu_data["isQiangGangHu"] = True
        hu_data["target"] = gang_seat.seatIndex
        hu_data["pai"] = hupai

        record_game_action(game, seat_index, ACTION_HU, hupai)
        game.qiangGangContext.isValid = False

        idx = js_index_of(gang_seat.holds, hupai)
        if idx != -1:
            splice(gang_seat.holds, idx, 1)
            gang_seat.countMap[hupai] -= 1
            await usermgr.send_msg(gang_seat.userId, 'game_holds_push', gang_seat.holds)

        gang_seat.huInfo.append(
            {
                "action": "beiqianggang",
                "target": seat_data.seatIndex,
                "index": len(seat_data.huInfo) - 1,
            }
        )
    elif game.chuPai == -1:
        # 原实现直接把 pop() 的结果当数字用（此时手上必然有牌）。
        hupai = js_pop(seat_data.holds)
        seat_data.countMap[hupai] -= 1
        notify = hupai
        hu_data["pai"] = hupai
        if hu_data["isGangHu"]:
            if turn_seat.lastFangGangSeat == seat_index:
                hu_data["action"] = "ganghua"
                hu_data["iszimo"] = True
            else:
                diangganghua_zimo = game.conf.dianganghua == 1
                hu_data["action"] = "dianganghua"
                hu_data["iszimo"] = diangganghua_zimo
                hu_data["target"] = turn_seat.lastFangGangSeat
        else:
            hu_data["action"] = "zimo"
            hu_data["iszimo"] = True

        is_zimo = True
        record_game_action(game, seat_index, ACTION_ZIMO, hupai)
    else:
        notify = game.chuPai
        hu_data["pai"] = hupai

        at = "hu"
        # 炮胡
        if turn_seat.lastFangGangSeat >= 0:
            at = "gangpaohu"

        hu_data["action"] = at
        hu_data["iszimo"] = False
        hu_data["target"] = game.turn

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
        if at == "gangpaohu":
            at = "gangpao"
        else:
            at = "fangpao"
        fs.huInfo.append(
            {
                "action": at,
                "target": seat_data.seatIndex,
                "index": len(seat_data.huInfo) - 1,
            }
        )

        record_game_action(game, seat_index, ACTION_HU, hupai)

        game.fangpaoshumu += 1

        if game.fangpaoshumu > 1:
            game.yipaoduoxiang = seat_index

    if game.firstHupai < 0:
        game.firstHupai = seat_index

    # 保存番数
    # checkCanHu 刚命中过这张牌，tingMap 里一定有它。
    ti = seat_data.tingMap[hupai]
    hu_data["fan"] = ti.fan
    hu_data["pattern"] = ti.pattern
    hu_data["iszimo"] = is_zimo
    # 如果是最后一张牌，则认为是海底胡
    hu_data["isHaiDiHu"] = game.currentIndex == len(game.mahjongs)

    if game.conf.tiandihu:
        if game.chupaiCnt == 0 and game.button == seat_data.seatIndex and game.chuPai == -1:
            hu_data["isTianHu"] = True
        elif (
            game.chupaiCnt == 1
            and game.turn == game.button
            and game.button != seat_data.seatIndex
            and game.chuPai != -1
        ):
            hu_data["isDiHu"] = True

    clear_all_options(game, seat_data)

    # 通知前端，有人和牌了
    await usermgr.broacast_in_room(
        'hu_push',
        {"seatindex": seat_index, "iszimo": is_zimo, "hupai": notify},
        seat_data.userId,
        True,
    )

    #
    if game.lastHuPaiSeat == -1:
        game.lastHuPaiSeat = seat_index
    # else 分支里：原实现读的是 game.lastFangGangSeat——一个从未被写入的字段，运行结果是 NaN，
    # 于是 `cur > lp` 恒为 false，即该分支什么都不做。
    # GameState 上没有这个字段，这里不凭空造一个，直接如实写出"不赋值"。

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
    # 注意：clear_all_options 刚把 canHu 置成 false，所以这个分支在原实现里**不会执行**
    # （历史 bug，照原样保留）。
    if game.chuPai >= 0 and seat_data.canHu:
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
            'guo_notify_push', {"userId": uid, "pai": game.chuPai}, seat_data.userId, True
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
    """对应原实现末尾的 `setInterval(update, 1000)`：每 1000 毫秒跑一次 `_update()`。"""
    while True:
        await asyncio.sleep(1)
        await _update()


# 导出契约自检：本模块导出必须满足 roommgr 通过 GameManager 调用的全部函数。
# 原实现写成对象字面量只为让 TS 编译器检查签名；Python 没有编译期检查，
# 这里只把名字列一遍，运行时没有任何副作用。
_game_manager_contract = (
    set_ready,
    begin,
    huan_san_zhang,
    ding_que,
    chu_pai,
    peng,
    is_playing,
    gang,
    hu,
    guo,
    has_began,
    do_dissolve,
    dissolve_request,
    dissolve_agree,
)

# 定时器只在模块被 import 时起一次（这正是 roommgr.load_game_manager 必须懒加载的原因）。
try:
    asyncio.get_running_loop().create_task(_update_loop())
except RuntimeError:
    pass  # 没有事件循环时（同步 import）不起定时器
