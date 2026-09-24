"""玩家管理的入参校验与出参形状。

**入参**用 DRF 序列化器校验（非法参数自然映射成 `ERR_BAD_REQUEST` = 10001）；
**出参**在这里拼成固定形状，视图只负责取数据与返回外壳。

两类出参：

* **玩家行**——`player_source` 的只读行 + `PlayerBan` 的最新状态（`player_summary`）；
* **预留端点**——对局记录 / 充值记录的接口契约已经定好，但数据源还没接
  （`reserved_payload`），前端据此展示"入口已预留"，接上真数据时
  **不需要改前端契约**。
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.common.pagination import PAGE_SIZE_MAX, page_payload

from .models import PlayerBan
from .player_source import DEFAULT_ORDERING, ORDERING_CHOICES

# ---------------------------------------------------------------- 状态取值

#: 列表页的封禁状态过滤。
BAN_STATE_ALL = "all"
BAN_STATE_BANNED = "banned"
BAN_STATE_NORMAL = "normal"
BAN_STATE_CHOICES: tuple[tuple[str, str], ...] = (
    (BAN_STATE_ALL, "全部"),
    (BAN_STATE_BANNED, "封禁中"),
    (BAN_STATE_NORMAL, "正常"),
)

#: 封禁时长上限（小时）：一年。再长请用"永久"。
MAX_BAN_HOURS = 24 * 365


# ---------------------------------------------------------------- 入参


class PlayerListQuerySerializer(serializers.Serializer[Any]):
    """`GET /api/players/` 的查询参数。"""

    keyword = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        default="",
        help_text="账号 / 昵称 / 玩家ID（纯数字时按 ID 精确匹配）",
    )
    ban_state = serializers.ChoiceField(
        choices=BAN_STATE_CHOICES,
        required=False,
        default=BAN_STATE_ALL,
    )
    ordering = serializers.ChoiceField(
        choices=sorted(ORDERING_CHOICES.keys()),
        required=False,
        default=DEFAULT_ORDERING,
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PAGE_SIZE_MAX,
        default=20,
    )


class PlayerBanInputSerializer(serializers.Serializer[Any]):
    """`POST /api/players/<id>/ban/` 的入参。"""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        default="",
        help_text="封禁原因，会写进流水",
    )
    duration_hours = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=MAX_BAN_HOURS,
        default=None,
        help_text="封禁时长（小时）；不传或 null 表示永久封禁",
    )


class PlayerUnbanInputSerializer(serializers.Serializer[Any]):
    """`POST /api/players/<id>/unban/` 的入参。"""

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        default="",
        help_text="解封原因（可选）",
    )


class ReservedPageQuerySerializer(serializers.Serializer[Any]):
    """预留分页端点（对局记录 / 充值记录）的查询参数。

    现在返回空列表，但**分页参数此刻就校验**：等数据源接上，
    前端已经在用同一套参数，不需要改一行。
    """

    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PAGE_SIZE_MAX,
        default=20,
    )


# ---------------------------------------------------------------- 出参


def ban_state_payload(record: PlayerBan | None) -> dict[str, Any] | None:
    """流水 → 出参；没有记录时返回 `None`。"""
    return record.as_payload() if record is not None else None


def player_summary(row: dict[str, Any], record: PlayerBan | None) -> dict[str, Any]:
    """列表页的一行：玩家只读字段 + 当前封禁状态。

    :param row: `player_source` 归一化后的玩家行。
    :param record: 该玩家最新一条封禁流水（可能为 `None`）。
    """
    return {
        "player_id": row["player_id"],
        "account": row["account"],
        "name": row["name"],
        "headimg": row["headimg"],
        "lv": row["lv"],
        "exp": row["exp"],
        "coins": row["coins"],
        # 房卡：游戏里扣的就是这个字段（`t_users.gems`），后台把它单独摆出来。
        "gems": row["gems"],
        "roomid": row["roomid"],
        "banned": record is not None and record.is_effective,
        "ban": ban_state_payload(record),
    }


def player_detail(row: dict[str, Any], history: list[PlayerBan]) -> dict[str, Any]:
    """详情：玩家字段 + 当前状态 + 封禁流水。"""
    latest = history[0] if history else None
    payload = player_summary(row, latest)
    payload["sex"] = row["sex"]
    payload["ban_records"] = [record.as_payload() for record in history]
    return payload


def reserved_payload(
    *,
    player_id: int,
    feature: str,
    source: str,
    message: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """预留端点的统一出参。

    形状与真实列表接口**完全一致**（`items` / `total` / `page` / `page_size` / `pages`），
    额外多一个 `reserved: true` 与数据来源说明。接上真实数据源时把 `items` 填上、
    去掉 `reserved` 即可，前端只认同一套键。
    """
    payload = page_payload(items=[], total=0, page=page, page_size=page_size)
    payload.update(
        {
            "reserved": True,
            "player_id": player_id,
            "feature": feature,
            "source": source,
            "message": message,
        }
    )
    return payload
