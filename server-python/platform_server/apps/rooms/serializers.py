"""房间管理的入参校验与出参形状。

**入参**用 DRF 序列化器校验（非法参数自然映射成 `ERR_BAD_REQUEST` = 10001）；
**出参**在这里拼成固定形状，视图只负责取数据与返回外壳。

出参分两类：

* **房间行**——`player_source` 的只读行（`room_payload`），列表与详情共用同一形状，
  详情额外多一个 `actions` 块（见下）；
* **预留的运维入口**——`dissolve` 恒返回 `reserved: true` 与"计划怎么实现"
  （`dissolve_action_payload`），前端据此展示"入口已预留"。

`actions.dissolve` 与 `POST /api/rooms/<id>/dissolve/` 是**同一件事的两种表达**
（前者让抽屉不必先点一次就知道能不能用），所以文案只在本模块定义一次。
"""

from __future__ import annotations

import re
from typing import Any, Final

from rest_framework import serializers

from apps.common.exceptions import PlatformError
from apps.common.pagination import PAGE_SIZE_MAX
from apps.players import player_source

# ---------------------------------------------------------------- 取值

#: 玩法过滤项：**白名单**（`conf.type` 本身没有白名单，客户端传什么落什么）。
#: 未知玩法会照常出现在列表里，只是不能用下拉筛选它。
ROOM_TYPE_FILTER_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    player_source.ROOM_TYPE_LABELS.items()
)

#: 房间号 / uuid 的合法形态：字母数字，最长 20（`t_rooms.uuid` 是 char(20)）。
#: 挡住明显是垃圾的路径参数，`_assert_read_only()` 与占位符已经保证了注入安全。
ROOM_REF_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Za-z]{1,20}$")

# ---------------------------------------------------------------- 预留入口文案

#: 预留功能的标识（前端按它区分入口）。
DISSOLVE_FEATURE: Final[str] = "dissolve"

DISSOLVE_SOURCE: Final[str] = (
    "计划实现：管理平台 → 游戏服的内部接口（共享密钥，按房间 uuid 通知 roommgr 销毁房间）。"
    "需要 Node 与 Python 两套游戏服同时新增接口与签名校验，属于跨进程改动，本期不做。"
)

DISSOLVE_MESSAGE: Final[str] = (
    "强制解散入口已预留：本期管理平台只做只读监控，解散需要游戏服先提供内部接口。"
)


# ---------------------------------------------------------------- 入参


class RoomListQuerySerializer(serializers.Serializer[Any]):
    """`GET /api/rooms/` 的查询参数。"""

    keyword = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        default="",
        help_text="房间号 / uuid / 座位上的玩家ID（纯数字），或座位玩家昵称",
    )
    room_type = serializers.ChoiceField(
        choices=ROOM_TYPE_FILTER_CHOICES,
        required=False,
        allow_blank=True,
        default="",
        help_text="玩法标识；不传或空串表示全部",
    )
    state = serializers.ChoiceField(
        choices=player_source.ROOM_STATE_CHOICES,
        required=False,
        default=player_source.ROOM_STATE_ALL,
        help_text="按座位占用过滤：未满座 / 已满座",
    )
    ordering = serializers.ChoiceField(
        choices=sorted(player_source.ROOM_ORDERING_CHOICES.keys()),
        required=False,
        default=player_source.ROOM_DEFAULT_ORDERING,
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PAGE_SIZE_MAX,
        default=20,
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


# ---------------------------------------------------------------- 出参


def _seat_payload(seat: dict[str, Any]) -> dict[str, Any]:
    """一个座位的出参。"""
    return {
        "seat_index": seat["seat_index"],
        "player_id": seat["player_id"],
        "name": seat["name"],
        "icon": seat["icon"],
        "score": seat["score"],
        "occupied": seat["player_id"] > 0,
    }


def _conf_payload(conf: dict[str, Any]) -> dict[str, Any]:
    """房间配置的出参（原始值，中文名由前端映射，见 `player_source._normalize_conf`）。"""
    return {
        "type": conf["type"],
        "base_score": conf["base_score"],
        "max_fan": conf["max_fan"],
        "max_games": conf["max_games"],
        "creator": conf["creator"],
        "zimo": conf["zimo"],
        "dianganghua": conf["dianganghua"],
        "jiangdui": conf["jiangdui"],
        "hsz": conf["hsz"],
        "menqing": conf["menqing"],
        "tiandihu": conf["tiandihu"],
    }


def room_payload(row: dict[str, Any]) -> dict[str, Any]:
    """列表与详情共用的房间出参。

    :param row: `player_source` 归一化后的房间行。
    """
    room_type = row["type"]
    return {
        "room_id": row["room_id"],
        "uuid": row["uuid"],
        "type": room_type,
        # 玩法名与大厅里玩家看到的一致；未知玩法按原样回，前端不至于显示空白。
        "type_label": player_source.ROOM_TYPE_LABELS.get(room_type, room_type),
        "state": row["state"],
        "seat_count": row["seat_count"],
        "occupied_seats": row["occupied_seats"],
        "create_time": row["create_time"],
        "created_at": row["created_at"],
        "num_of_turns": row["num_of_turns"],
        "next_button": row["next_button"],
        "ip": row["ip"],
        "port": row["port"],
        "conf": _conf_payload(row["conf"]),
        "seats": [_seat_payload(seat) for seat in row["seats"]],
    }


def dissolve_action_payload() -> dict[str, Any]:
    """强制解散这个**预留**入口的说明块。"""
    return {
        "reserved": True,
        "available": False,
        "feature": DISSOLVE_FEATURE,
        "source": DISSOLVE_SOURCE,
        "message": DISSOLVE_MESSAGE,
    }


def reserved_dissolve_payload(*, room_id: str, uuid: str) -> dict[str, Any]:
    """`POST /api/rooms/<id>/dissolve/` 的返回：契约已定、动作未接入。

    :param room_id: 房间号（`t_rooms.id`）。
    :param uuid: 房间 uuid（`t_rooms.uuid`）——将来游戏服的接口认的就是它。
    """
    payload = dissolve_action_payload()
    payload["room_id"] = room_id
    payload["uuid"] = uuid
    return payload


def room_detail_payload(row: dict[str, Any]) -> dict[str, Any]:
    """详情：房间字段 + 预留运维入口的可用性说明。"""
    payload = room_payload(row)
    payload["actions"] = {DISSOLVE_FEATURE: dissolve_action_payload()}
    return payload
