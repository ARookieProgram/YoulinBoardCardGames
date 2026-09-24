"""游戏服给大厅服调用的内部 HTTP 接口（:9003）。

对应 `server/game_server/http_service.ts`。

四个接口（`/get_server_info`、`/create_room`、`/enter_room`、`/is_room_runing`）
**都校验 `sign`**，`/get_server_info` 用的是 `md5(serverid + ROOM_PRI_KEY)`，
其余三个与登录链路同源（拼接顺序见各处理器，任何改动都会导致大厅服调不通）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from aiohttp import web

from game_server import roommgr, tokenmgr
from utils import crypto, http
from utils.jscompat import js_keys, js_number

_config: dict[str, Any] | None = None

#: 本机对外暴露的 ip，由心跳回包里的 `ip` 字段写入；建房时作为房间地址落库。
server_ip = ""

#: 心跳上报给大厅服的载荷，最终被拼成 query string。
game_server_info: dict[str, Any] = {}
last_tick_time = 0.0

_tick_task: asyncio.Task[None] | None = None


def _require_config() -> dict[str, Any]:
    if _config is None:
        raise RuntimeError("http_service.create_routes() 尚未调用")
    return _config


def create_routes(config: dict[str, Any]) -> web.Application:
    """建游戏服的内部 HTTP 应用，并启动每秒一次的心跳检查。"""
    global _config, game_server_info, last_tick_time, _tick_task
    _config = config
    last_tick_time = 0.0

    game_server_info = {
        "id": config["SERVER_ID"],
        "clientip": config["CLIENT_IP"],
        "clientport": config["CLIENT_PORT"],
        "httpPort": config["HTTP_PORT"],
        "load": roommgr.get_total_rooms(),
    }

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

    async def on_get_server_info(request: web.Request) -> web.Response:
        server_id = http.query_string(request, "serverid")
        sign = http.query_string(request, "sign")
        print(server_id)
        print(sign)
        if server_id != config["SERVER_ID"] or sign is None:
            return http.send(1, "invalid parameters")

        digest = crypto.md5(str(server_id) + config["ROOM_PRI_KEY"])
        if digest != sign:
            return http.send(1, "sign check failed.")

        locations = roommgr.get_user_locations()
        arr: list[str] = []
        # `for...in` 的键在 JS 里是字符串，且整数键按升序枚举——这里两样都保持一致。
        for user_id in js_keys(locations):
            location = locations[user_id]
            room_id = location.roomId
            arr.append(str(user_id))
            arr.append(room_id)
        return http.send(0, "ok", {"userroominfo": arr})

    async def on_create_room(request: web.Request) -> web.Response:
        user_id = http.query_int(request, "userid")
        sign = http.query_string(request, "sign")
        gems = http.query_string(request, "gems")
        conf = http.query_string(request, "conf")
        if user_id is None or sign is None or conf is None:
            return http.send(1, "invalid parameters")

        digest = crypto.md5(str(user_id) + str(conf) + str(gems) + config["ROOM_PRI_KEY"])
        if digest != sign:
            print("invalid reuqest.")
            return http.send(1, "sign check failed.")

        room_conf = json.loads(str(conf))
        # 原实现把 query 里的字符串直接当 gems 用（`cost > gems` 靠 JS 隐式转数字）。
        # js_number 正是 `Number()` 的语义，因此这里数值比较的结果与原来完全一致，
        # 而 md5 仍然用原始字符串。
        errcode, room_id = await roommgr.create_room(
            user_id, room_conf, js_number(gems), server_ip, int(config["CLIENT_PORT"])
        )
        if errcode != 0 or room_id is None:
            return http.send(errcode, "create failed.")
        return http.send(0, "ok", {"roomid": room_id})

    async def on_enter_room(request: web.Request) -> web.Response:
        user_id = http.query_int(request, "userid")
        name = http.query_string(request, "name")
        room_id = http.query_string(request, "roomid")
        sign = http.query_string(request, "sign")
        if user_id is None or room_id is None or sign is None:
            return http.send(1, "invalid parameters")

        digest = crypto.md5(str(user_id) + str(name) + str(room_id) + config["ROOM_PRI_KEY"])
        print(dict(request.query))
        print(digest)
        if digest != sign:
            return http.send(2, "sign check failed.")

        # 安排玩家坐下
        ret = await roommgr.enter_room(room_id, user_id, str(name))
        if ret != 0:
            if ret == 1:
                return http.send(4, "room is full.")
            if ret == 2:
                return http.send(3, "can't find room.")
            return http.send(ret, "enter room failed.")

        token = tokenmgr.create_token(user_id, 5000)
        return http.send(0, "ok", {"token": token})

    async def on_is_room_runing(request: web.Request) -> web.Response:
        room_id = http.query_string(request, "roomid")
        sign = http.query_string(request, "sign")
        if room_id is None or sign is None:
            return http.send(1, "invalid parameters")

        digest = crypto.md5(str(room_id) + config["ROOM_PRI_KEY"])
        if digest != sign:
            return http.send(2, "sign check failed.")

        # 原实现里 `var roomInfo = roomMgr.getRoom(roomId);` 是被注释掉的，
        # 因此这里恒回 runing:true（保持原样）。
        return http.send(0, "ok", {"runing": True})

    app.router.add_get("/get_server_info", on_get_server_info)
    app.router.add_get("/create_room", on_create_room)
    app.router.add_get("/enter_room", on_enter_room)
    app.router.add_get("/is_room_runing", on_is_room_runing)

    _tick_task = asyncio.get_running_loop().create_task(_tick_loop())
    return app


async def _tick_loop() -> None:
    """每秒检查一次是否到了上报时间（对应原实现的 `setInterval(update,1000)`）。"""
    while True:
        await asyncio.sleep(1)
        await _update()


async def _update() -> None:
    """向大厅服定时心跳。"""
    global last_tick_time, server_ip
    config = _require_config()
    if last_tick_time + config["HTTP_TICK_TIME"] < time.time() * 1000:
        last_tick_time = time.time() * 1000
        game_server_info["load"] = roommgr.get_total_rooms()
        result = await http.get(
            str(config["HALL_IP"]), int(config["HALL_PORT"]), "/register_gs", game_server_info
        )
        if result.ok:
            data = result.data
            if data.get("errcode") != 0:
                print(data.get("errmsg"))
            if data.get("ip") is not None:
                # 原来是把响应当中的 ip 原样赋给 serverIp；这里用 str() 收窄，
                # 非字符串的畸形响应也仍然是"有值就用"。
                server_ip = str(data.get("ip"))
        else:
            last_tick_time = 0

        memory = _memory_usage()
        _ = _format_bytes(memory)


def _memory_usage() -> float:
    """当前进程 RSS（字节）。

    原实现读的是 `process.memoryUsage()`；这一行结果只用于（被注释掉的）日志，
    `format` 也一样没有被使用过，这里保留同样的"算了但不用"。
    """
    try:
        import resource

        return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:  # noqa: BLE001
        return 0.0


def _format_bytes(bytes_: float) -> str:
    """原实现里的 `format(bytes)`：`(bytes/1024/1024).toFixed(2) + 'MB'`。"""
    return format(bytes_ / 1024 / 1024, ".2f") + "MB"


def stop_tick() -> None:
    """停掉心跳任务（进程退出时调用）。"""
    global _tick_task
    if _tick_task is not None:
        _tick_task.cancel()
        _tick_task = None

