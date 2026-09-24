"""登录与令牌相关的错误码。

**定义在 `apps/common/error_codes.py`**（异常处理器要在不依赖具体 app 的前提下
引用它们），这里只是登录模块的转出口，方便 `from . import error_codes` 的写法。

新加登录相关错误码时，数字请加在 `apps/common/error_codes.py` 的 `11xxx` 段，
不要在本文件里另起一套。
"""

from __future__ import annotations

from apps.common.error_codes import (
    ERR_ACCOUNT_DISABLED,
    ERR_BAD_REQUEST,
    ERR_FORBIDDEN,
    ERR_LOGIN_FAILED,
    ERR_NOT_FOUND,
    ERR_SERVER_ERROR,
    ERR_TOKEN_INVALID,
    ERR_TOO_MANY_REQUESTS,
    ERR_UNAUTHORIZED,
)

__all__ = [
    "ERR_ACCOUNT_DISABLED",
    "ERR_BAD_REQUEST",
    "ERR_FORBIDDEN",
    "ERR_LOGIN_FAILED",
    "ERR_NOT_FOUND",
    "ERR_SERVER_ERROR",
    "ERR_TOKEN_INVALID",
    "ERR_TOO_MANY_REQUESTS",
    "ERR_UNAUTHORIZED",
]
