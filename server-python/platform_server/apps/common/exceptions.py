"""统一异常处理：把 DRF/Django 抛出的异常翻译成 `{code, message, data}`。

在 `settings.REST_FRAMEWORK["EXCEPTION_HANDLER"]` 里注册。没有这一层，
DRF 会吐出它自己的 `{"detail": "..."}`，前端就得为每种错误写一套解析。

约定：

* 业务错误（`PlatformError`）：用异常自带的 code / status / message；
* DRF 的 `ValidationError` / `AuthenticationFailed` 等：映射到对应的业务码；
* 未捕获异常：记录堆栈后返回 500，**不把堆栈泄露给前端**（DEBUG 时除外）。
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from . import error_codes
from . import response as envelope

logger = logging.getLogger(__name__)


class PlatformError(Exception):
    """管理平台的业务异常基类。

    视图里 `raise PlatformError("账号或密码错误", code=..., status_code=...)`
    比手动构造失败响应更省事，并且保证走同一套外壳。
    """

    def __init__(
        self,
        message: str,
        *,
        code: int = error_codes.ERR_BAD_REQUEST,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.data = data


class LoginFailed(PlatformError):
    """账号或口令错误。

    **为什么需要这个子类**：DRF 的 `ValidationError` 只表达"参数不合法"，
    统一异常处理器只能把它映射成 `ERR_BAD_REQUEST`。要给出精确的
    `ERR_LOGIN_FAILED`，异常类型本身就必须能携带这个语义，
    否则就会出现"测试断言文案通过、客户端拿到的却是 10001"这种偏差
    （这个 bug 真的发生过，见 `scripts/e2e_login_check.sh`）。
    """

    def __init__(self, message: str = "账号或密码错误") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_LOGIN_FAILED,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AccountDisabled(PlatformError):
    """账号已被禁用。"""

    def __init__(self, message: str = "该账号已被禁用，请联系超级管理员") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_ACCOUNT_DISABLED,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class TokenInvalid(PlatformError):
    """刷新令牌无效或已过期。"""

    def __init__(self, message: str = "登录已过期，请重新登录") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_TOKEN_INVALID,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


def _validation_message(detail: Any) -> str:
    """把 DRF 的嵌套校验错误压成一行可读文案。"""
    if isinstance(detail, dict):
        parts: list[str] = []
        for field, value in detail.items():
            text = _validation_message(value)
            # `non_field_errors` 是 DRF 对整体错误的键名，不该展示给用户。
            parts.append(text if field == "non_field_errors" else f"{field}: {text}")
        return "; ".join(parts)
    if isinstance(detail, (list, tuple)):
        return "; ".join(_validation_message(item) for item in detail)
    return str(detail)


def platform_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF 异常处理器。

    :param exc: 视图抛出的异常。
    :param context: DRF 提供的上下文（含 view / request）。
    :return: 统一外壳的响应；`None` 表示交给 Django 继续处理（不会发生，见下）。
    """
    # 本方业务异常：优先级最高。
    if isinstance(exc, PlatformError):
        return envelope.fail(
            exc.code,
            exc.message,
            status=exc.status_code,
            data=exc.data,
        )

    # 交给 DRF 先翻译，拿到它认为合适的状态码与 detail。
    drf_response = drf_exception_handler(exc, context)

    if isinstance(exc, drf_exceptions.ValidationError):
        return envelope.fail(
            error_codes.ERR_BAD_REQUEST,
            _validation_message(exc.detail),
            status=status.HTTP_400_BAD_REQUEST,
            data=exc.detail,
        )

    if isinstance(exc, (drf_exceptions.NotAuthenticated, drf_exceptions.AuthenticationFailed)):
        return envelope.fail(
            error_codes.ERR_UNAUTHORIZED,
            "登录状态已失效，请重新登录",
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, (drf_exceptions.PermissionDenied, DjangoPermissionDenied)):
        return envelope.fail(
            error_codes.ERR_FORBIDDEN,
            "没有权限执行该操作",
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, Http404):
        return envelope.fail(
            error_codes.ERR_NOT_FOUND,
            "请求的资源不存在",
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, drf_exceptions.APIException):
        detail = exc.detail
        message = _validation_message(detail) if not isinstance(detail, str) else detail
        # DRF 自带异常（如 Throttled）的 status_code 直接当业务码用会有歧义，
        # 统一映射到"参数不合法/服务端错误"两档，HTTP 状态码保持 DRF 原值。
        code = (
            error_codes.ERR_SERVER_ERROR
            if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
            else error_codes.ERR_BAD_REQUEST
        )
        return envelope.fail(code, message, status=exc.status_code)

    # 没被 DRF 识别的异常：记录堆栈，返回 500。
    # DEBUG=True 时不吞掉，交给 Django 的调试页，方便定位。
    if drf_response is None:
        from django.conf import settings

        logger.exception("未处理的服务端异常: %s", exc)
        if settings.DEBUG:
            return None
        return envelope.fail(
            error_codes.ERR_SERVER_ERROR,
            "服务器内部错误，请稍后重试",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 理论上到不了这里（上面的分支已覆盖 DRF 的全部异常），保底返回 drf_response。
    return drf_response
