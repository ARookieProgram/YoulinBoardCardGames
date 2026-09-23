"""HTTP 客户端 / 统一响应出口。

对应 `server/utils/http.ts`。Node 版是回调风格（`callback(ret, data)`），
Python 版改为 `async`/`await` 并返回结果对象——这是本次移植里**有意为之**的差异：
asyncio 下再套一层回调只会让调用方变成"回调地狱"，而且 aiomysql 本身就是 await 的。

对外行为（拼接的 URL、查询参数、错误日志文案、JSON 出参结构）保持一致。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from .jscompat import js_parse_int

# ---------------------------------------------------------------------------
# 查询参数与结果对象
# ---------------------------------------------------------------------------

#: URL 查询参数。客户端 `HTTP.js` 全部用 GET，参数走 query string。
QueryParams = dict[str, Any]

#: 解析后的 JSON 响应体。
JsonObject = dict[str, Any]


@dataclass
class HttpResult:
    """`get` / `get2` 的结果：先看 `ok`，再取 `data` 或 `error`。

    对应 Node 版的 `HttpResult` 可判别联合。
    """

    ok: bool
    data: JsonObject = field(default_factory=dict)
    error: Exception | None = None


# ---------------------------------------------------------------------------
# 共享的 aiohttp 会话
# ---------------------------------------------------------------------------

_session: aiohttp.ClientSession | None = None


def init_session() -> aiohttp.ClientSession:
    """进程启动时建一个共享的 ClientSession（Node 版没有这一步，它每次 `http.get` 都用全局 agent）。"""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """进程退出时关闭共享会话。"""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


def _host_for_url(host: str) -> str:
    """把主机名放进 URL；IPv6 字面量必须用方括号包起来。

    Node 版的 `http.request({hostname, port, path})` 把主机与端口分开传，天然没有这个问题；
    Python 这边是拼 URL，`http://::1:19003/...` 是非法 URL，会被 aiohttp 直接拒绝
    （游戏服向大厅服注册时对端可能是 `::1`，这条路一定会走到）。
    """
    if ":" in host and not host.startswith("["):
        return "[" + host + "]"
    return host


def _stringify(data: QueryParams | None) -> str:
    """把查询参数拼成 query string。

    对应 Node 的 `querystring.stringify`：值为 `None`/`undefined` 的键**整个丢掉**，
    其余值按字符串处理（`urlencode` 默认也会这样做，但会把 `None` 写成 "None"，
    所以先过滤）。布尔值 Node 会写成 "true"/"false"（小写），这里显式转换。
    """
    if not data:
        return ""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        if value is None:
            continue
        if value is True:
            pairs.append((key, "true"))
        elif value is False:
            pairs.append((key, "false"))
        else:
            pairs.append((key, str(value)))
    return urlencode(pairs)


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------


async def get(
    host: str,
    port: int | None,
    path: str,
    data: QueryParams,
    safe: bool = False,
) -> HttpResult:
    """GET 一个 JSON 接口（按 host/port/path 组装）。

    与 `get2` 的区别只在入参形态：这个版本让调用方分别给 host、port、path。

    :param host: 目标主机。
    :param port: 目标端口（不传则用协议默认端口）。
    :param path: 路径。
    :param data: 查询参数。
    :param safe: 为 True 时用 https。
    :return: 结果对象；网络失败时 `ok=False`。
    """
    content = _stringify(data)
    url = f"{'https' if safe else 'http'}://{_host_for_url(host)}"
    if port:
        url += f":{port}"
    url += path + "?" + content
    return await _get_json(url, host=host, port=port, path=path)


async def get2(url: str, data: QueryParams, safe: bool = False) -> HttpResult:
    """GET 一个 JSON 接口（整条 url 由调用方给全）。

    :param url: 完整 URL。
    :param data: 查询参数。
    :param safe: 为 True 时用 https（保留入参以对齐 Node 版签名；url 里已带协议）。
    :return: 结果对象；网络失败时 `ok=False`。
    """
    content = _stringify(data)
    full_url = url + "?" + content
    return await _get_json(full_url)


async def _get_json(
    url: str,
    host: str | None = None,
    port: int | None = None,
    path: str | None = None,
) -> HttpResult:
    """请求一个 JSON 接口并把响应体解析成对象。"""
    session = init_session()
    try:
        async with session.get(url) as response:
            text = await response.text()
            parsed: Any = json.loads(text)
            if not isinstance(parsed, dict):
                # Node 版的 `JSON.parse(chunk)` 在负载不是对象时会把数组/标量交给回调，
                # TypeScript 的类型注释写的是 JsonObject，这里按对象收窄，包一层避免调用方炸掉。
                parsed = {"data": parsed}
            return HttpResult(ok=True, data=parsed)
    except Exception as error:  # noqa: BLE001 —— 与原实现一样：任何失败都走 ok=False
        print("problem with request: " + _describe_error(error, url, host, port, path))
        return HttpResult(ok=False, error=error)


async def get_raw(
    url: str,
    data: QueryParams,
    safe: bool = False,
    encoding: str | None = None,
) -> tuple[str | None, JsonObject | str | None]:
    """拉取一个 URL 的原始响应体。

    对应 Node 的 `getRaw(url, data, safe, encoding, callback)`（原名 `getSync`，
    历史上用 fibers 把异步 HTTP 包装成同步调用，fibers 移除后改成回调风格）。

    :param url: 完整 URL。
    :param data: 查询参数。
    :param safe: 为 True 时用 https（url 里已带协议，保留入参以对齐签名）。
    :param encoding: 响应编码；传 `"binary"` 时不做 JSON 解析，直接把原始文本返回。
    :return: `(contentType, body)`；失败时两个都是 `None`。
    """
    content = _stringify(data)
    # data 为空时不要拼出多余的 '?'
    req_url = url + "?" + content if content else url
    use_encoding = encoding or "utf8"

    session = init_session()
    try:
        async with session.get(req_url) as response:
            content_type = response.headers.get("Content-Type")
            body = await response.text()
            if use_encoding != "binary":
                try:
                    parsed: Any = json.loads(body)
                    if not isinstance(parsed, dict):
                        parsed = {"data": parsed}
                    return content_type, parsed
                except Exception as error:  # noqa: BLE001
                    print(f"JSON parse error: {error}, url: {req_url}")
                    return None, None
            return content_type, body
    except Exception as error:  # noqa: BLE001
        print("problem with request: " + code_of(error) + " — " + req_url)
        return None, None


async def get_bytes(url: str, data: QueryParams | None = None) -> tuple[str | None, bytes | None]:
    """拉取一个 URL 的**原始字节**（账号服 `/image` 代理图片用）。

    Node 版的 `/image` 走 `getRaw(..., 'binary')` 再 `res.write(data, 'binary')`：
    encoding='binary' 在 Node 里就是 latin-1，逐字节写回。Python 这边直接拿 bytes 更准确，
    不会在 text 解码上丢字节。
    """
    content = _stringify(data)
    req_url = url + "?" + content if content else url
    session = init_session()
    try:
        async with session.get(req_url) as response:
            return response.headers.get("Content-Type"), await response.read()
    except Exception as error:  # noqa: BLE001
        print("problem with request: " + code_of(error) + " — " + req_url)
        return None, None


def request_ip(request: web.Request) -> str:
    """取客户端 IP，形态与 Express 的 `req.ip` 对齐。

    Node 的服务端默认监听双栈地址，一条 IPv4 连接的 `socket.remoteAddress` 是
    `"::ffff:127.0.0.1"`（IPv4-mapped IPv6），Express 的 `req.ip` 也是这个形态。
    aiohttp 给的是裸的 `"127.0.0.1"`，这里补回映射前缀，客户端与大厅服的
    `ip.indexOf("::ffff:")` 判断才与 Node 版一致。
    """
    address = request.remote or ""
    if address == "":
        return ""
    if ":" in address:
        return address
    return "::ffff:" + address


# ---------------------------------------------------------------------------
# 统一响应出口
# ---------------------------------------------------------------------------

def _dumps(payload: Any) -> str:
    """与 `JSON.stringify` 对齐的序列化：无多余空格、不转义非 ASCII。"""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def json_response(data: dict[str, Any] | None = None, *, content_type: str = "application/json") -> web.Response:
    """把一个字典按 `JSON.stringify` 的形状返回（不附加 errcode/errmsg）。"""
    body = _dumps({} if data is None else data)
    return web.Response(
        body=body.encode("utf-8"),
        content_type=content_type,
        charset="utf-8",
        headers={"X-Powered-By": " 3.2.1"},
    )


def send(
    errcode: int,
    errmsg: str,
    data: dict[str, Any] | None = None,
) -> web.Response:
    """大厅服与游戏服给客户端/调用方返回 JSON 的统一出口。

    对应 Node 的 `send(res, errcode, errmsg, data)`：把 errcode / errmsg **就地写进** data
    再序列化。Python 版返回 `web.Response` 而不是写 `res`，其余完全一致。

    :param errcode: 业务错误码，0 表示成功。
    :param errmsg: 错误描述。
    :param data: 业务数据；会被就地写入 errcode / errmsg 后序列化。
    """
    payload = {} if data is None else data
    payload["errcode"] = errcode
    payload["errmsg"] = errmsg
    return json_response(payload)


# ---------------------------------------------------------------------------
# 请求参数助手
# ---------------------------------------------------------------------------


def query_string(request: web.Request, name: str) -> str | None:
    """取 query 参数里的字符串形态；不存在时返回 `None`（对应 JS 的 undefined）。

    本仓库的接口只走 `HTTP.js` 的 GET + 简单 query（见 protocol.md §3），
    实际拿到的永远是字符串；数组/对象一律当作"没传"。
    """
    return request.query.get(name)


def query_int(request: web.Request, name: str) -> int | float:
    """取 query 参数里的整数，语义对齐原来的 `parseInt(req.query.x)`：缺参数返回 NaN。

    能解析成整数时返回 `int`（JS 的 number 9 序列化成 `9` 而不是 `9.0`，
    这一点会影响落库的 `base_info` JSON）；无法解析时返回 `float("nan")`，
    与 JS 一样在签名拼接里变成字符串 `"NaN"`。
    """
    value = query_string(request, name)
    parsed = js_parse_int("" if value is None else value)
    if isinstance(parsed, float) and parsed.is_integer():
        return int(parsed)
    return parsed


# ---------------------------------------------------------------------------
# 错误文案
# ---------------------------------------------------------------------------


def code_of(error: BaseException) -> str:
    """取错误的 `code`（Node 的 errno 错误带这个字段）。

    原实现是 `(e && e.code) ? e.code : e.message`：优先用 `code`，没有则退回 `message`。
    """
    code = getattr(error, "errno", None)
    if isinstance(code, str) and code != "":
        return code
    if isinstance(code, int):
        return str(code)
    message = str(error)
    return message if message != "" else "unknown error"


def _describe_error(
    error: BaseException,
    url: str,
    host: str | None,
    port: int | None,
    path: str | None,
) -> str:
    """把请求错误写成"哪台机器、哪个端口、哪个路径、什么错误"。

    直接用 `str(e)` 是不够的：Node 版对 localhost 会同时尝试 ::1 与 127.0.0.1，
    两个都失败时抛出的是 message 为空的 AggregateError，日志里只剩
    "problem with request: "，完全看不出到底连不上谁（游戏服每秒向大厅服心跳，
    日志会被这种空行刷屏）。Python 版同样把目标写进文案。
    """
    code = code_of(error)
    if host is not None:
        return f"{code} — {host}:{port or ''}{path or ''}"
    return f"{code} — {url}"


__all__ = [
    "HttpResult",
    "JsonObject",
    "QueryParams",
    "close_session",
    "code_of",
    "get",
    "get2",
    "get_bytes",
    "get_raw",
    "init_session",
    "json_response",
    "query_int",
    "query_string",
    "request_ip",
    "send",
]
