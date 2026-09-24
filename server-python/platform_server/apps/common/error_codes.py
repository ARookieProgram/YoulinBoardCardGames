"""管理平台业务错误码 —— **全平台唯一的一套**。

**只属于管理平台**：与游戏客户端的错误码（`server-python/shared/` 那套）
互不相关，改动这里不会影响玩家侧。

编码规则：5 位数字，第一位固定 `1` 表示"管理平台"，后四位按模块划分。

| 段 | 模块 |
| --- | --- |
| `10xxx` | 通用（参数、登录态、权限、资源、服务端） |
| `11xxx` | 登录与令牌 |

`code == 0` 表示成功，其余一切值都表示失败。前端
（`admin-platform/src/api/`）按 `code` 弹提示、按 HTTP 状态码决定是否跳登录页。

**为什么常量放在 `apps/common/` 而不是各自的 app 里**：异常处理器
（`apps/common/exceptions.py`）必须能引用这些码，而它不该反向依赖某个具体 app。
`apps/accounts/error_codes.py` 里的登录专属码在这里定义后由那边再导出，
保证全平台只有一份数字定义。
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------- 通用

#: 请求参数不合法。
ERR_BAD_REQUEST: Final[int] = 10001

#: 未登录或令牌失效，需要重新登录（前端据此跳登录页）。
ERR_UNAUTHORIZED: Final[int] = 10002

#: 已登录但无权限。
ERR_FORBIDDEN: Final[int] = 10003

#: 资源不存在。
ERR_NOT_FOUND: Final[int] = 10004

#: 请求过于频繁（后续限流用）。
ERR_TOO_MANY_REQUESTS: Final[int] = 10005

#: 服务端内部错误。
ERR_SERVER_ERROR: Final[int] = 10500

# ---------------------------------------------------------------- 登录与令牌

#: 账号或口令错误。
#: 刻意不区分"账号不存在"和"口令错误"，避免账号枚举。
ERR_LOGIN_FAILED: Final[int] = 11001

#: 账号已被禁用。
ERR_ACCOUNT_DISABLED: Final[int] = 11002

#: 刷新令牌无效或已过期。
ERR_TOKEN_INVALID: Final[int] = 11003
