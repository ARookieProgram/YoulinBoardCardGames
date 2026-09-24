"""房间管理接口。

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/rooms/` | 登录即可 | 存活房间列表：搜索 / 玩法 / 状态过滤 / 排序 / 分页 |
| GET | `/api/rooms/overview/` | 登录即可 | 概览：房间总数、满座数、未满座数、24 小时新建 |
| GET | `/api/rooms/<room_id>/` | 登录即可 | 房间详情（配置 + 四个座位）+ 预留运维入口说明 |
| POST | `/api/rooms/<room_id>/dissolve/` | 管理员及以上 | **预留**：强制解散（恒返回 `reserved: true`） |

数据来源：**玩家库 `db_scmj` 的 `t_rooms`**，走 `apps/players/player_source.py`
这条**唯一只读通道**（只执行 SELECT）。本应用没有模型，也不往玩家库写任何一行；
"强制解散"要写游戏服的内存与库，属于游戏服务端的职责，本期只预留入口。

关于"房间":`t_rooms` 里只有**尚未销毁**的房间——游戏服的 `roommgr.destroy()`
会删掉整行，进程重启时再用这些行把房间恢复回内存。所以查不到某个房间号
最常见的原因是"它已经打完了"，而不是运营输错了，`13001` 的文案里写了这一点。

权限口径与玩家管理一致：**看数据是运营的日常**（`operator` 及以上都能看），
**动房间是管理员及以上**——所以预留的解散入口多挂一层 `IsAdminOrAbove`，
现在它虽然还不做实事，但将来接入时权限已经是对的了。
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AdminUser
from apps.accounts.permissions import IsAdminOrAbove
from apps.common import response as envelope
from apps.common.pagination import page_payload
from apps.players import player_source

from .exceptions import RoomNotFound
from .serializers import (
    RoomListQuerySerializer,
    reserved_dissolve_payload,
    room_detail_payload,
    room_payload,
    validate_room_ref,
)

logger = logging.getLogger(__name__)


def _operator_name(request: Request) -> str:
    """取当前操作人的账号名（写日志用；理论到不了 `None` 分支）。"""
    admin = request.user
    return admin.username if isinstance(admin, AdminUser) else ""


class RoomListView(APIView):
    """`GET /api/rooms/` —— 存活房间列表。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """按关键字 / 玩法 / 座位占用分页查询房间。"""
        query = RoomListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params: dict[str, Any] = dict(query.validated_data)

        rows, total = player_source.search_rooms(
            keyword=params["keyword"],
            room_type=params["room_type"],
            state=params["state"],
            ordering=params["ordering"],
            page=params["page"],
            page_size=params["page_size"],
        )
        return envelope.ok(
            page_payload(
                items=[room_payload(row) for row in rows],
                total=total,
                page=params["page"],
                page_size=params["page_size"],
            )
        )


class RoomOverviewView(APIView):
    """`GET /api/rooms/overview/` —— 列表页顶部的概览数字。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """返回房间总数、满座 / 未满座数与最近 24 小时新建数。"""
        return envelope.ok(player_source.room_overview())


class RoomDetailView(APIView):
    """`GET /api/rooms/<room_id>/` —— 房间详情（房间号或 uuid 都可以）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, room_id: str) -> Response:
        """房间配置 + 四个座位 + 预留运维入口的可用性。"""
        room_ref = validate_room_ref(room_id)
        row = player_source.get_room(room_ref)
        if row is None:
            # 房间是瞬时的，所以"刚还在列表里、点开就没了"是正常现象。
            raise RoomNotFound(room_ref)
        return envelope.ok(room_detail_payload(row))


class RoomDissolveView(APIView):
    """`POST /api/rooms/<room_id>/dissolve/` —— **预留**：强制解散房间。

    本期**不做实事**：返回 `reserved: true` 与计划实现，让契约先定下来
    （前端已经在调它、权限已经挂好），接上游戏服接口时只需要换掉这个实现。
    """

    permission_classes = [IsAuthenticated, IsAdminOrAbove]

    def post(self, request: Request, room_id: str) -> Response:
        """校验房间存在后返回预留说明。"""
        room_ref = validate_room_ref(room_id)
        row = player_source.get_room(room_ref)
        if row is None:
            raise RoomNotFound(room_ref)

        logger.info(
            "强制解散入口被调用（当前为预留，未对房间做任何操作）"
            " room_id=%s uuid=%s operator=%s",
            row["room_id"],
            row["uuid"],
            _operator_name(request),
        )
        return envelope.ok(
            reserved_dissolve_payload(room_id=row["room_id"], uuid=row["uuid"]),
            message="强制解散入口已预留，游戏服接口待接入",
        )
