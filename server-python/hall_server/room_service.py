"""游戏服上报接口（:9002）+ 向游戏服发起内部调用。

对应 `server/hall_server/room_service.ts`。

`/register_gs` 是游戏服每 5 秒心跳上报的入口；`create_room` / `enter_room` 是大厅服
主动调游戏服内部 HTTP 接口的两个函数，签名拼接顺序必须与 `game_server/http_service.py`
逐字一致——改任一侧都是"大厅服调不通游戏服"。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from utils import crypto, db, http

#: `config` 由 `create_routes()` 在开始监听前赋值，所有请求处理里必然已经就绪。
_config: dict[str, Any] | None = None
_hall_ip: str | None = None

#: 房间号 -> 游戏服地址（`ip:port`）。
rooms: dict[str, str] = {}
#: 游戏服地址（`clientip:clientport`）-> 上报信息。
server_map: dict[str, dict[str, Any]] = {}
#: userId -> 房间号。
room_id_of_users: dict[str, str] = {}


@dataclass
class EnterInfo:
    """`create_room` / `enter_room` 交给调用方的进房信息：`token` 由游戏服 `/enter_room` 下发。"""

    ip: str | None
    port: str | None
    token: str


def _port_of(info: dict[str, Any]) -> int | None:
    """把上报里的 `httpPort`（query 字符串）转成 aiohttp 需要的整数端口。

    Node 版把它原样交给 `http.get` 的 `options.port`，Node 接受字符串；
    Python 侧必须显式转一次，转不出来就当作"没给端口"。
    """
    value = info.get("httpPort")
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def create_routes(config: dict[str, Any]) -> web.Application:
    """建大厅服的上报服务应用。"""
    global _config
    _config = config

    app = web.Application()

    @web.middleware
    async def cors(request: web.Request, handler: Any) -> web.StreamResponse:
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "X-Requested-With"
        response.headers["Access-Control-Allow-Methods"] = "PUT,POST,GET,DELETE,OPTIONS"
        response.headers["X-Powered-By"] = " 3.2.1"
        if "Content-Type" not in response.headers:
            response.headers["Content-Type"] = "application/json;charset=utf-8"
        return response

    app.middlewares.append(cors)

    async def on_register_gs(request: web.Request) -> web.Response:
        ip = http.request_ip(request)
        clientip = http.query_string(request, "clientip")
        clientport = http.query_string(request, "clientport")
        http_port = http.query_string(request, "httpPort")
        load = http.query_string(request, "load")
        server_id = str(clientip) + ":" + str(clientport)

        if server_id in server_map:
            info = server_map[server_id]
            if (
                info.get("clientport") != clientport
                or info.get("httpPort") != http_port
                or info.get("ip") != ip
            ):
                print("duplicate gsid:" + server_id + ",addr:" + ip + "(" + str(http_port) + ")")
                return http.send(1, "duplicate gsid:" + server_id)
            info["load"] = load
            return http.send(0, "ok", {"ip": ip})

        server_map[server_id] = {
            "ip": ip,
            "id": server_id,
            # 上面的 id 已经用 `clientip + ":" + clientport` 算过；这里显式转字符串，
            # 与老代码把值直接放进对象的隐式转字符串结果相同（缺参数时一样是 "None"）。
            "clientip": str(clientip),
            "clientport": str(clientport),
            "httpPort": http_port,
            "load": load,
        }
        print(
            "game server registered.\n\tid:"
            + server_id
            + "\n\taddr:"
            + ip
            + "\n\thttp port:"
            + str(http_port)
            + "\n\tsocket clientport:"
            + str(clientport)
        )

        # 原实现是"先把 HTTP 回包发出去，再异步去拉 /get_server_info"。
        # 这里保持同样的时序：把那次调用丢到后台任务里，不等它就把 ok 回给游戏服
        # （否则游戏服每 5 秒的心跳都要多等一个来回，对方不可达时还会被拖住）。
        reqdata = {
            "serverid": server_id,
            "sign": crypto.md5(server_id + _require_config()["ROOM_PRI_KEY"]),
        }
        _spawn(_fetch_server_info(ip, _port_of(server_map[server_id]), reqdata))
        return http.send(0, "ok", {"ip": ip})

    app.router.add_get("/register_gs", on_register_gs)
    return app


async def _fetch_server_info(ip: str, port: int | None, reqdata: dict[str, Any]) -> None:
    """拉一次游戏服的 `/get_server_info`（原实现里的异步回调体）。"""
    result = await http.get(ip, port, "/get_server_info", reqdata)
    if not result.ok:
        return
    data = result.data
    if data.get("errcode") == 0:
        user_room_info = data.get("userroominfo") or []
        # 原实现只是把数组两两取出来（局部变量随后被丢弃），这里如实保留这个循环。
        for i in range(0, len(user_room_info), 2):
            _ = user_room_info[i]
            _ = user_room_info[i + 1] if i + 1 < len(user_room_info) else None
    else:
        print(data.get("errmsg"))


#: 后台任务的强引用集合（不保留引用的话任务可能被 GC 掉）。
_background_tasks: set[Any] = set()


def _spawn(coroutine: Any) -> None:
    task = asyncio.get_running_loop().create_task(coroutine)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def choose_server() -> dict[str, Any] | None:
    """挑一台负载最低的游戏服（`load` 按**字符串**比较，与原实现一致）。"""
    serverinfo: dict[str, Any] | None = None
    for info in server_map.values():
        new_load = info.get("load")
        if serverinfo is None:
            serverinfo = info
        else:
            old_load = serverinfo.get("load")
            if old_load is not None and new_load is not None and old_load > new_load:
                serverinfo = info
    return serverinfo


def _require_config() -> dict[str, Any]:
    if _config is None:
        raise RuntimeError("room_service.create_routes() 尚未调用")
    return _config


async def create_room(
    account: str | None,
    user_id: Any,
    room_conf: Any,
) -> tuple[int, str | None]:
    """请求游戏服建房。

    :return: `(errcode, roomId)`；101 没有可用游戏服、102 调不通、103 查不到房卡。
    """
    serverinfo = choose_server()
    if serverinfo is None:
        return 101, None

    data = await db.get_gems(account)
    if data is None:
        return 103, None

    reqdata: dict[str, Any] = {
        "userid": user_id,
        "gems": data.get("gems"),
        # 客户端传来的建房配置：它本来就是 query 里的一个 JSON 字符串，按老代码原样带上。
        "conf": room_conf,
    }
    # 签名拼接顺序与游戏服 http_service.py 完全一致：userId + conf + gems + ROOM_PRI_KEY。
    reqdata["sign"] = crypto.md5(
        str(user_id) + str(room_conf) + str(data.get("gems")) + _require_config()["ROOM_PRI_KEY"]
    )

    result = await http.get(
        str(serverinfo.get("ip")), _port_of(serverinfo), "/create_room", reqdata
    )
    if not result.ok:
        return 102, None

    if result.data.get("errcode") == 0:
        return 0, result.data.get("roomid")
    return int(result.data.get("errcode") or 0), None


async def enter_room(
    user_id: Any,
    name: str | None,
    room_id: str | None,
) -> tuple[int, EnterInfo | None]:
    """请求游戏服进房，返回客户端连游戏服需要的 `(ip, port, token)`。"""
    reqdata: dict[str, Any] = {
        "userid": user_id,
        "name": name,
        "roomid": room_id,
    }
    # 签名拼接顺序与游戏服 http_service.py 完全一致：userId + name + roomId + ROOM_PRI_KEY。
    reqdata["sign"] = crypto.md5(
        str(user_id) + str(name) + str(room_id) + _require_config()["ROOM_PRI_KEY"]
    )

    async def check_room_is_running(serverinfo: dict[str, Any]) -> bool:
        # 与游戏服 /is_room_runing 的校验一致：md5(roomId + ROOM_PRI_KEY)。
        sign = crypto.md5(str(room_id) + _require_config()["ROOM_PRI_KEY"])
        result = await http.get(
            str(serverinfo.get("ip")),
            _port_of(serverinfo),
            "/is_room_runing",
            {"roomid": room_id, "sign": sign},
        )
        if not result.ok:
            # 网络失败等价于"没在跑"。
            return False
        return result.data.get("errcode") == 0 and result.data.get("runing") is True

    async def enter_room_req(serverinfo: dict[str, Any]) -> tuple[int, EnterInfo | None]:
        result = await http.get(
            str(serverinfo.get("ip")), _port_of(serverinfo), "/enter_room", reqdata
        )
        if not result.ok:
            return -1, None
        data = result.data
        print(data)
        if data.get("errcode") == 0:
            await db.set_room_id_of_user(user_id, room_id)
            return 0, EnterInfo(
                ip=serverinfo.get("clientip"),
                port=serverinfo.get("clientport"),
                token=data.get("token"),
            )
        print(data.get("errmsg"))
        return int(data.get("errcode") or 0), None

    ok, ip, port = await db.get_room_addr(room_id)
    if ok:
        server_id = str(ip) + ":" + str(port)
        serverinfo = server_map.get(server_id)
        if serverinfo is not None:
            if await check_room_is_running(serverinfo):
                return await enter_room_req(serverinfo)
            chosen = choose_server()
            if chosen is not None:
                return await enter_room_req(chosen)
            return -1, None
        chosen = choose_server()
        if chosen is not None:
            return await enter_room_req(chosen)
        return -1, None
    return -2, None
