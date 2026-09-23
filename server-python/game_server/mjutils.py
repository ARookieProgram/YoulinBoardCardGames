"""麻将听牌判定（纯逻辑，不碰 DB / socket）。

对应 `server/game_server/mjutils.ts`，逐函数照搬。

已知行为（保留，不要"顺手修"）：

* **没有实现七对**——七对是在 gamemgr 的 `checkCanTingPai` 里单独判的，
  这个通用拆牌函数只处理"3N + 将牌"；
* `check_can_hu` 无解时返回 `None` 而不是 `False`（原实现没有显式 `return false`），
  调用方只做真值判断，所以两种写法等价；
* `get_mj_type` 对范围外的牌返回 `None`（JS 的 `undefined`）。
"""

from __future__ import annotations

from shared.domain import CountMap, TingMap, TingPaiInfo
from utils.jscompat import js_keys


class TingPaiSeat:
    """`check_ting_pai` 需要的最小座位接口。

    只用鸭子类型：gamemgr 直接传 `GameSeat`，测试里传一个同形状的假对象即可。
    """

    holds: list[int]
    countMap: CountMap
    tingMap: TingMap


def check_ting_pai(seat_data: TingPaiSeat, begin: int, end: int) -> None:
    """逐个试牌，把能和的牌写进 `seat_data.tingMap`。

    :param seat_data: 手上牌的数据（会被就地修改：临时加牌判定后再撤销）。
    :param begin: 起始牌 id（含）。
    :param end: 结束牌 id（不含）。
    """
    for i in range(begin, end):
        # 如果这牌已经在和了，就不用检查了
        if seat_data.tingMap.get(i) is not None:
            continue
        # 将牌加入到计数中
        old = seat_data.countMap.get(i)
        if old is None:
            old = 0
            seat_data.countMap[i] = 1
        else:
            seat_data.countMap[i] += 1

        seat_data.holds.append(i)
        # 逐个判定手上的牌
        ret = check_can_hu(seat_data)
        if ret:
            # 平胡 0 番
            seat_data.tingMap[i] = TingPaiInfo(pattern="normal", fan=0)

        # 搞完以后，撤消刚刚加的牌
        seat_data.countMap[i] = old
        seat_data.holds.pop()


# 原实现的调试记录开关，永远是关的；保留下来是为了让 `debug_record` 的调用点一一对应。
kanzi: list[int] = []
record = False


def debug_record(pai: int) -> None:
    if record:
        kanzi.append(pai)


def match_single(seat_data: TingPaiSeat, selected: int) -> bool:
    """把 `selected` 这张牌拆成顺子，递归判定剩下的牌。"""
    # 分开匹配 A-2,A-1,A
    matched = True
    v = selected % 9
    if v < 2:
        matched = False
    else:
        for i in range(3):
            t = selected - 2 + i
            cc = seat_data.countMap.get(t)
            if cc is None or cc == 0:
                matched = False
                break

    # 匹配成功，扣除相应数值
    if matched:
        seat_data.countMap[selected - 2] -= 1
        seat_data.countMap[selected - 1] -= 1
        seat_data.countMap[selected] -= 1
        ret = check_single(seat_data)
        seat_data.countMap[selected - 2] += 1
        seat_data.countMap[selected - 1] += 1
        seat_data.countMap[selected] += 1
        if ret is True:
            debug_record(selected - 2)
            debug_record(selected - 1)
            debug_record(selected)
            return True

    # 分开匹配 A-1,A,A + 1
    matched = True
    if v < 1 or v > 7:
        matched = False
    else:
        for i in range(3):
            t = selected - 1 + i
            cc = seat_data.countMap.get(t)
            if cc is None or cc == 0:
                matched = False
                break

    if matched:
        seat_data.countMap[selected - 1] -= 1
        seat_data.countMap[selected] -= 1
        seat_data.countMap[selected + 1] -= 1
        ret = check_single(seat_data)
        seat_data.countMap[selected - 1] += 1
        seat_data.countMap[selected] += 1
        seat_data.countMap[selected + 1] += 1
        if ret is True:
            debug_record(selected - 1)
            debug_record(selected)
            debug_record(selected + 1)
            return True

    # 分开匹配 A,A+1,A + 2
    matched = True
    if v > 6:
        matched = False
    else:
        for i in range(3):
            t = selected + i
            cc = seat_data.countMap.get(t)
            if cc is None or cc == 0:
                matched = False
                break

    if matched:
        seat_data.countMap[selected] -= 1
        seat_data.countMap[selected + 1] -= 1
        seat_data.countMap[selected + 2] -= 1
        ret = check_single(seat_data)
        seat_data.countMap[selected] += 1
        seat_data.countMap[selected + 1] += 1
        seat_data.countMap[selected + 2] += 1
        if ret is True:
            debug_record(selected)
            debug_record(selected + 1)
            debug_record(selected + 2)
            return True
    return False


def check_single(seat_data: TingPaiSeat) -> bool:
    """取手上第一张还没被拆掉的牌，尝试按坎/顺子拆下去。"""
    holds = seat_data.holds
    selected = -1
    c = 0
    for i in range(len(holds)):
        pai = holds[i]
        c = seat_data.countMap.get(pai)
        if c != 0:
            selected = pai
            break
    # 如果没有找到剩余牌，则表示匹配成功了
    if selected == -1:
        return True
    # 否则，进行匹配
    if c == 3:
        # 直接作为一坎
        seat_data.countMap[selected] = 0
        debug_record(selected)
        debug_record(selected)
        debug_record(selected)
        ret = check_single(seat_data)
        # 立即恢复对数据的修改
        seat_data.countMap[selected] = c
        if ret is True:
            return True
    elif c == 4:
        # 直接作为一坎
        seat_data.countMap[selected] = 1
        debug_record(selected)
        debug_record(selected)
        debug_record(selected)
        ret = check_single(seat_data)
        # 立即恢复对数据的修改
        seat_data.countMap[selected] = c
        # 如果作为一坎能够把牌匹配完，直接返回TRUE。
        if ret is True:
            return True

    # 按单牌处理
    return match_single(seat_data, selected)


def check_can_hu(seat_data: TingPaiSeat) -> bool | None:
    """遍历每一种将牌，判断剩下的牌能否拆成 3N。

    注意：与原实现一样，**没有实现七对**；也因为没有显式 `return false`，
    无解时返回 `None`——调用方只做真值判断。

    `for...in` 的键顺序用 `js_keys` 保证与 JS 一致（整数键升序）。
    """
    for key in js_keys(seat_data.countMap):
        c = seat_data.countMap[key]
        if c < 2:
            continue
        # 如果当前牌大于等于２，则将它选为将牌
        seat_data.countMap[key] -= 2
        # 逐个判定剩下的牌是否满足　３Ｎ规则,一个牌会有以下几种情况
        # 1、0张，则不做任何处理
        # 2、2张，则只可能是与其它牌形成匹配关系
        # 3、3张，则可能是单张形成 A-2,A-1,A  A-1,A,A+1  A,A+1,A+2，也可能是直接成为一坎
        # 4、4张，则只可能是一坎+单张
        kanzi.clear()
        ret = check_single(seat_data)
        seat_data.countMap[key] += 2
        if ret:
            return True
    return None


def get_mj_type(pai: int) -> int | None:
    """牌 id 转花色：0 筒 / 1 条 / 2 万，范围外返回 `None`（与原实现一致）。"""
    if 0 <= pai < 9:
        # 筒
        return 0
    elif 9 <= pai < 18:
        # 条
        return 1
    elif 18 <= pai < 27:
        # 万
        return 2
    return None
