"""房间登录 token 的生成与有效期校验。

对应 `server/game_server/tokenmgr.ts`。

token 由游戏服的 `/enter_room` 内部接口创建（`http_service.py`），
客户端带着它去 socket.io 登录；`socket_service.py` 用它换 userId。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from utils import crypto


@dataclass
class TokenInfo:
    """一条 token 记录。"""

    userId: int
    #: 生成时刻（毫秒）。
    time: int
    #: 有效期，由 `create_token` 的入参写入。
    lifeTime: int


#: token -> 记录；`del_token` 会把它置成 None（原实现如此，不是 delete）。
_tokens: dict[str, TokenInfo | None] = {}
#: userId -> token。
_users: dict[int, str | None] = {}


def create_token(user_id: int, life_time: int) -> str:
    """为一个玩家签发 token（同一玩家已有 token 时先作废旧的）。

    :param user_id: 玩家 id。
    :param life_time: 有效期（毫秒）。
    :return: 新 token。
    """
    token = _users.get(user_id)
    if token is not None:
        del_token(token)

    time = int(_now_ms())
    token = crypto.md5(f"{user_id}!@#$%^&{time}")
    _tokens[token] = TokenInfo(userId=user_id, time=time, lifeTime=life_time)
    _users[user_id] = token
    return token


def get_token(user_id: int) -> str | None:
    """取某个玩家当前的 token。"""
    return _users.get(user_id)


def get_user_id(token: str) -> int:
    """用 token 换 userId。

    **行为保留**：原实现是 `tokens[token].userId`，token 不存在时会抛 TypeError。
    这里让 `KeyError` 抛出去，保留同样的崩溃语义，而不是悄悄返回 None。
    """
    return _tokens[token].userId  # type: ignore[union-attr]


def is_token_valid(token: str) -> bool:
    """token 是否有效。

    **历史 bug（移植不修，改它要单独开一次改动）**：原实现读的是 `info.lifetime`
    （小写 t），而 `create_token` 写入的字段是 `lifeTime`，因此取到 undefined，
    `time + undefined` 是 NaN，`NaN < Date.now()` 恒为 false —— 本函数**恒返回 True**，
    token 实际上不过期。

    这里把"读一个从不存在的字段"写成 `_legacy_lifetime()`，让这个行为在代码里
    看得见，而不是靠巧合。
    """
    info = _tokens.get(token)
    if info is None:
        return False
    if info.time + _legacy_lifetime(info) < _now_ms():
        return False
    return True


def del_token(token: str) -> None:
    """删除 token（同时清掉玩家的 token 映射）。"""
    info = _tokens.get(token)
    if info is not None:
        _tokens[token] = None
        _users[info.userId] = None


def _legacy_lifetime(info: TokenInfo) -> float:
    """读老代码里的 `info.lifetime`（小写 t）。这个字段从未被写入过，所以永远是 `NaN`。"""
    return getattr(info, "lifetime", math.nan)


def _now_ms() -> float:
    """毫秒时间戳（对应 JS 的 `Date.now()`）。"""
    import time

    return time.time() * 1000
