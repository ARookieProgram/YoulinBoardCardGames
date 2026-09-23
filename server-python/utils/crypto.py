"""摘要与 Base64 工具。

对应 `server/utils/crypto.py`，行为逐字一致：

* `md5()`：进房签名（`md5(roomid + token + time + ROOM_PRI_KEY)`）、大厅服与游戏服之间的
  内部接口签名，以及 token 生成；
* `to_base64()` / `from_base64()`：用户名进出库的编码（`utils/db.py` 内部使用）。

已知向量由 `server-python/tests/test_crypto.py` 钉住（与 Node 版
`tools/lib/smoke.mjs` 用的是同一组向量）。
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from .jscompat import js_str


def md5(content: Any) -> str:
    """计算字符串的 md5（小写十六进制）。

    `content` 允许传非字符串：Node 版里 `crypto.md5(userId + ...)` 的 `+` 会先做
    `String()` 转换，这里用 `js_str` 复现同一套转换（`null -> "null"`、`NaN -> "NaN"`）。

    :param content: 待摘要内容。
    :return: 32 位十六进制摘要。
    """
    return hashlib.md5(js_str(content).encode("utf-8")).hexdigest()


def to_base64(content: str) -> str:
    """UTF-8 字符串转 Base64。"""
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def from_base64(content: str) -> str:
    """Base64 还原 UTF-8 字符串。

    Node 的 `Buffer.from(content, "base64")` 对非法字符是宽松的（忽略），
    Python 的 `b64decode(validate=False)` 行为一致。
    """
    return base64.b64decode(content).decode("utf-8")
