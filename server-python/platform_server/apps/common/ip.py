"""客户端 IP 提取。

登录日志要记来源 IP。直接读 `request.META["REMOTE_ADDR"]` 在反向代理后面
拿到的是代理地址，所以这里优先看 `X-Forwarded-For` 的**第一段**（最靠近客户端
的那一跳）。

安全提醒：`X-Forwarded-For` 是客户端可伪造的头。部署时必须在反向代理上
**覆盖**（而不是追加）这个头，`PLATFORM_BEHIND_PROXY=1` 才可信；
本机开发直连时走 `REMOTE_ADDR`，伪造不了。
"""

from __future__ import annotations

from django.core.validators import validate_ipv46_address
from django.core.exceptions import ValidationError

#: `X-Forwarded-For` 最大可信跳数，防止超长头撑爆字段。
MAX_FORWARDED_HOPS = 8


def _is_valid_ip(value: str) -> bool:
    """判断字符串是不是合法 IPv4/IPv6 地址。"""
    try:
        validate_ipv46_address(value)
    except ValidationError:
        return False
    return True


def get_client_ip(request: object) -> str | None:
    """取出请求的来源 IP。

    顺序：`X-Forwarded-For` 第一段 → `X-Real-IP` → `REMOTE_ADDR`。
    取不到或格式非法时返回 `None`（`AdminUser.last_login_ip` 允许为空）。

    :param request: Django/DRF 的 request（只要有 `META` 属性即可）。
    :return: IP 字符串，或 `None`。
    """
    meta = getattr(request, "META", None)
    if not isinstance(meta, dict):
        return None

    forwarded = meta.get("HTTP_X_FORWARDED_FOR")
    if isinstance(forwarded, str) and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",")][:MAX_FORWARDED_HOPS]
        for hop in hops:
            if _is_valid_ip(hop):
                return hop

    real_ip = meta.get("HTTP_X_REAL_IP")
    if isinstance(real_ip, str) and _is_valid_ip(real_ip.strip()):
        return real_ip.strip()

    remote = meta.get("REMOTE_ADDR")
    if isinstance(remote, str) and _is_valid_ip(remote):
        return remote

    return None
