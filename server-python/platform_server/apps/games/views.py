"""对局记录接口。

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/games/` | 登录即可 | 对局列表：关键字 / 玩法 / 来源 / 日期 / 排序 / 分页 |
| GET | `/api/games/overview/` | 登录即可 | 概览：总局数、已结束、进行中、最近 24 小时 |
| GET | `/api/games/rooms/<房间号或uuid>/` | 登录即可 | 一个房间的全部对局 + 四个座位 |
| GET | `/api/games/rooms/<房间号或uuid>/<局号>/` | 登录即可 | **单局详情：四家出牌记录**（时间线 + 每人自己的动作） |
| GET | `/api/games/players/<玩家ID>/` | 登录即可 | 某个玩家的房间战绩（来自 `t_users.history`，最多最近 10 场） |

数据来源：**玩家库 `db_scmj` 的 `t_games` / `t_games_archive`**，与玩家管理、房间管理
走**同一条只读通道**（`apps/players/player_source.py`，只执行 SELECT）。
本应用没有模型，也不往玩家库写任何一行。

三条只有读过这两张表的人才知道的坑（README §6.7 有完整说明）：

1. **每结束一局才写一行**：房间刚建好、第一局还在打时，`/api/games/` 里查不到它，
   这是正常的，`14001` 的文案里写了这一点；
2. **表里只有座位号、没有玩家**：玩家身份优先取存活房间的 `t_rooms`，房间已销毁时
   从 `t_users.history`（每人最近 10 场）反查；两边都没有时座位显示成 `座位N`
   （`identity_source = unknown`），接口不会因此报错；
3. **房间号不在对局表里**：所以"按房间号查"必须先解析成 uuid，解析在
   `player_source.resolve_room_ref()` 里，`games` 应用不做 SQL。

权限口径与玩家 / 房间管理一致：**看数据是运营的日常**，所以这五个接口都只要求登录；
对局记录全是只读的历史数据，本模块没有任何写入口。
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common import response as envelope
from apps.common.pagination import page_payload
from apps.players import player_source
from apps.players.exceptions import PlayerNotFound

from .exceptions import GameNotFound
from .serializers import (
    GameListQuerySerializer,
    PlayerGameListQuerySerializer,
    day_bounds,
    day_end_seconds,
    game_detail_payload,
    game_row_payload,
    player_game_payload,
    room_games_payload,
    validate_room_ref,
)


def _identities(uuids: list[str]) -> dict[str, dict[str, Any]]:
    """批量解析房间身份（一次查询覆盖整页，见 `player_source.resolve_room_identities`）。"""
    return player_source.resolve_room_identities(uuids)


def _locate_room(room_ref: str) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """把房间号 / uuid 定位成 `(uuid, 该房间的对局行, 房间身份)`。

    候选 uuid 由 `player_source.resolve_room_ref()` 给出（存活房间优先，
    其次是历史战绩里最新的一条，最后才把入参本身当 uuid 试），这里逐个试到有对局为止。
    """
    candidates = player_source.resolve_room_ref(room_ref)
    identities = _identities(candidates)
    for uuid in candidates:
        rows = player_source.get_room_games(uuid)
        if rows:
            return uuid, rows, identities.get(uuid)
    raise GameNotFound(room_ref)


class GameListView(APIView):
    """`GET /api/games/` —— 对局记录列表。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """按关键字 / 玩法 / 来源 / 日期分页查询对局。"""
        query = GameListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params: dict[str, Any] = dict(query.validated_data)

        rows, total = player_source.search_games(
            keyword=params["keyword"],
            game_type=params["game_type"],
            source=params["source"],
            created_from=day_bounds(params["date_from"]),
            created_to=day_end_seconds(params["date_to"]),
            ordering=params["ordering"],
            page=params["page"],
            page_size=params["page_size"],
        )
        identities = _identities([row["room_uuid"] for row in rows])
        return envelope.ok(
            page_payload(
                items=[
                    game_row_payload(row, identities.get(row["room_uuid"])) for row in rows
                ],
                total=total,
                page=params["page"],
                page_size=params["page_size"],
            )
        )


class GameOverviewView(APIView):
    """`GET /api/games/overview/` —— 列表页顶部的概览数字。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """返回总局数、已结束 / 进行中局数与最近 24 小时的对局 / 房间数。"""
        return envelope.ok(player_source.game_overview())


class RoomGameListView(APIView):
    """`GET /api/games/rooms/<房间号或uuid>/` —— 一个房间的全部对局。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, room_ref: str) -> Response:
        """房间信息 + 四个座位 + 逐局要点（不出牌流水，明细走单局详情接口）。"""
        ref = validate_room_ref(room_ref)
        room_uuid, rows, identity = _locate_room(ref)
        return envelope.ok(room_games_payload(room_uuid=room_uuid, identity=identity, rows=rows))


class GameDetailView(APIView):
    """`GET /api/games/rooms/<房间号或uuid>/<局号>/` —— 单局详情（出牌记录）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, room_ref: str, game_index: int) -> Response:
        """**这一局每个玩家打了什么**：全局时间线 + 每人自己的动作与出牌顺序。"""
        ref = validate_room_ref(room_ref)
        candidates = player_source.resolve_room_ref(ref)
        row: dict[str, Any] | None = None
        room_uuid = ""
        for uuid in candidates:
            found = player_source.get_game(uuid, game_index)
            if found is not None:
                row, room_uuid = found, uuid
                break
        if row is None:
            raise GameNotFound(ref, game_index)
        identity = _identities([room_uuid]).get(room_uuid)
        return envelope.ok(game_detail_payload(row, identity))


class PlayerGameListView(APIView):
    """`GET /api/games/players/<玩家ID>/` —— 某个玩家的房间战绩。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, player_id: int) -> Response:
        """从 `t_users.history` 读该玩家的战绩，并补上每个房间的局数。

        刻意**不查 `t_games` 的逐局明细**：玩家侧的战绩快照是"房间级"的
        （`history` 里只有 uuid / 房间号 / 四家总分），逐局明细要点进房间再看，
        这样一次请求最多只扫一遍 `t_users.history`。
        """
        query = PlayerGameListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params: dict[str, Any] = dict(query.validated_data)

        entries = player_source.player_history_entries(player_id)
        if entries is None:
            raise PlayerNotFound(player_id)

        counts = player_source.count_games_by_room([entry["uuid"] for entry in entries])
        total = len(entries)
        page_size = int(params["page_size"])
        offset = max(int(params["page"]) - 1, 0) * page_size
        page_entries = entries[offset : offset + page_size]
        items = [
            player_game_payload(
                entry,
                player_id=player_id,
                game_count=counts.get(entry["uuid"], 0),
            )
            for entry in page_entries
        ]
        payload = page_payload(
            items=items,
            total=total,
            page=int(params["page"]),
            page_size=page_size,
        )
        payload["player_id"] = player_id
        payload["max_entries"] = player_source.HISTORY_MAX_ENTRIES
        payload["note"] = (
            "玩家侧战绩快照只保留最近 "
            f"{player_source.HISTORY_MAX_ENTRIES} 场（游戏服 store_single_history 的裁剪口径），"
            "更早的对局请用房间号 / uuid 在「对局记录」里查。"
        )
        return envelope.ok(payload)
