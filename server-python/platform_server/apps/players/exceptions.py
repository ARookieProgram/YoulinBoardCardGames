"""玩家管理相关的业务异常。

业务码都挂在**异常类型**上，而不是靠 `ValidationError` 的 `code`——
原因与登录那几个异常一样（见 `apps/common/exceptions.py` 的 `LoginFailed`）：
DRF 的 `ValidationError` 走到统一异常处理器时只剩 `detail`，
自定义业务码会被压成通用的 `ERR_BAD_REQUEST`。

数字定义在 `apps/common/error_codes.py` 的 `12xxx` 段，这里不重复定义。
"""

from __future__ import annotations

from rest_framework import status

from apps.common import error_codes
from apps.common.exceptions import PlatformError


class PlayerNotFound(PlatformError):
    """玩家库里没有这个 userid。"""

    def __init__(self, player_id: object) -> None:
        super().__init__(
            f"玩家 {player_id} 不存在",
            code=error_codes.ERR_PLAYER_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PlayerAlreadyBanned(PlatformError):
    """该玩家已在封禁中。"""

    def __init__(self, message: str = "该玩家已处于封禁中，无需重复封禁") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_PLAYER_ALREADY_BANNED,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class PlayerNotBanned(PlatformError):
    """该玩家当前没有被封禁。"""

    def __init__(self, message: str = "该玩家当前不在封禁中，无需解封") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_PLAYER_NOT_BANNED,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class PlayerSourceUnavailable(PlatformError):
    """玩家只读数据源不可用（连不上玩家库 / 账号没有权限）。

    与"玩家不存在"刻意分开：前者是运维问题（要去看数据库配置），
    后者是运营输入问题（账号或 ID 写错了）。
    """

    def __init__(self, message: str = "玩家数据源暂时不可用，请稍后重试") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_PLAYER_SOURCE_UNAVAILABLE,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class PlayerSourceReadOnlyViolation(RuntimeError):
    """只读数据源里出现了非 SELECT 语句。

    这是**代码 bug**，不是用户错误，所以不继承 `PlatformError`：
    它必须在开发/测试阶段就炸出来，而不是变成一条 503 悄悄放过。
    `tests/test_players.py::PlayerSourceIsolationTests` 会主动触发它。
    """
