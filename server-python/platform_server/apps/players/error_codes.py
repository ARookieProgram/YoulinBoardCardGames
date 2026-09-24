"""玩家管理相关错误码的转出口。

**定义在 `apps/common/error_codes.py` 的 `12xxx` 段**（异常处理器要在不依赖
具体 app 的前提下引用它们），这里只是转出口，方便 `from . import error_codes`。
不要在本文件里另起一套数字。
"""

from __future__ import annotations

from apps.common.error_codes import (
    ERR_BAD_REQUEST,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_PLAYER_ALREADY_BANNED,
    ERR_PLAYER_NOT_BANNED,
    ERR_PLAYER_NOT_FOUND,
    ERR_PLAYER_SOURCE_UNAVAILABLE,
    ERR_UNAUTHORIZED,
)

__all__ = [
    "ERR_BAD_REQUEST",
    "ERR_FORBIDDEN",
    "ERR_NOT_FOUND",
    "ERR_PLAYER_ALREADY_BANNED",
    "ERR_PLAYER_NOT_BANNED",
    "ERR_PLAYER_NOT_FOUND",
    "ERR_PLAYER_SOURCE_UNAVAILABLE",
    "ERR_UNAUTHORIZED",
]
