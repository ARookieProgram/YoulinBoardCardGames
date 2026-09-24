"""玩家管理接口。

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/players/` | 登录即可 | 玩家列表：搜索 / 封禁状态过滤 / 分页 |
| GET | `/api/players/overview/` | 登录即可 | 概览：玩家总数、封禁中人数 |
| GET | `/api/players/<id>/` | 登录即可 | 玩家详情 + 封禁流水 |
| POST | `/api/players/<id>/ban/` | 管理员及以上 | 封禁（可限时） |
| POST | `/api/players/<id>/unban/` | 管理员及以上 | 解封 |
| GET | `/api/players/<id>/games/` | 登录即可 | **预留**：对局记录 |
| GET | `/api/players/<id>/recharges/` | 登录即可 | **预留**：充值记录 |

权限口径：看数据是运营的日常（`operator` 及以上都能看），
**改玩家状态是管理员及以上**的操作，所以封禁 / 解封多挂一层 `IsAdminOrAbove`。
无权限返回 `10003`，未登录返回 `10002`，两者前端处理方式不同。

**本期封禁只落在管理平台自己的库**（`PlayerBan`），游戏服登录链路不做拦截——
这一点必须在文档里说明白，免得有人以为"封了就是登不上"。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AdminUser
from apps.accounts.permissions import IsAdminOrAbove
from apps.common import response as envelope
from apps.common.pagination import page_payload

from . import player_source
from .exceptions import PlayerAlreadyBanned, PlayerNotBanned, PlayerNotFound
from .models import PlayerBan
from .serializers import (
    BAN_STATE_ALL,
    BAN_STATE_BANNED,
    PlayerBanInputSerializer,
    PlayerListQuerySerializer,
    PlayerUnbanInputSerializer,
    ReservedPageQuerySerializer,
    player_detail,
    player_summary,
    reserved_payload,
)

logger = logging.getLogger(__name__)


def _operator(request: Request) -> tuple[AdminUser | None, str]:
    """取当前操作人：`(AdminUser 或 None, 账号名快照)`。"""
    admin = request.user
    if isinstance(admin, AdminUser):
        return admin, admin.username
    # 理论到不了：IsAuthenticated + SimpleJWT 已保证 user 是 AdminUser。
    return None, ""


class PlayerListView(APIView):
    """`GET /api/players/` —— 玩家列表。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """按关键字 / 封禁状态分页查询玩家。"""
        query = PlayerListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params: dict[str, Any] = dict(query.validated_data)

        only_ids: list[int] | None = None
        exclude_ids: list[int] | None = None
        if params["ban_state"] != BAN_STATE_ALL:
            # 封禁状态在管理平台库里，玩家数据在玩家库里，两边没法用一条 SQL 关联。
            # 先把"当前封禁中的 ID 集合"算出来，再作为 IN / NOT IN 条件下推给只读查询。
            # 这张表只记录发生过封禁动作的玩家，集合规模远小于玩家总数。
            banned_ids = sorted(PlayerBan.banned_player_ids())
            if params["ban_state"] == BAN_STATE_BANNED:
                only_ids = banned_ids
            else:
                exclude_ids = banned_ids

        rows, total = player_source.search_players(
            keyword=params["keyword"],
            ordering=params["ordering"],
            page=params["page"],
            page_size=params["page_size"],
            only_ids=only_ids,
            exclude_ids=exclude_ids,
        )
        records = PlayerBan.current_records([row["player_id"] for row in rows])
        items = [player_summary(row, records.get(row["player_id"])) for row in rows]
        return envelope.ok(
            page_payload(
                items=items,
                total=total,
                page=params["page"],
                page_size=params["page_size"],
            )
        )


class PlayerOverviewView(APIView):
    """`GET /api/players/overview/` —— 列表页顶部的概览数字。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """返回玩家总数与封禁中人数。"""
        return envelope.ok(
            {
                "total_players": player_source.count_players(),
                "banned_players": PlayerBan.banned_count(),
            }
        )


class PlayerDetailView(APIView):
    """`GET /api/players/<player_id>/` —— 玩家详情。"""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, player_id: int) -> Response:
        """玩家只读字段 + 当前封禁状态 + 封禁流水。"""
        row = player_source.get_player(player_id)
        if row is None:
            raise PlayerNotFound(player_id)
        return envelope.ok(player_detail(row, PlayerBan.history(player_id)))


class PlayerBanView(APIView):
    """`POST /api/players/<player_id>/ban/` —— 封禁。"""

    permission_classes = [IsAuthenticated, IsAdminOrAbove]

    def post(self, request: Request, player_id: int) -> Response:
        """写一条封禁流水。"""
        serializer = PlayerBanInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        row = player_source.get_player(player_id)
        if row is None:
            raise PlayerNotFound(player_id)
        if PlayerBan.is_banned(player_id):
            raise PlayerAlreadyBanned()

        duration_hours = data.get("duration_hours")
        expires_at = (
            timezone.now() + timedelta(hours=int(duration_hours))
            if duration_hours
            else None
        )

        admin, operator_name = _operator(request)
        record = PlayerBan.objects.create(
            player_id=player_id,
            account=row["account"],
            player_name=row["name"],
            action=PlayerBan.Action.BAN,
            reason=data["reason"],
            operator=admin,
            operator_name=operator_name,
            expires_at=expires_at,
        )
        logger.info(
            "玩家封禁 player_id=%s account=%s operator=%s expires_at=%s reason=%s",
            player_id,
            row["account"],
            operator_name,
            expires_at,
            data["reason"],
        )
        return envelope.ok(
            {"player_id": player_id, "banned": True, "ban": record.as_payload()},
            message="已封禁该玩家",
        )


class PlayerUnbanView(APIView):
    """`POST /api/players/<player_id>/unban/` —— 解封。"""

    permission_classes = [IsAuthenticated, IsAdminOrAbove]

    def post(self, request: Request, player_id: int) -> Response:
        """写一条解封流水。

        刻意**不要求玩家行存在**：玩家库暂时连不上时，运营仍然要能把封禁解开
        （否则数据源故障会把人锁死在"封着"的状态）。账号与昵称优先取最近一条
        封禁流水的快照，快照缺失时才回查玩家库。
        """
        serializer = PlayerUnbanInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)

        latest = PlayerBan.current_record(player_id)
        if latest is None or not latest.is_effective:
            raise PlayerNotBanned()

        account = latest.account
        player_name = latest.player_name
        if not account or not player_name:
            row = player_source.get_player(player_id)
            if row is not None:
                account = account or row["account"]
                player_name = player_name or row["name"]

        admin, operator_name = _operator(request)
        record = PlayerBan.objects.create(
            player_id=player_id,
            account=account,
            player_name=player_name,
            action=PlayerBan.Action.UNBAN,
            reason=data["reason"],
            operator=admin,
            operator_name=operator_name,
            expires_at=None,
        )
        logger.info(
            "玩家解封 player_id=%s account=%s operator=%s reason=%s",
            player_id,
            account,
            operator_name,
            data["reason"],
        )
        return envelope.ok(
            {"player_id": player_id, "banned": False, "ban": record.as_payload()},
            message="已解封该玩家",
        )


class _ReservedPlayerView(APIView):
    """预留端点的公共实现：只回答"契约已就绪"，不访问玩家库。"""

    permission_classes = [IsAuthenticated]

    #: 子类覆盖：功能标识 / 计划的数据来源 / 给前端的说明。
    feature: str = ""
    source: str = ""
    message: str = ""

    def get(self, request: Request, player_id: int) -> Response:
        """返回空的分页结果 + `reserved: true`。"""
        query = ReservedPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = dict(query.validated_data)
        return envelope.ok(
            reserved_payload(
                player_id=player_id,
                feature=self.feature,
                source=self.source,
                message=self.message,
                page=params["page"],
                page_size=params["page_size"],
            ),
            message="该查询入口已预留，数据源待接入",
        )


class PlayerGamesView(_ReservedPlayerView):
    """`GET /api/players/<player_id>/games/` —— **预留**：对局记录。"""

    feature = "games"
    source = "计划来源：玩家库 t_users.history（房间 uuid 列表）+ t_games / t_games_archive"
    message = "对局记录查询入口已预留：房间 uuid 在 t_users.history 里，逐局明细在 t_games，数据源待接入。"


class PlayerRechargesView(_ReservedPlayerView):
    """`GET /api/players/<player_id>/recharges/` —— **预留**：充值记录。"""

    feature = "recharges"
    source = "计划来源：充值订单表（当前玩家库只有 t_users.coins / gems 余额，没有订单流水）"
    message = "充值记录查询入口已预留：当前玩家库只有金币/房卡余额，没有订单流水表，数据源待接入。"
