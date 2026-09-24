"""给**游戏服**调用的内部只读接口。

游戏服（大厅服与游戏服两个进程）在登录 / 进房前要问一句"这个玩家有没有被封"。
管理平台不允许游戏服直连自己的库，玩家库也只有只读通道，所以这里开一个
**只读**的内部接口，用共享密钥签名认证——这是 `AGENTS.md` §2 第 5 条那条
只读通道的反方向：游戏服 → 管理平台，同样只读、同样不共享库。

     GET /api/internal/players/ban-check/?account=<account>&sign=<md5>
     GET /api/internal/players/ban-check/?player_id=<id>&sign=<md5>

签名口径（**三处实现必须逐字一致**：本文件、`server-python/utils/bancheck.py`、
`server/utils/bancheck.ts`）：

    sign = md5("account" + account + "player_id" + player_id + PRI_KEY)

缺席的那一项按空串参与拼接；密钥是 `settings.PLATFORM_INTERNAL_KEY`，与游戏服配置
`ban_check()["PRI_KEY"]` 必须一样。参考向量钉在 `server-python/tests/test_protocol.py`
（跨实现）与 `tools/lib/smoke.mjs`（Node 侧）。

**信任边界**：`/api/internal/` 下的接口不走 JWT、不做 CSRF，只认这个密钥。
部署时应在反向代理上把该前缀限制成只允许游戏服所在网络访问，不要暴露到公网；
密钥留空时接口直接拒绝服务（10500），而不是放行——详见 `InternalNotConfigured`。

**为什么不复用大厅服/账号服已有的 HTTP 接口**：那两个进程正是需要答案的调用方，
它们手里没有封禁数据（封禁记录在管理平台库里），让它们互相问会绕成一个环。
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Final

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common import response as envelope
from apps.common.exceptions import PlatformError

from . import player_source
from .exceptions import InternalNotConfigured, InternalSignInvalid
from .models import PlayerBan

#: 签名串里的字段标签。带上字段名，两个参数互相错位也不会撞出同一个签名。
ACCOUNT_LABEL: Final[str] = "account"
PLAYER_ID_LABEL: Final[str] = "player_id"


def build_sign(*, account: str, player_id: int | None, key: str) -> str:
    """算出内部接口的签名。

    :param account: 玩家账号；不按账号查时传空串。
    :param player_id: 玩家 ID；不按 ID 查时传 `None`。
    :param key: 共享密钥（`settings.PLATFORM_INTERNAL_KEY`）。
    :return: 32 位小写 md5。
    """
    content = (
        ACCOUNT_LABEL
        + (account or "")
        + PLAYER_ID_LABEL
        + ("" if player_id is None else str(player_id))
        + key
    )
    # 游戏服侧用的是 `md5(...)`（无 salt、无分隔、hex 输出），这里必须完全一致，
    # 所以直接用 hashlib，不引 Django 的 salted 哈希。
    return hashlib.md5(content.encode("utf-8")).hexdigest()


class BanCheckView(APIView):
    """`GET /api/internal/players/ban-check/` —— 玩家封禁状态（只读）。

    成功返回：

        {"code": 0, "message": "ok", "data": {
            "account": "guest_1", "player_id": 9, "known": true,
            "banned": true, "reason": "使用外挂", "expires_at": "2026-01-01 00:00:00"
        }}

    `known=false`（玩家库里查不到这个账号）时 `banned` 恒为 false；
    游戏服拿到 `known` 只是为了日志，判定只看 `banned`。
    """

    #: 内部接口不走 JWT：调用方是游戏服，它没有管理平台账号。
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        """校验签名并按 account / player_id 回答封禁状态。"""
        key = str(getattr(settings, "PLATFORM_INTERNAL_KEY", "") or "")
        if not key:
            raise InternalNotConfigured()

        account = str(request.query_params.get("account") or "").strip()
        player_id_raw = str(request.query_params.get("player_id") or "").strip()
        sign = str(request.query_params.get("sign") or "").strip()

        if not account and not player_id_raw:
            raise PlatformError("必须提供 account 或 player_id")
        if not sign:
            raise InternalSignInvalid("缺少 sign 参数")

        player_id: int | None = None
        if player_id_raw:
            if not player_id_raw.isdigit():
                raise PlatformError("player_id 必须是数字")
            player_id = int(player_id_raw)

        expected = build_sign(account=account, player_id=player_id, key=key)
        # 固定时间比较：这是共享密钥，不要给计时侧信道留口子。
        if not hmac.compare_digest(sign, expected):
            raise InternalSignInvalid()

        # 按 ID 查时不再回查账号（游戏服是从 token 里拿到 userId 的）；
        # 按账号查时要先换成 ID——封禁流水是以 player_id 为主键的。
        if player_id is None:
            row = player_source.get_player_by_account(account)
            if row is not None:
                player_id = int(row["player_id"])

        record = PlayerBan.current_record(player_id) if player_id is not None else None
        banned = record is not None and record.is_effective
        return envelope.ok(self._payload(account, player_id, record, banned))

    @staticmethod
    def _payload(
        account: str,
        player_id: int | None,
        record: PlayerBan | None,
        banned: bool,
    ) -> dict[str, Any]:
        """拼出参；未封禁时不回原因，避免把历史原因误当成当前状态。"""
        payload: dict[str, Any] = {
            "account": account,
            "player_id": player_id,
            "known": player_id is not None,
            "banned": banned,
            "reason": record.reason if (banned and record is not None) else "",
            "expires_at": (record.expires_at if (banned and record is not None) else None),
        }
        return payload
