"""封禁校验：游戏服 → 管理平台（`platform_server`）的内部只读接口。

大厅服与游戏服两个进程在**登录 / 进房前**问一句"这个玩家被封了吗"，
问的对象是管理平台：

    GET <PLATFORM>/api/internal/players/ban-check/?account=..&sign=..
    GET <PLATFORM>/api/internal/players/ban-check/?player_id=..&sign=..
    sign = md5("account" + account + "player_id" + player_id + PRI_KEY)

对应 `server/utils/bancheck.ts`，两侧的**行为与签名必须逐字一致**
（参考向量钉在 `tests/test_protocol.py` 与 `tools/lib/smoke.mjs`）。

三条设计决定（改之前先读）
--------------------------

1. **fail-open**：超时、连不上、平台返回非 0，一律当作"没被封"放行，只打警告日志。
   理由：管理后台是运营工具，它挂掉不该让**全体玩家**登不上游戏。
   代价是平台故障期间被封玩家能临时进游戏——这是刻意的取舍，写进了 README/AGENTS。
2. **缓存**：成功的结果按 `CACHE_TTL_MS` 缓存（正负都缓存），所以"后台点封禁"到
   "玩家被拦下"最多滞后一个 TTL；失败的调用不缓存结果本身，但会进入
   `FAIL_COOLDOWN_MS` 的冷却窗口，避免平台挂掉时**每次登录都白等一个超时**。
3. **不抛异常**：调用方（HTTP 处理器 / socket 处理器）拿到的一定是一个
   `BanStatus`，不会因为平台抖动而把登录链路炸掉。

**密钥不一致的表现是"封禁静默失效"**：平台回 10003、游戏服 fail-open 放行，
只在日志里留一行警告。排查封禁不生效时，先看这行日志，再核对两侧密钥。
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from shared.config import BanCheckConfig

from . import http

logger = logging.getLogger(__name__)

#: 内部接口路径（与 `platform_server/apps/players/urls_internal.py` 对应）。
BAN_CHECK_PATH = "/api/internal/players/ban-check/"

#: 签名串里的字段标签。带上字段名，两个参数互相错位也不会撞出同一个签名。
ACCOUNT_LABEL = "account"
PLAYER_ID_LABEL = "player_id"

#: 失败后的冷却窗口（毫秒）：窗口内不再发请求，直接按"不知道"放行。
FAIL_COOLDOWN_MS = 5000

#: 缓存条目上限。超过就整体清空——这是刻意的粗粒度回收：
#: 条目数远小于它时不会触发，真触发时多打几次平台接口也无所谓。
MAX_CACHE_ENTRIES = 5000

_config: BanCheckConfig | None = None
_cache: dict[str, tuple[float, "BanStatus"]] = {}
_cooldown_until: float = 0.0


@dataclass
class BanStatus:
    """一次封禁校验的结果。

    `known=False` 表示"没问到平台"（未启用 / 冷却中 / 调用失败）——
    此时 `banned` 恒为 False（fail-open），调用方一律放行。
    """

    known: bool
    banned: bool
    reason: str = ""
    expires_at: str | None = None
    player_id: int | None = None


def init(config: BanCheckConfig) -> None:
    """进程启动时注入配置（对应 Node 版的 `bancheck.init`）。"""
    global _config
    _config = config


def reset() -> None:
    """清掉配置与缓存（测试用；进程里没有调用点）。"""
    global _config, _cooldown_until
    _config = None
    _cache.clear()
    _cooldown_until = 0.0


def _require_config() -> BanCheckConfig:
    if _config is None:
        raise RuntimeError("utils.bancheck.init() 尚未调用")
    return _config


def build_sign(*, account: str, player_id: int | None, key: str) -> str:
    """算出内部接口的签名（与平台侧 `apps/players/internal.py` 同一公式）。

    :param account: 玩家账号；不按账号查时传空串。
    :param player_id: 玩家 ID；不按 ID 查时传 `None`。
    :param key: 共享密钥（配置里的 `PRI_KEY`）。
    :return: 32 位小写 md5。
    """
    content = (
        ACCOUNT_LABEL
        + (account or "")
        + PLAYER_ID_LABEL
        + ("" if player_id is None else str(player_id))
        + key
    )
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _now_ms() -> float:
    """毫秒时间戳（与 JS 的 `Date.now()` 对齐）。"""
    return time.time() * 1000


async def check_account(account: str | None) -> BanStatus:
    """按账号查封禁状态（大厅服走这条，它手里只有 account）。"""
    text = (account or "").strip()
    if not text:
        return _unknown()
    return await _check(f"account:{text}", {"account": text}, account=text, player_id=None)


async def check_user_id(user_id: int | None) -> BanStatus:
    """按玩家 ID 查封禁状态（游戏服从 token 里拿到的是 userId）。"""
    if user_id is None or int(user_id) <= 0:
        return _unknown()
    value = int(user_id)
    return await _check(f"player_id:{value}", {"player_id": value}, account="", player_id=value)


def _unknown() -> BanStatus:
    """"没问到"的统一答案：放行。"""
    return BanStatus(known=False, banned=False)


def ban_message(status: BanStatus) -> str:
    """把封禁状态拼成给玩家看的一句话。

    大厅服（HTTP）与游戏服（socket）共用它，保证同一个封禁在两条链路上
    文案一致；客户端拿到 `errmsg` 后原样提示。
    """
    parts = ["账号已被封禁"]
    if status.reason:
        parts.append("原因：" + status.reason)
    if status.expires_at:
        parts.append("自动解封时间：" + status.expires_at)
    else:
        parts.append("永久封禁")
    return "；".join(parts) + "。如有疑问请联系客服。"


async def _check(
    cache_key: str,
    params: dict[str, Any],
    *,
    account: str,
    player_id: int | None,
) -> BanStatus:
    """带缓存 / 冷却的查询。任何失败都返回 `_unknown()`。"""
    global _cooldown_until

    config = _require_config()
    if not config["ENABLE"]:
        return _unknown()

    now = _now_ms()
    cached = _cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]
    if now < _cooldown_until:
        # 平台刚失败过：冷却期内不再打，避免每次登录都白等一个超时。
        return _unknown()

    query = dict(params)
    query["sign"] = build_sign(account=account, player_id=player_id, key=str(config["PRI_KEY"]))

    try:
        status = await _request(config, query)
    except Exception as error:  # noqa: BLE001 —— fail-open：任何异常都只能放行
        _cooldown_until = _now_ms() + FAIL_COOLDOWN_MS
        logger.warning(
            "封禁校验失败，本次放行（%s）：%s。请检查平台地址与两侧密钥是否一致。",
            cache_key,
            error,
        )
        return _unknown()

    _store(cache_key, status, config)
    return status


def _store(cache_key: str, status: BanStatus, config: BanCheckConfig) -> None:
    """写缓存（超上限时整体清空）。"""
    if len(_cache) >= MAX_CACHE_ENTRIES:
        _cache.clear()
    _cache[cache_key] = (_now_ms() + int(config["CACHE_TTL_MS"]), status)


async def _request(config: BanCheckConfig, params: dict[str, Any]) -> BanStatus:
    """真正发一次请求；失败时抛异常，由 `_check` 负责 fail-open。

    :raises Exception: 网络错误、超时、响应不是合法 JSON、平台返回非 0。
    """
    host = str(config["HOST"])
    port = int(config["PORT"])
    path = BAN_CHECK_PATH
    # IPv6 字面量要加方括号（与 utils/http.py 的 _host_for_url 同一个原因：
    # 拼出来的 `http://::1:8000/...` 是非法 URL）。
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    url = f"http://{host}:{port}{path}"

    session = http.init_session()
    # 每次请求单独设超时：共享 session 的默认超时是 5 分钟，登录链路不能等那么久。
    timeout = aiohttp.ClientTimeout(total=int(config["TIMEOUT_MS"]) / 1000)
    async with session.get(url, params=params, timeout=timeout) as response:
        body = await response.json(content_type=None)

    if not isinstance(body, dict) or body.get("code") != 0:
        raise RuntimeError(f"平台返回 {body!r}")
    return _parse(body.get("data"))


def _parse(data: Any) -> BanStatus:
    """把平台的 `data` 解析成 `BanStatus`（字段缺失按"没封"处理）。"""
    if not isinstance(data, dict):
        raise RuntimeError(f"平台返回的 data 不是对象：{data!r}")
    player_id = data.get("player_id")
    expires_at = data.get("expires_at")
    return BanStatus(
        known=bool(data.get("known", True)),
        banned=bool(data.get("banned", False)),
        reason=str(data.get("reason") or ""),
        expires_at=str(expires_at) if expires_at else None,
        player_id=int(player_id) if isinstance(player_id, int) else None,
    )
