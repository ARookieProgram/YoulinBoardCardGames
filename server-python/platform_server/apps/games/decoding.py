"""对局流水（`t_games.action_records`）的解读。

**这是本模块唯一"懂玩法"的地方**，所以口径必须写清楚，改动前先读
`repo:docs/ai-native/game-rules.md` 与游戏服的两份实现
（`repo:server-python/game_server/gamemgr_xlch.py` / `gamemgr_xzdd.py`）。

牌 id（`pai`）
---------------

四川麻将只有三门 27 种牌，每种 4 张共 108 张。游戏服的 `shuffle()` 按
**筒 0~8 / 条 9~17 / 万 18~26** 依次填 `game.mahjongs`，客户端
`MahjongMgr.onLoad()` 用同一顺序建 `mahjongSprites`，所以：

===========  ==========  ================  ==================
id 区间       花色        第几张            客户端图集名
===========  ==========  ================  ==================
0 ~ 8        筒（dot）   1 ~ 9             ``dot_1``…``dot_9``
9 ~ 17       条（bamboo）1 ~ 9             ``bamboo_1``…``bamboo_9``
18 ~ 26      万（character）1 ~ 9          ``character_1``…``character_9``
===========  ==========  ================  ==================

后台把 `pai` 翻成中文（"5筒"）与图集名（`dot_5`）两种形态：
前者给人看，后者给"将来要画牌面"的界面用。

动作流水（`action_records`）
----------------------------

`gamemgr.do_game_over()` 把 `game.actionList` 紧凑 JSON 化后写进
`t_games.action_records`；`actionList` 是**扁平的整数数组**，每三个一组：

    [座位, 动作, 牌, 座位, 动作, 牌, ...]

动作编号与 `gamemgr` 顶部的常量逐字一致：

====  ============  ==========================================
编号  动作          说明
====  ============  ==========================================
``1`` ``ACTION_CHUPAI`` 出牌（`pai` 是打出的那张）
``2`` ``ACTION_MOPAI``  摸牌（`pai` 是摸到的那张）
``3`` ``ACTION_PENG``   碰（`pai` 是被碰的那张）
``4`` ``ACTION_GANG``   杠（明杠 / 暗杠 / 点杠都是它，`pai` 是杠的那张）
``5`` ``ACTION_HU``     胡别人的牌（点炮）
``6`` ``ACTION_ZIMO``   自摸
====  ============  ==========================================

客户端回放（`client/assets/scripts/ReplayMgr.ts`）用的就是这同一套三元组，
所以这里解出来的时间线与"玩家看到的回放"是同一个东西。

**只有开局快照、没有逐张手牌**：`action_records` 里不含每次动作后的手牌，
要还原每一手牌得从 `t_games.base_info.game_seats`（起手牌）+ 摸牌流水自己推。
后台不做这件事（那是回放器的活），只把"谁在第几步打了什么"如实列出。
"""

from __future__ import annotations

import json
from typing import Any, Final

# ---------------------------------------------------------------- 动作

#: 出牌。
ACTION_CHUPAI: Final[int] = 1
#: 摸牌。
ACTION_MOPAI: Final[int] = 2
#: 碰。
ACTION_PENG: Final[int] = 3
#: 杠（明杠 / 暗杠 / 点杠）。
ACTION_GANG: Final[int] = 4
#: 胡（点炮）。
ACTION_HU: Final[int] = 5
#: 自摸。
ACTION_ZIMO: Final[int] = 6

#: 动作编号 → 中文名。
ACTION_LABELS: Final[dict[int, str]] = {
    ACTION_CHUPAI: "出牌",
    ACTION_MOPAI: "摸牌",
    ACTION_PENG: "碰",
    ACTION_GANG: "杠",
    ACTION_HU: "胡",
    ACTION_ZIMO: "自摸",
}

#: 动作编号 → 短标签（时间线里一格一个，中文名太长）。
ACTION_SHORT_LABELS: Final[dict[int, str]] = {
    ACTION_CHUPAI: "打",
    ACTION_MOPAI: "摸",
    ACTION_PENG: "碰",
    ACTION_GANG: "杠",
    ACTION_HU: "胡",
    ACTION_ZIMO: "自摸",
}

#: 统计用的动作分类（`action_summary` 的键），与上面的编号一一对应。
ACTION_SUMMARY_KEYS: Final[tuple[str, ...]] = (
    "chupai",
    "mopai",
    "peng",
    "gang",
    "hu",
    "zimo",
)

#: 动作编号 → `action_summary` 的键。
ACTION_SUMMARY_KEY_BY_CODE: Final[dict[int, str]] = {
    ACTION_CHUPAI: "chupai",
    ACTION_MOPAI: "mopai",
    ACTION_PENG: "peng",
    ACTION_GANG: "gang",
    ACTION_HU: "hu",
    ACTION_ZIMO: "zimo",
}

#: 三元组里的第三个值缺失时用的占位（`record_game_action` 允许不传 `pai`）。
NO_TILE: Final[int] = -1

# ---------------------------------------------------------------- 牌

#: 牌 id 的取值范围：0 ~ 26（三门各 9 张）。
TILE_MIN: Final[int] = 0
TILE_MAX: Final[int] = 26

#: 每种牌 4 张，共 108 张。
TILES_PER_KIND: Final[int] = 4
WALL_SIZE: Final[int] = 27 * TILES_PER_KIND

#: 花色下标（`tile // 9`）→ 中文名与客户端图集前缀。
SUIT_LABELS: Final[tuple[str, ...]] = ("筒", "条", "万")
SUIT_SPRITE_PREFIXES: Final[tuple[str, ...]] = ("dot_", "bamboo_", "character_")

#: 点数 0~8 → 中文数字（牌面用中文更贴近玩家习惯）。
RANK_LABELS: Final[tuple[str, ...]] = ("一", "二", "三", "四", "五", "六", "七", "八", "九")


def is_valid_tile(tile: Any) -> bool:
    """牌 id 是否落在 0~26 之内。"""
    try:
        value = int(tile)
    except (TypeError, ValueError):
        return False
    return TILE_MIN <= value <= TILE_MAX


def tile_suit(tile: Any) -> int | None:
    """牌 id → 花色下标（0 筒 / 1 条 / 2 万）；越界返回 `None`。"""
    if not is_valid_tile(tile):
        return None
    return int(tile) // 9


def tile_label(tile: Any) -> str:
    """牌 id → 中文牌面（`5筒`、`一万`）；越界时如实写出来，不猜。"""
    suit = tile_suit(tile)
    if suit is None:
        return f"未知牌({tile})"
    rank = int(tile) % 9
    return f"{RANK_LABELS[rank]}{SUIT_LABELS[suit]}"


def tile_code(tile: Any) -> str:
    """牌 id → 客户端图集里的名字（`dot_5` / `bamboo_3` / `character_9`）。

    与 `client/assets/scripts/MahjongMgr.ts` 的 `mahjongSprites` 同序，
    将来后台要画牌面时直接用它取图集帧。
    """
    suit = tile_suit(tile)
    if suit is None:
        return ""
    return f"{SUIT_SPRITE_PREFIXES[suit]}{int(tile) % 9 + 1}"


def tile_payload(tile: Any) -> dict[str, Any]:
    """牌的出参形状（列表 / 时间线共用）。"""
    return {
        "tile": int(tile) if is_valid_tile(tile) else NO_TILE,
        "tile_label": tile_label(tile),
        "tile_code": tile_code(tile),
        "tile_suit": tile_suit(tile),
    }


# ---------------------------------------------------------------- 解析


def parse_action_records(raw: Any) -> tuple[list[int], list[str]]:
    """把 `action_records` 的 JSON 文本解析成扁平整数数组。

    :param raw: `t_games.action_records` 的内容（JSON 文本，也可能是已经是列表）。
    :return: `(整数数组, 警告列表)`；脏数据不抛异常，只记警告（后台不该因为
        一行历史数据整页打不开）。
    """
    warnings: list[str] = []
    values: list[Any]
    if isinstance(raw, list):
        values = raw
    elif raw is None or str(raw).strip() == "":
        return [], warnings
    else:
        try:
            values = json.loads(str(raw))
        except (TypeError, ValueError):
            return [], ["action_records 不是合法 JSON，已跳过"]
    if not isinstance(values, list):
        return [], ["action_records 不是数组，已跳过"]

    ints: list[int] = []
    for item in values:
        try:
            ints.append(int(item))
        except (TypeError, ValueError):
            ints.append(NO_TILE)
            warnings.append("action_records 里出现了非数字，已按未知处理")
    if len(ints) % 3 != 0:
        warnings.append(
            f"action_records 长度为 {len(ints)}，不是 3 的整数倍（每三个一组：座位/动作/牌）"
        )
    return ints, warnings


def decode_action_records(raw: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """把动作流水解成一条条可读的动作。

    :param raw: `t_games.action_records` 的内容。
    :return: `(动作列表, 警告列表)`；每个动作含
        `seq`（从 1 开始）/ `seat_index` / `action` / `action_label` /
        `tile` / `tile_label` / `tile_code`。
    """
    ints, warnings = parse_action_records(raw)
    actions: list[dict[str, Any]] = []
    for index in range(0, len(ints) - 2, 3):
        seat_index = ints[index]
        code = ints[index + 1]
        tile = ints[index + 2]
        actions.append(
            {
                "seq": index // 3 + 1,
                "seat_index": seat_index,
                "action": code,
                "action_label": ACTION_LABELS.get(code, f"未知动作({code})"),
                "action_short": ACTION_SHORT_LABELS.get(code, "?"),
                **tile_payload(tile),
            }
        )
    return actions, warnings


def empty_action_summary() -> dict[str, int]:
    """六个动作分类的计数器（初值全 0）。"""
    return {key: 0 for key in ACTION_SUMMARY_KEYS}


def summarize_actions(actions: list[dict[str, Any]]) -> dict[str, int]:
    """统计动作条数（按 `action_summary` 的六个分类）。"""
    summary = empty_action_summary()
    for action in actions:
        key = ACTION_SUMMARY_KEY_BY_CODE.get(int(action.get("action") or 0))
        if key is not None:
            summary[key] += 1
    return summary
