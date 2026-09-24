"""管理平台业务错误码 —— **全平台唯一的一套**。

**只属于管理平台**：与游戏客户端的错误码（`server-python/shared/` 那套）
互不相关，改动这里不会影响玩家侧。

编码规则：5 位数字，第一位固定 `1` 表示"管理平台"，后四位按模块划分。

| 段 | 模块 |
| --- | --- |
| `10xxx` | 通用（参数、登录态、权限、资源、服务端） |
| `11xxx` | 登录与令牌 |
| `12xxx` | 玩家管理 |
| `13xxx` | 房间管理 |

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

# ---------------------------------------------------------------- 玩家管理

#: 玩家不存在（玩家库里查不到这个 userid）。
ERR_PLAYER_NOT_FOUND: Final[int] = 12001

#: 该玩家已处于封禁中，不能重复封禁。
ERR_PLAYER_ALREADY_BANNED: Final[int] = 12002

#: 该玩家当前不在封禁中，无需解封。
ERR_PLAYER_NOT_BANNED: Final[int] = 12003

#: 玩家只读数据源不可用（玩家库连不上 / 账号无权限）。
#: 与"玩家不存在"刻意分开：前者是运维问题，后者是运营输入问题。
ERR_PLAYER_SOURCE_UNAVAILABLE: Final[int] = 12004

# ---------------------------------------------------------------- 房间管理

#: 房间不存在（玩家库的 `t_rooms` 里没有这个房间号 / uuid）。
#: 房间是**瞬时**的：游戏服销毁房间时会删掉 `t_rooms` 里的那一行，所以
#: "查不到"最常见的原因不是输入错了，而是房间已经打完 / 已被解散。
ERR_ROOM_NOT_FOUND: Final[int] = 13001

# 说明：房间数据与玩家数据来自**同一条只读数据源**（同一个玩家库），
# 所以"玩家库连不上"仍然复用 `ERR_PLAYER_SOURCE_UNAVAILABLE`（12004），
# 不为房间另开一个码——运维看到的处置方式是同一个：去检查玩家库连接。

