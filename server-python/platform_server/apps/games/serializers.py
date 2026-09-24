"""对局记录的入参校验与出参形状。

**入参**用 DRF 序列化器校验（非法参数自然映射成 `ERR_BAD_REQUEST` = 10001）；
**出参**在这里拼成固定形状，视图只负责取数据与返回外壳。

出参分四类：

* **对局行**（`game_row_payload`）——列表与详情共用，详情在此之上多出动作流水（见下）；
* **单局详情**（`game_detail_payload`）——多出 `timeline`（全局动作时间线）、
  `seat_actions`（**每个玩家自己的出牌记录**）、`initial_hands`（开局四家手牌）、
  `wall`（牌墙消耗）；
* **房间对局**（`room_games_payload`）——房间信息 + 四个座位 + 该房间的全部对局；
* **玩家对局**（`player_game_payload`）——来自 `t_users.history` 的房间级战绩
  （每人只保留最近 10 场，见 `player_source.HISTORY_MAX_ENTRIES`）。

牌与动作的中文名由 `apps/games/decoding.py` 负责；这里只做"拼形状"，
不重复定义玩法口径。
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from django.conf import settings
from rest_framework import serializers

from apps.common.exceptions import PlatformError
from apps.common.pagination import PAGE_SIZE_MAX
from apps.players import player_source

from . import decoding

# ---------------------------------------------------------------- 取值

#: 玩法过滤项：**白名单**（`conf.type` 本身没有白名单，客户端传什么落什么）。
GAME_TYPE_FILTER_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    player_source.ROOM_TYPE_LABELS.items()
)

#: 房间号 / uuid 的合法形态：字母数字，最长 20（`t_rooms.uuid` 是 char(20)）。
#: 与房间管理同一口径；这里另写一份是为了让 `games` 不反向依赖 `rooms` 应用。
ROOM_REF_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Za-z]{1,20}$")

#: `create_time` 是 Unix 秒，按 `settings.TIME_ZONE` 切天。
_SITE_TIMEZONE: Final[ZoneInfo] = ZoneInfo(settings.TIME_ZONE)

#: 动作时间线里"可能拿走别人打出的牌"的动作（碰 / 杠 / 胡）。
_TAKE_ACTIONS: Final[tuple[int, ...]] = (
    decoding.ACTION_PENG,
    decoding.ACTION_GANG,
    decoding.ACTION_HU,
)

#: 一次出牌之后最多往后看几步来判断"这张牌被谁拿走"（碰 / 杠 / 胡 最多三家各一步）。
_TAKE_LOOKAHEAD: Final[int] = 3

#: 拖尾动作（胡 / 自摸）的动作编号。
_WIN_ACTIONS: Final[tuple[int, ...]] = (decoding.ACTION_HU, decoding.ACTION_ZIMO)

#: `base_info.game_seats` 期望的座位数（与 `t_rooms` 一致）。
_SEAT_COUNT: Final[int] = player_source.ROOM_SEAT_COUNT


# ---------------------------------------------------------------- 入参


class GameListQuerySerializer(serializers.Serializer[Any]):
    """`GET /api/games/` 的查询参数。"""

    keyword = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        default="",
        help_text="房间 uuid / 房间号 / 玩家ID / 玩家昵称",
    )
    game_type = serializers.ChoiceField(
        choices=GAME_TYPE_FILTER_CHOICES,
        required=False,
        allow_blank=True,
        default="",
        help_text="玩法标识；不传或空串表示全部",
    )
    source = serializers.ChoiceField(
        choices=player_source.GAME_SOURCE_CHOICES,
        required=False,
        default=player_source.GAME_SOURCE_ALL,
        help_text="进行中（t_games）/ 已结束（t_games_archive）/ 全部",
    )
    date_from = serializers.DateField(
        required=False, allow_null=True, default=None, help_text="按本局开始日期过滤（含）"
    )
    date_to = serializers.DateField(
        required=False, allow_null=True, default=None, help_text="按本局开始日期过滤（含）"
    )
    ordering = serializers.ChoiceField(
        choices=sorted(player_source.GAME_ORDERING_CHOICES.keys()),
        required=False,
        default=player_source.GAME_DEFAULT_ORDERING,
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PAGE_SIZE_MAX,
        default=20,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """起止日期不能反着填。"""
        start = attrs.get("date_from")
        end = attrs.get("date_to")
        if start and end and start > end:
            raise serializers.ValidationError({"date_from": "起始日期不能晚于结束日期"})
        return attrs


class PlayerGameListQuerySerializer(serializers.Serializer[Any]):
    """`GET /api/games/players/<id>/` 的查询参数。

    数据来自 `t_users.history`，一人最多 10 场，所以只有分页参数。
    """

    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PAGE_SIZE_MAX,
        default=player_source.HISTORY_MAX_ENTRIES,
    )


def validate_room_ref(room_ref: str) -> str:
    """校验路径里的房间号 / uuid。

    :param room_ref: URL 里的房间标识。
    :return: 去掉首尾空白后的标识。
    :raises PlatformError: 形态不合法（映射成 10001）。
    """
    text = (room_ref or "").strip()
    if not ROOM_REF_PATTERN.fullmatch(text):
        raise PlatformError("房间号不合法（只能是 1~20 位字母或数字）")
    return text


def day_bounds(value: Any) -> int | None:
    """把"某一天"换成这一天的起始 Unix 秒（按站点时区）。

    :param value: `datetime.date`（DRF `DateField` 的产物）；`None` 原样返回。
    """
    if value is None:
        return None
    moment = datetime.combine(value, time.min, tzinfo=_SITE_TIMEZONE)
    return int(moment.timestamp())


def day_end_seconds(value: Any) -> int | None:
    """把"某一天"换成这一天的**最后一秒**（`create_time` 用 `<=` 过滤，所以是闭区间）。

    用"次日零点减一秒"而不是 `起点 + 86399`，这样将来换到有夏令时的时区也不会错一小时。
    """
    if value is None:
        return None
    next_day = datetime.combine(value, time.min, tzinfo=_SITE_TIMEZONE) + timedelta(days=1)
    return int(next_day.timestamp()) - 1


# ---------------------------------------------------------------- 座位


def _seat_display_name(seat: dict[str, Any]) -> str:
    """座位的展示名：昵称 → `玩家#ID` → `座位N`。"""
    name = str(seat.get("name") or "").strip()
    if name:
        return name
    if int(seat.get("player_id") or 0) > 0:
        return f"玩家#{seat['player_id']}"
    return f"座位{seat['seat_index']}"


def seat_payload(seat: dict[str, Any]) -> dict[str, Any]:
    """把 `player_source` 的座位行拼成出参（不含本局得分，由调用方补）。"""
    return {
        "seat_index": int(seat.get("seat_index") or 0),
        "player_id": int(seat.get("player_id") or 0),
        "name": str(seat.get("name") or ""),
        "display_name": _seat_display_name(seat),
        "icon": str(seat.get("icon") or ""),
        "occupied": int(seat.get("player_id") or 0) > 0,
        "is_banker": False,
    }


def _seat_rows(seats: Any) -> list[dict[str, Any]]:
    """取一组座位行（缺项补"未知座位"）。"""
    if not isinstance(seats, list) or len(seats) < _SEAT_COUNT:
        return [
            {"seat_index": index, "player_id": 0, "name": "", "icon": "", "score": 0}
            for index in range(_SEAT_COUNT)
        ]
    return seats


def _identity_seats(identity: dict[str, Any] | None) -> list[dict[str, Any]]:
    """取身份解析结果里的四个座位。"""
    return _seat_rows((identity or {}).get("seats"))


def _identity_known(identity: dict[str, Any] | None) -> bool:
    """身份是不是真的查到了（`unknown` 表示只有座位号，没有玩家）。"""
    source = str((identity or {}).get("identity_source") or "")
    return source != player_source.GAME_IDENTITY_UNKNOWN


# ---------------------------------------------------------------- 对局行


def game_seats(row: dict[str, Any], identity: dict[str, Any] | None) -> list[dict[str, Any]]:
    """四个座位 + 本局得分 / 房间累计得分。

    * `score`  —— **本局**得分，来自 `t_games.result`（权威，一定存在）；
    * `room_score` —— **房间累计**得分，来自 `t_rooms.user_scoreN` 或历史战绩；
      身份查不到时是 `None`（不是 0——0 会被误读成"打平"）。
    """
    known = _identity_known(identity)
    button = int(row.get("button") or 0)
    result = list(row.get("result") or [])
    seats: list[dict[str, Any]] = []
    for index, seat in enumerate(_identity_seats(identity)):
        item = seat_payload(seat)
        item["is_banker"] = index == button
        item["score"] = int(result[index]) if index < len(result) else 0
        item["room_score"] = int(seat.get("score") or 0) if known else None
        seats.append(item)
    return seats


def _type_label(game_type: str) -> str:
    """玩法标识 → 大厅里的名字；未知玩法按原样回，前端不至于显示空白。"""
    return player_source.ROOM_TYPE_LABELS.get(game_type, game_type)


def game_row_payload(
    row: dict[str, Any],
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    """列表与详情共用的对局行。

    :param row: `player_source` 归一化后的对局行。
    :param identity: `resolve_room_identities()` 的结果（`None` 表示只有座位号）。
    """
    room_uuid = str(row.get("room_uuid") or "")
    game_type = str(row.get("type") or "") or str((identity or {}).get("room_type") or "")
    actions, _ = decoding.decode_action_records(row.get("action_records"))
    summary = decoding.summarize_actions(actions)
    game_index = int(row.get("game_index") or 0)
    source = str(row.get("source") or player_source.GAME_SOURCE_ARCHIVE)
    identity_source = str((identity or {}).get("identity_source") or player_source.GAME_IDENTITY_UNKNOWN)
    return {
        "room_uuid": room_uuid,
        "room_id": str((identity or {}).get("room_id") or ""),
        "game_index": game_index,
        # 对局里给运营看的是"第几局"，游戏服的 `game_index` 从 0 开始，这里 +1。
        "round": game_index + 1,
        "source": source,
        "source_label": player_source.GAME_SOURCE_LABELS.get(source, source),
        "type": game_type,
        "type_label": _type_label(game_type),
        "button": int(row.get("button") or 0),
        "create_time": int(row.get("create_time") or 0),
        "created_at": str(row.get("created_at") or ""),
        "result": list(row.get("result") or []),
        "seats": game_seats(row, identity),
        "seat_count": _SEAT_COUNT,
        "identity_source": identity_source,
        "identity_note": player_source.GAME_IDENTITY_LABELS.get(identity_source, ""),
        "live": bool((identity or {}).get("live")),
        "has_action_records": bool(actions),
        "action_count": len(actions),
        "action_summary": summary,
        # 详情入口：前端据此决定"查看出牌记录"按钮是否可点。
        "detail_available": bool(row.get("base_info")) or bool(actions),
    }


# ---------------------------------------------------------------- 单局详情


def _initial_hands(row: dict[str, Any], seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """开局四家手牌（来自 `t_games.base_info.game_seats`）。"""
    raw = row.get("base_info") or {}
    hands_raw = raw.get("game_seats")
    hands: list[dict[str, Any]] = []
    for index, seat in enumerate(seats):
        tiles_raw = hands_raw[index] if isinstance(hands_raw, list) and index < len(hands_raw) else []
        tiles = tiles_raw if isinstance(tiles_raw, list) else []
        payload = [decoding.tile_payload(tile) for tile in tiles]
        hands.append(
            {
                "seat_index": seat["seat_index"],
                "player_id": seat["player_id"],
                "name": seat["display_name"],
                "tiles": payload,
                "tile_count": len(payload),
                "tiles_text": " ".join(item["tile_label"] for item in payload),
            }
        )
    return hands


def _mark_discard_taken(timeline: list[dict[str, Any]]) -> None:
    """给每一张打出的牌标注"被谁拿走"（碰 / 杠 / 胡），就地修改 `timeline`。"""
    for index, item in enumerate(timeline):
        if item["action"] != decoding.ACTION_CHUPAI:
            continue
        for follower in timeline[index + 1 : index + 1 + _TAKE_LOOKAHEAD]:
            if follower["action"] not in _TAKE_ACTIONS:
                break
            if follower["tile"] == item["tile"]:
                item["taken_by"] = {
                    "seat_index": follower["seat_index"],
                    "name": follower["seat_name"],
                    "action": follower["action"],
                    "action_label": follower["action_label"],
                }
                break


def _seat_action_view(
    seat: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    """单个玩家的动作视图：**他这一局打出的每一张牌**与全部动作。"""
    mine = [item for item in timeline if item["seat_index"] == seat["seat_index"]]
    folds = [item for item in mine if item["action"] == decoding.ACTION_CHUPAI]
    drawn = [item for item in mine if item["action"] == decoding.ACTION_MOPAI]
    pengs = [item for item in mine if item["action"] == decoding.ACTION_PENG]
    gangs = [item for item in mine if item["action"] == decoding.ACTION_GANG]
    wins = [item for item in mine if item["action"] in _WIN_ACTIONS]
    return {
        **seat,
        "actions": mine,
        "action_count": len(mine),
        "summary": decoding.summarize_actions(mine),
        "folds": folds,
        "folds_text": " ".join(item["tile_label"] for item in folds),
        "drawn": drawn,
        "drawn_text": " ".join(item["tile_label"] for item in drawn),
        "pengs": pengs,
        "pengs_text": " ".join(item["tile_label"] for item in pengs),
        "gangs": gangs,
        "gangs_text": " ".join(item["tile_label"] for item in gangs),
        "hued": bool(wins),
        "zimo": any(item["action"] == decoding.ACTION_ZIMO for item in wins),
        "win_tiles": wins,
        "win_text": " ".join(item["tile_label"] for item in wins),
    }


def _wall_payload(row: dict[str, Any], hands: list[dict[str, Any]], drawn: int) -> dict[str, Any]:
    """牌墙消耗：洗好的张数、发出的张数、摸走的张数、还剩多少。"""
    raw = row.get("base_info") or {}
    wall_raw = raw.get("mahjongs")
    wall_tiles = wall_raw if isinstance(wall_raw, list) else []
    dealt = sum(int(hand["tile_count"]) for hand in hands)
    size = len(wall_tiles) or decoding.WALL_SIZE
    return {
        "size": size,
        "dealt": dealt,
        "drawn": drawn,
        "remaining": max(size - dealt - drawn, 0),
        "tiles": [int(tile) for tile in wall_tiles],
    }


def game_detail_payload(
    row: dict[str, Any],
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    """单局详情：对局行 + 出牌记录（全局时间线 + 每个玩家自己的动作）。"""
    payload = game_row_payload(row, identity)
    seats = [dict(seat) for seat in payload["seats"]]
    seats_by_index = {seat["seat_index"]: seat for seat in seats}
    actions, warnings = decoding.decode_action_records(row.get("action_records"))

    timeline: list[dict[str, Any]] = []
    for action in actions:
        seat = seats_by_index.get(action["seat_index"])
        timeline.append(
            {
                **action,
                "seat_label": f"座位{action['seat_index']}",
                "player_id": seat["player_id"] if seat else 0,
                "seat_name": seat["display_name"] if seat else f"座位{action['seat_index']}",
                "is_banker": bool(seat["is_banker"]) if seat else False,
            }
        )
    _mark_discard_taken(timeline)

    hands = _initial_hands(row, seats)
    summary = payload["action_summary"]
    payload.update(
        {
            "warnings": warnings,
            "timeline": timeline,
            "seat_actions": [_seat_action_view(seat, timeline) for seat in seats],
            "initial_hands": hands,
            "initial_hands_text": [hand["tiles_text"] for hand in hands],
            "wall": _wall_payload(row, hands, summary["mopai"]),
        }
    )
    return payload


# ---------------------------------------------------------------- 房间对局


def room_games_payload(
    *,
    room_uuid: str,
    identity: dict[str, Any] | None,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """一个房间的对局列表（含房间信息与四个座位）。

    :param rows: `player_source.get_room_games()` 的结果（按局号升序）。
    """
    game_type = str((identity or {}).get("room_type") or "")
    if not game_type and rows:
        game_type = str(rows[0].get("type") or "")
    identity_source = str((identity or {}).get("identity_source") or player_source.GAME_IDENTITY_UNKNOWN)
    seats = []
    for seat in _identity_seats(identity):
        item = seat_payload(seat)
        item["room_score"] = int(seat.get("score") or 0) if _identity_known(identity) else None
        seats.append(item)
    # 庄家每局都可能变，所以"谁是庄"放在每一局里（`games[].seats[].is_banker`），
    # 房间级的座位只给累计得分。
    return {
        "room_uuid": room_uuid,
        "room_id": str((identity or {}).get("room_id") or ""),
        "type": game_type,
        "type_label": _type_label(game_type),
        "live": bool((identity or {}).get("live")),
        "identity_source": identity_source,
        "identity_note": player_source.GAME_IDENTITY_LABELS.get(identity_source, ""),
        "seats": seats,
        "game_count": len(rows),
        "games": [game_row_payload(row, identity) for row in rows],
    }


# ---------------------------------------------------------------- 玩家对局


def player_game_payload(
    entry: dict[str, Any],
    *,
    player_id: int,
    game_count: int = 0,
) -> dict[str, Any]:
    """一条玩家房间战绩（来自 `t_users.history`）。

    :param entry: `player_source.parse_player_history()` 的条目。
    :param player_id: 当前看的是谁（用来标出"我"与算名次）。
    :param game_count: 该房间在 `t_games` / `t_games_archive` 里的局数。
    """
    seats: list[dict[str, Any]] = []
    my_seat: int | None = None
    for seat in _seat_rows(entry.get("seats")):
        item = seat_payload(seat)
        item["score"] = int(seat.get("score") or 0)
        item["is_me"] = item["player_id"] == int(player_id)
        item["is_banker"] = False
        if item["is_me"]:
            my_seat = item["seat_index"]
        seats.append(item)

    scores = [seat["score"] for seat in seats]
    my_score = scores[my_seat] if my_seat is not None and my_seat < len(scores) else 0
    # 名次按房间累计得分排（并列同名次）。
    rank = sorted(scores, reverse=True).index(my_score) + 1 if my_seat is not None else None
    return {
        "room_uuid": str(entry.get("uuid") or ""),
        "room_id": str(entry.get("room_id") or ""),
        "create_time": int(entry.get("create_time") or 0),
        "created_at": player_source.format_unix_seconds(entry.get("create_time")),
        "seats": seats,
        "seat_count": _SEAT_COUNT,
        "my_seat": my_seat,
        "my_score": my_score,
        "my_rank": rank,
        "game_count": int(game_count),
        "games_available": int(game_count) > 0,
    }
