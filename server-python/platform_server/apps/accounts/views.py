"""登录相关接口。

四个端点，构成完整的登录闭环：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login/` | 账号 + 口令 → access/refresh + 管理员信息 |
| POST | `/api/auth/refresh/` | refresh → 新的 access（并轮换 refresh） |
| GET | `/api/auth/me/` | 当前登录管理员信息 |
| POST | `/api/auth/logout/` | 吊销 refresh，退出登录 |

**隔离说明**：这里的所有查询只落在 `AdminUser` 表。玩家的 `/login` 在账号服
（`server-python/account_server`，端口 9000），与本模块没有共用代码、共用表或
共用令牌，玩家账号无法登录这里，反之亦然。
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.common import response as envelope
from apps.common.ip import get_client_ip

from . import error_codes
from .models import AdminUser
from .serializers import (
    AdminUserSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshSerializer,
    blacklist_refresh_token,
    issue_tokens,
)

logger = logging.getLogger(__name__)


class LoginView(APIView):
    """`POST /api/auth/login/` —— 管理平台登录。

    成功返回：

        {"code": 0, "message": "ok", "data": {
            "access": "...", "refresh": "...",
            "access_expires_at": 1730000000,
            "user": {...}
        }}
    """

    #: 登录当然不能要求先登录。
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        """校验入参并签发令牌。"""
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        admin: AdminUser = serializer.validated_data["admin"]
        payload = issue_tokens(admin, request)

        logger.info(
            "管理员登录成功 username=%s role=%s ip=%s",
            admin.username,
            admin.effective_role,
            get_client_ip(request),
        )
        return envelope.ok(payload, message="登录成功")


class RefreshTokenView(TokenRefreshView):
    """`POST /api/auth/refresh/` —— 用 refresh 换新的 access。

    在 SimpleJWT 的 `TokenRefreshView` 之上只做三件事，不自己重写轮换逻辑：

    1. 把响应包成统一外壳；
    2. 顺带返回 `user`，前端刷新令牌后不必再打一次 `/me/`；
    3. **核对账号仍然启用**——否则"登录后被禁用"的账号能靠 refresh 无限续期。

    配置开启了 `ROTATE_REFRESH_TOKENS`，所以旧 refresh 会立即进黑名单，
    响应里的新 refresh 必须覆盖前端本地那一个。
    """

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    serializer_class = RefreshSerializer

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """轮换令牌并补充管理员信息。"""
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return envelope.fail(
                error_codes.ERR_TOKEN_INVALID,
                "登录已过期，请重新登录",
                status=status.HTTP_401_UNAUTHORIZED,
            )

        data: dict[str, Any] = dict(serializer.validated_data)

        # `RefreshSerializer.validate` 已经把 admin_id 解出来了；
        # 账号被删或禁用时，令牌本身仍然"有效"，所以必须单独拦。
        admin_id = serializer.admin_id
        admin = AdminUser.objects.filter(pk=admin_id).first() if admin_id else None
        if admin is None or not admin.is_enabled:
            return envelope.fail(
                error_codes.ERR_ACCOUNT_DISABLED,
                "账号不可用，请联系超级管理员",
                status=status.HTTP_403_FORBIDDEN,
            )

        data["user"] = AdminUserSerializer(admin).data
        return envelope.ok(data)


class CurrentAdminView(APIView):
    """`GET /api/auth/me/` —— 当前登录管理员信息。

    前端每次进后台（或刷新页面）都靠这个接口确认登录态是否还有效，
    并用返回的 `user` 渲染顶栏与菜单权限。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """返回当前管理员资料。"""
        admin = request.user
        if not isinstance(admin, AdminUser):
            # 理论上不会发生：IsAuthenticated 已保证 user 是 AdminUser。
            return envelope.fail(
                error_codes.ERR_UNAUTHORIZED,
                "登录状态已失效，请重新登录",
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return envelope.ok(AdminUserSerializer(admin).data)


class LogoutView(APIView):
    """`POST /api/auth/logout/` —— 退出登录。

    服务端能做的只有"把 refresh 拉黑"：JWT 是无状态的，已经签发出去的
    access 在过期前依然有效。前端必须同时清掉本地令牌，否则等于没退出。
    需要"立即失效"时把 `ACCESS_TOKEN_LIFETIME` 调短即可。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """吊销 refresh 令牌。"""
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_refresh: str = serializer.validated_data.get("refresh", "")

        revoked = blacklist_refresh_token(raw_refresh)
        if not revoked and raw_refresh:
            logger.warning("退出时 refresh 令牌无效或已被吊销，按已退出处理")

        logger.info(
            "管理员退出 username=%s ip=%s",
            getattr(request.user, "username", "?"),
            get_client_ip(request),
        )
        return envelope.ok({"revoked": revoked}, message="已退出登录")
