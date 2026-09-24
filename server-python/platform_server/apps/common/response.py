"""统一 HTTP 响应外壳。

前端只按一个形状解析响应，不用为每个接口记不同的字段：

    {"code": 0, "message": "ok", "data": {...}}

`code` 为 `0` 表示成功；非 0 是业务错误码，**定义集中在
`apps/common/error_codes.py`**（本模块不重复定义，避免两套数字打架）。
HTTP 状态码仍然有意义（401/403/404/...），前端拦截器按状态码决定
"要不要跳登录页"，按 `code` 决定"弹什么提示"。

异常 → 响应外壳的转换只发生在 `apps/common/exceptions.py` 一处，
视图里直接 `return ok(data)` 即可，不需要自己拼字典。
"""

from __future__ import annotations

from typing import Any, Final

from rest_framework.response import Response

#: 成功响应的业务码。
CODE_OK: Final[int] = 0


def ok(data: Any = None, message: str = "ok") -> Response:
    """构造成功响应。

    :param data: 业务数据，任意可 JSON 序列化的值。
    :param message: 提示文案，默认 `ok`。
    :return: HTTP 200 的 DRF 响应。
    """
    return Response({"code": CODE_OK, "message": message, "data": data})


def created(data: Any = None, message: str = "ok") -> Response:
    """构造创建成功响应（HTTP 201）。"""
    return Response({"code": CODE_OK, "message": message, "data": data}, status=201)


def fail(
    code: int,
    message: str,
    *,
    status: int = 400,
    data: Any = None,
) -> Response:
    """构造业务失败响应。

    :param code: 业务错误码（非 0），取值见 `apps/common/error_codes.py`。
    :param message: 面向用户的提示文案。
    :param status: HTTP 状态码。
    :param data: 附加数据（例如字段级校验错误）。
    """
    return Response({"code": code, "message": message, "data": data}, status=status)
