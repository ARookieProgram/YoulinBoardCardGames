"""管理员账号管理（`/api/admins/`）的业务异常。

与登录那几个异常（`LoginFailed` / `AccountDisabled`）同一套约定：
**业务码挂在异常类型上**，而不是靠 DRF `ValidationError` 的 `code`——
原因见 `apps/common/exceptions.py` 的 `LoginFailed` 注释：
统一异常处理器只能从异常类型上读到业务码。

数字定义在 `apps/common/error_codes.py` 的 `15xxx` 段，这里不重复定义。
"""

from __future__ import annotations

from rest_framework import status

from apps.common import error_codes
from apps.common.exceptions import PlatformError


class AdminNotFound(PlatformError):
    """`accounts_adminuser` 里没有这个 id。"""

    def __init__(self, admin_id: object) -> None:
        super().__init__(
            f"管理员 {admin_id} 不存在",
            code=error_codes.ERR_ADMIN_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class AdminUsernameTaken(PlatformError):
    """账号名已被占用（大小写不敏感判重）。"""

    def __init__(self, username: str) -> None:
        super().__init__(
            f"账号名「{username}」已被占用",
            code=error_codes.ERR_ADMIN_USERNAME_TAKEN,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AdminEmailTaken(PlatformError):
    """邮箱已被其他管理员占用。"""

    def __init__(self, email: str) -> None:
        super().__init__(
            f"邮箱「{email}」已被其他管理员使用",
            code=error_codes.ERR_ADMIN_EMAIL_TAKEN,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AdminSelfOperation(PlatformError):
    """不能对自己做这个操作（停用 / 删除 / 给自己降级）。

    前端也按同样的规则把按钮置灰，但**服务端必须自己再判一次**：
    前端置灰只是提示，不是防线。
    """

    def __init__(self, message: str = "不能对自己执行该操作") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_ADMIN_SELF_OPERATION,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AdminLastSuperAdmin(PlatformError):
    """不能停用 / 删除 / 降级最后一个启用中的超级管理员。"""

    def __init__(self, message: str = "不能停用、删除或降级最后一个启用中的超级管理员") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_ADMIN_LAST_SUPER,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AdminOldPasswordIncorrect(PlatformError):
    """本人改口令时原口令不正确。"""

    def __init__(self, message: str = "原密码不正确") -> None:
        super().__init__(
            message,
            code=error_codes.ERR_ADMIN_OLD_PASSWORD,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
