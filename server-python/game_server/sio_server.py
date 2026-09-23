"""Engine.IO 3 / Socket.IO 4 服务端的最小实现（基于 aiohttp）。

## 为什么不用现成的库

客户端是 vendored 的 **socket.io-client 2.0.0** → **Socket.IO 协议 4 + Engine.IO 协议 3**。
两条现成的路都走不通：

* `python-socketio` 5.x / `python-engineio` 4.x **硬编码拒绝 EIO=3**
  （`engineio/server.py`：`if sid is None and query.get('EIO') != ['4']` 直接 400），
  客户端连握手都过不去；
* 退回到支持 EIO3 的 `python-socketio` 4.6.1 / `python-engineio` 3.13.2，
  在 **Python 3.14 上已经跑不起来**：`asyncio.wait()` 从 3.12 起禁止传入协程，
  而它正是用 `asyncio.wait([...coroutines])` 实现 `emit` —— 也就是**所有服务端推送**
  都会抛 `TypeError`；此外 `aiohttp` 3.14 下它的 polling 响应 Content-Type 退化成
  `application/octet-stream`，EIO3 的字符串载荷会被客户端当二进制解析。

所以这里按协议自己实现一层。范围严格限定在本仓库真正用到的特性：

* 传输：`websocket`（客户端 `transports: ['websocket', 'polling']` 的首选）与 `polling`；
* 包类型：Engine.IO 的 open/close/ping/pong/message；Socket.IO 的 connect/disconnect/event；
* 载荷：JSON（字符串/数字/布尔/数组/对象/null），无二进制、无 namespace、无 ack。

## 与原 Node 服务端的对应关系

原实现用 `socket.io` 1.7.x（`socketio(httpServer)`）。这里对外暴露的用法刻意做成同一形状：

    server = SocketIOServer()
    server.on('connection', on_connection)
    socket.on('login', on_login)
    await socket.emit('login_result', {...})
    await user_mgr.send_msg(user_id, 'hu_push', {...})

唯一差别是本实现的 `emit` / `disconnect` 都是**协程**（原版是同步的），
因为底层 aiohttp 的写操作是 await 的。

## 两个容易踩的协议细节

1. **心跳方向**：EIO3 是**客户端发 ping、服务端回 pong**（EIO4 反过来）。
   凭据：客户端 bundle 里 `case 'pong': this.setPing();` —— 收到 pong 之后才安排下一次 ping。
2. **"不传数据"与"传 null"不是一回事**：
   `socket.emit('login_finished')` 在线上是 `42["login_finished"]`，
   而 `socket.emit('game_huanpai_push', undefined)` 是 `42["game_huanpai_push",null]`。
   客户端拿到的分别是 `undefined` 与 `null`。原实现两种写法都有，所以这里用
   `NO_DATA` 哨兵把两者区分开。
"""

from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import WSMsgType, web

# Engine.IO 包类型（协议 v3）
EIO_OPEN = "0"
EIO_CLOSE = "1"
EIO_PING = "2"
EIO_PONG = "3"
EIO_MESSAGE = "4"
EIO_UPGRADE = "5"
EIO_NOOP = "6"

# Socket.IO 包类型（协议 v4）
SIO_CONNECT = "0"
SIO_DISCONNECT = "1"
SIO_EVENT = "2"
SIO_ACK = "3"
SIO_ERROR = "4"

#: 表示"这次 emit 没有第二个参数"（见模块文档的说明）。
NO_DATA = object()

#: 默认心跳参数，取自 socket.io 1.x 的默认值。
DEFAULT_PING_INTERVAL = 25000
DEFAULT_PING_TIMEOUT = 60000

Handler = Callable[..., Awaitable[None]]


class Socket:
    """一条客户端连接（对应 socket.io 的 `Socket`，本仓库还会往上挂业务字段）。"""

    def __init__(
        self,
        server: "SocketIOServer",
        sid: str,
        query: dict[str, str],
        address: str,
    ) -> None:
        self._server = server
        self.sid = sid
        self.query = query
        #: 对端地址；`socket_service` 登录时会写进房间座位的 `ip` 字段。
        self.address = address

        #: 登录成功后写入；未登录为 None。
        self.userId: int | None = None
        #: 登录成功后写入，指向房间所用的玩法实现。
        self.gameMgr: Any = None

        self._handlers: dict[str, Handler] = {}
        self._ws: web.WebSocketResponse | None = None
        self._poll_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._connected = False
        self._established = False
        self._disconnecting = False
        self.last_activity = time.monotonic()

    # -- 事件注册 ---------------------------------------------------------

    def on(self, event: str, handler: Handler | None = None) -> Any:
        """注册一个客户端事件处理器（也可以当装饰器用）。

        `event == "disconnect"` 是 socket.io 内置的断开事件，处理器只收一个"原因"参数。
        """
        if handler is None:

            def decorator(func: Handler) -> Handler:
                self._handlers[event] = func
                return func

            return decorator
        self._handlers[event] = handler
        return handler

    # -- 发送 -------------------------------------------------------------

    async def emit(self, event: str, data: Any = NO_DATA) -> None:
        """给这个连接推一个事件。

        :param event: 事件名（与客户端 `addHandler` 逐字一致）。
        :param data: 载荷；**不传**表示线上是 `[event]`，显式传 `None` 表示 `[event,null]`。
        """
        if data is NO_DATA:
            packet = f"{SIO_EVENT}" + json.dumps([event], separators=(",", ":"), ensure_ascii=True)
        else:
            packet = f"{SIO_EVENT}" + json.dumps(
                [event, data], separators=(",", ":"), ensure_ascii=True
            )
        await self._send_eio(EIO_MESSAGE + packet)

    async def disconnect(self) -> None:
        """服务端主动断开这条连接。

        与原实现一致：**服务端的主动断开也会触发 `disconnect` 处理器**。
        `socket_service` 里几处调用点（`exit` / `dispress` / `kickAllInRoom`）
        依赖这个行为——它们先 `userMgr.del`，再 `disconnect`，
        于是处理器里的 `userMgr.get(userId) != socket` 判空成立、直接返回。
        """
        if self._disconnecting:
            return
        self._disconnecting = True
        try:
            await self._close_transport()
        finally:
            await self._server._forget(self)
            await self._server._fire_disconnect(self, "server namespace disconnect")

    # -- 底层发送 ---------------------------------------------------------

    async def _send_eio(self, packet: str) -> None:
        """发一个 Engine.IO 包（websocket 直发，polling 进队列）。"""
        if not self._connected:
            return
        if self._ws is not None:
            async with self._send_lock:
                if self._ws.closed:
                    return
                try:
                    await self._ws.send_str(packet)
                except (ConnectionResetError, RuntimeError):
                    pass
        else:
            await self._poll_queue.put(packet)
        self.last_activity = time.monotonic()

    async def _close_transport(self) -> None:
        """关掉底层传输（不发 Socket.IO 的 DISCONNECT 包，与原实现的 `disconnect()` 一致）。"""
        self._connected = False
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.send_str(EIO_CLOSE)
            except (ConnectionResetError, RuntimeError):
                pass
            await self._ws.close()
        # 叫醒可能正挂着长轮询的 GET
        await self._poll_queue.put(None)

    async def _deliver(self, engine_packet: str) -> None:
        """收到的 Engine.IO 包分发。"""
        self.last_activity = time.monotonic()
        packet_type = engine_packet[0]
        payload = engine_packet[1:]

        if packet_type == EIO_PING:
            # EIO3：客户端发 ping，服务端回 pong（原样带回 data）
            await self._send_eio(EIO_PONG + payload)
            return
        if packet_type == EIO_PONG:
            return
        if packet_type == EIO_CLOSE:
            await self._server._forget(self)
            await self._server._fire_disconnect(self, "transport close")
            return
        if packet_type != EIO_MESSAGE:
            return

        await self._deliver_sio(payload)

    async def _deliver_sio(self, packet: str) -> None:
        """收到的 Socket.IO 包分发。"""
        if not packet:
            return
        packet_type = packet[0]
        body = packet[1:]

        if packet_type == SIO_CONNECT:
            # 兼容"客户端主动发 CONNECT"的写法（socket.io 2.x+）。本仓库的客户端是
            # socket.io 1.x，默认 namespace 下**不会**发这个包，服务端才是发起方；
            # 这里做成幂等，两种客户端都能用。
            await self._server._establish(self)
            return

        if packet_type == SIO_DISCONNECT:
            await self._server._forget(self)
            await self._server._fire_disconnect(self, "client namespace disconnect")
            return

        if packet_type != SIO_EVENT:
            # ack / error / 二进制：本仓库的客户端不会用到，忽略即可
            return

        try:
            decoded: Any = json.loads(body) if body else []
        except ValueError:
            return
        if not isinstance(decoded, list) or not decoded:
            return

        event = decoded[0]
        args = decoded[1:]
        handler = self._handlers.get(event)
        if handler is None:
            return
        try:
            # 客户端 `sock.emit('event')`（不带第二个参数）在线上是 `42["event"]`，
            # 此时 `args` 为空——Node 版里处理器拿到的 `data` 是 `undefined`，
            # 所以这里传 `None`，而不是"不传参数"（后者对形参是必填的处理器会抛 TypeError）。
            await handler(args[0] if args else None)
        except Exception as error:  # noqa: BLE001 —— 单个事件出错不能拖垮连接
            print(f"[sio] handler '{event}' failed: {type(error).__name__}: {error}")


class SocketIOServer:
    """极简 socket.io 服务端：只管一个默认 namespace 与 JSON 事件。"""

    def __init__(
        self,
        *,
        path: str = "/socket.io/",
        ping_interval: int = DEFAULT_PING_INTERVAL,
        ping_timeout: int = DEFAULT_PING_TIMEOUT,
    ) -> None:
        self.path = path
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self._sockets: dict[str, Socket] = {}
        self._connection_handlers: list[Handler] = []
        self._watchdog: asyncio.Task[None] | None = None

    # -- 注册 -------------------------------------------------------------

    def on(self, event: str, handler: Handler | None = None) -> Any:
        """注册服务端级事件；本实现只支持 `connection`。

        用法与原实现一致：`server.on('connection', fn)`，`fn(socket)`。
        """
        if event != "connection":
            raise ValueError(f"仅支持 'connection' 事件，收到：{event}")
        if handler is None:

            def decorator(func: Handler) -> Handler:
                self._connection_handlers.append(func)
                return func

            return decorator
        self._connection_handlers.append(handler)
        return handler

    # -- 发送 -------------------------------------------------------------

    async def emit(self, event: str, data: Any = NO_DATA, *, to: int | None = None) -> None:
        """给单个连接推事件（按 userId 定位）。

        :param to: 目标 userId；不在线则**静默丢弃**（与原实现一致）。
        """
        if to is None:
            return
        for socket in list(self._sockets.values()):
            if socket.userId == to:
                await socket.emit(event, data)

    async def close(self) -> None:
        """关闭所有连接与看门狗（进程退出时调用）。"""
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None
        for socket in list(self._sockets.values()):
            await socket._close_transport()
        self._sockets.clear()

    # -- 内部 -------------------------------------------------------------

    async def _fire_connection(self, socket: Socket) -> None:
        for handler in self._connection_handlers:
            try:
                await handler(socket)
            except Exception as error:  # noqa: BLE001
                print(f"[sio] connection handler failed: {type(error).__name__}: {error}")

    async def _establish(self, socket: Socket) -> None:
        """建立 Socket.IO 层的连接：先发 `40`，再触发 `connection` 处理器（幂等）。

        **顺序不能反**，也不能等客户端发 `40`：socket.io 1.x 的服务端是发起方
        （`socket.io/lib/server.js` 的 `onconnection` 立刻 `client.connect('/')`，
        `lib/socket.js` 的 `Socket.prototype.onconnect` 发出 CONNECT 包），
        而客户端在默认 namespace 下**不发** CONNECT（只在收到服务端 CONNECT 之后
        才触发 `connect` 并开始 `emit`）。顺序反了会出现"客户端永远不 connect"。
        """
        if socket._established:
            return
        socket._established = True
        socket._connected = True
        await socket._send_eio(EIO_MESSAGE + SIO_CONNECT)
        await self._fire_connection(socket)

    async def _fire_disconnect(self, socket: Socket, reason: str) -> None:
        handler = socket._handlers.get("disconnect")
        if handler is None:
            return
        try:
            await handler(reason)
        except Exception as error:  # noqa: BLE001
            print(f"[sio] disconnect handler failed: {type(error).__name__}: {error}")

    async def _forget(self, socket: Socket) -> None:
        self._sockets.pop(socket.sid, None)

    # -- HTTP 接入 --------------------------------------------------------

    def attach(self, app: web.Application) -> None:
        """把 `/socket.io/` 的路由挂到一个 aiohttp 应用上。"""
        app.router.add_route("GET", self.path, self._handle_get)
        app.router.add_route("POST", self.path, self._handle_post)
        app.router.add_route("OPTIONS", self.path, self._handle_options)

    async def start(self) -> None:
        """启动心跳看门狗（在应用启动后调用）。"""
        if self._watchdog is None:
            self._watchdog = asyncio.create_task(self._watchdog_loop())

    async def _watchdog_loop(self) -> None:
        """踢掉心跳超时的连接（对应 socket.io 的 pingTimeout）。"""
        limit = (self.ping_interval + self.ping_timeout) / 1000
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            for socket in list(self._sockets.values()):
                if now - socket.last_activity > limit:
                    await socket._close_transport()
                    await self._forget(socket)
                    await self._fire_disconnect(socket, "ping timeout")

    def _new_socket(self, request: web.Request) -> Socket:
        sid = secrets.token_hex(16)
        query = dict(request.query)
        address = request.remote or ""
        socket = Socket(self, sid, query, address)
        self._sockets[sid] = socket
        return socket

    async def _handle_options(self, request: web.Request) -> web.Response:
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            },
        )

    async def _handle_get(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("transport") == "websocket":
            return await self._handle_websocket(request)
        return await self._handle_poll_get(request)

    async def _handle_post(self, request: web.Request) -> web.StreamResponse:
        return await self._handle_poll_post(request)

    async def _handle_websocket(self, request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)

        sid = request.query.get("sid")
        socket = self._sockets.get(sid) if sid else None
        fresh = socket is None
        if socket is None:
            socket = self._new_socket(request)
        socket._ws = ws

        # 直接以 websocket 起手（客户端 transports 首选就是它）时，先发 open 包
        if fresh:
            socket._connected = True
            await ws.send_str(EIO_OPEN + self._handshake_json(socket, upgrades=[]))
            await self._establish(socket)

        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    await socket._deliver(message.data)
                elif message.type == WSMsgType.BINARY:
                    # 本仓库的聊天/语音都是字符串，二进制不参与协议
                    continue
                elif message.type == WSMsgType.ERROR:
                    break
        finally:
            if self._sockets.get(socket.sid) is socket:
                await self._forget(socket)
                await self._fire_disconnect(socket, "transport close")
        return ws

    def _handshake_json(self, socket: Socket, upgrades: list[str]) -> str:
        return json.dumps(
            {
                "sid": socket.sid,
                "upgrades": upgrades,
                "pingInterval": self.ping_interval,
                "pingTimeout": self.ping_timeout,
            },
            separators=(",", ":"),
        )

    async def _handle_poll_get(self, request: web.Request) -> web.Response:
        sid = request.query.get("sid")
        if not sid:
            # 握手：新建会话，回 open 包 + Socket.IO 的 CONNECT 包（polling 允许升级到 websocket）
            socket = self._new_socket(request)
            socket._connected = True
            await socket._send_eio(EIO_OPEN + self._handshake_json(socket, ["websocket"]))
            await self._establish(socket)
            return _polling_response(_encode_payload(_drain_queue(socket)))

        socket = self._sockets.get(sid)
        if socket is None:
            return _polling_response("1:6")  # 未知 sid：回一个 NOOP，客户端会重连

        # 长轮询：等到有包、或到超时为止
        packets: list[str] = []
        deadline = time.monotonic() + min(self.ping_interval, 20000) / 1000
        while not packets:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                packets.append(EIO_NOOP)
                break
            try:
                packet = await asyncio.wait_for(socket._poll_queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                packets.append(EIO_NOOP)
                break
            if packet is None:
                packets.append(EIO_CLOSE)
                break
            packets.append(packet)
            _drain_queue(socket, packets)

        return _polling_response(_encode_payload(packets))

    async def _handle_poll_post(self, request: web.Request) -> web.Response:
        sid = request.query.get("sid")
        socket = self._sockets.get(sid) if sid else None
        if socket is None:
            return web.Response(status=400, text="Invalid session")

        raw = await request.read()
        for packet in _decode_payload(raw):
            await socket._deliver(packet)

        # engine.io 对 POST 的回包固定是 `ok` + text/html（避免 XHR 预检）
        return web.Response(
            text="ok",
            content_type="text/html",
            headers={"Access-Control-Allow-Origin": "*"},
        )


# ---------------------------------------------------------------------------
# Engine.IO 3 的 polling 载荷编解码
# ---------------------------------------------------------------------------


def _encode_payload(packets: list[str]) -> str:
    """把若干 Engine.IO 包编成 polling 载荷：`<长度>:<包>` 依次拼接。

    **出参保证是纯 ASCII**：socket.io 的 JSON 用 `ensure_ascii=True` 生成，
    所以这里的"长度"同时等于字符数、`latin-1` 字节数和 UTF-8 字节数。
    这一点很关键——客户端把响应体按**字节**逐个映射成字符
    （`String.fromCharCode.apply(null, new Uint8Array(...))`），
    长度头与它的 `msg.length` 校验必须对得上。
    """
    if not packets:
        return "0:"
    return "".join(f"{len(packet)}:{packet}" for packet in packets)


def _decode_payload(raw: bytes) -> list[str]:
    """把 polling 请求体解成 Engine.IO 包列表（`<长度>:<包>` 依次解析）。

    客户端编码时走了 engine.io 的 `utf8.encode`：**每个 UTF-8 字节变成一个字符**，
    再交给 XHR 按 UTF-8 发送。所以要先把响应体按 UTF-8 解回"字节字符"串，
    按字符数切包，最后把每个包按 `latin-1` 还原成字节再按 UTF-8 解码，
    才能拿回客户端真正发出的字符串（中文聊天内容走的就是这条路）。
    """
    text = raw.decode("utf-8", errors="replace")
    packets: list[str] = []
    index = 0
    length = 0
    digits = ""
    while index < len(text):
        char = text[index]
        if char != ":":
            digits += char
            index += 1
            continue
        try:
            length = int(digits)
        except ValueError:
            break
        index += 1
        message = text[index : index + length]
        index += length
        digits = ""
        if not message:
            continue
        packets.append(_wtf8_decode(message))
    return packets


def _wtf8_decode(text: str) -> str:
    """把"每个字节一个字符"的串还原成真正的字符串；不是这种串时原样返回。"""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _drain_queue(socket: Socket, packets: list[str] | None = None) -> list[str]:
    """把 polling 队列里已经排好的包一次取完（尽量少几个往返）。

    `None` 是"传输已关闭"的哨兵，翻译成 Engine.IO 的 CLOSE 包。
    """
    result = [] if packets is None else packets
    while not socket._poll_queue.empty():
        extra = socket._poll_queue.get_nowait()
        result.append(EIO_CLOSE if extra is None else extra)
    return result


def _polling_response(body: str) -> web.Response:
    """polling 的响应：`text/plain; charset=UTF-8`，原实现如此。"""
    return web.Response(
        body=body.encode("utf-8"),
        content_type="text/plain",
        charset="UTF-8",
        headers={"Access-Control-Allow-Origin": "*"},
    )


# `math` 只用于类型上的一致性，避免 linters 报未使用；保留导出便于测试。
_ = math
