"""对局协议的唯一入口：所有客户端事件处理器都在这里。

对应 `server/game_server/socket_service.ts`。

登录链路（见 `server/AGENTS.md` §3）：
客户端拿大厅服给的一次性 token 连上来，`login` 里校验
`md5(roomid + token + time + ROOM_PRI_KEY)` 与 token 时效，然后登记连接、取房间与座位，
把 `socket.gameMgr` 指向该房间的玩法实现；之后所有业务动作都走 `socket.gameMgr.xxx(...)`。

推送：对局内一律走 `usermgr`；只有登录/连接阶段的几处直接 `socket.emit` 是例外
（`login_result`×4、`login_finished`、`exit_result`、`game_pong`）。

与 Node 版的差异：

* 事件处理器是**协程**，`socket.on` 注册的就是 `async def`；
* `gameMgr` 上的方法全部要 `await`（见 `shared/domain.py` 的 `GameManagerProtocol`）；
* 原实现里 `socket.emit('login_finished')`（不带载荷）与
  `sendMsg(uid, ev, undefined)`（带 null）在线上是不同的包，这里用 `NO_DATA` 保留这个区别。
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from game_server import roommgr, tokenmgr, usermgr
from game_server.sio_server import Socket, SocketIOServer
from utils import crypto, http
from utils.jscompat import js_parse_int, now_ms

_config: dict[str, Any] | None = None
_sio: SocketIOServer | None = None


def _require_config() -> dict[str, Any]:
    if _config is None:
        raise RuntimeError("socket_service.create_server() 尚未调用")
    return _config


def create_server(config: dict[str, Any]) -> SocketIOServer:
    """建对局用的 Socket.IO 服务（Engine.IO 3 / Socket.IO 4）。"""
    global _config, _sio
    _config = config

    server = SocketIOServer()
    _sio = server

    @server.on("connection")
    async def on_connection(socket: Socket) -> None:
        await _register_handlers(socket)

    return server


async def _register_handlers(socket: Socket) -> None:
    """给一条新连接注册全部客户端事件处理器。"""

    async def on_login(data: Any) -> None:
        login_data = json.loads(data)
        if socket.userId is not None:
            # 已经登陆过的就忽略
            return
        token = login_data.get("token")
        login_room_id = login_data.get("roomid")
        time = login_data.get("time")
        sign = login_data.get("sign")

        print(login_room_id)
        print(token)
        print(time)
        print(sign)

        # 检查参数合法性
        if token is None or login_room_id is None or sign is None or time is None:
            print(1)
            await socket.emit("login_result", {"errcode": 1, "errmsg": "invalid parameters"})
            return

        # 检查参数是否被篡改
        digest = crypto.md5(
            str(login_room_id) + str(token) + str(time) + _require_config()["ROOM_PRI_KEY"]
        )
        if digest != sign:
            print(2)
            await socket.emit("login_result", {"errcode": 2, "errmsg": "login failed. invalid sign!"})
            return

        # 检查token是否有效
        if tokenmgr.is_token_valid(token) is False:
            print(3)
            await socket.emit("login_result", {"errcode": 3, "errmsg": "token out of time."})
            return

        # 检查房间合法性
        user_id = tokenmgr.get_user_id(token)
        room_id = roommgr.get_user_room(user_id)

        usermgr.bind(user_id, socket)
        socket.userId = user_id

        # 返回房间信息
        # 说明：原实现同样不判空（roomId 或座位为空时这里会抛 TypeError），
        # 这里保持同样的取值路径，不加保护；要加请单独开一次改动。
        room_info = roommgr.get_room(room_id)  # type: ignore[arg-type]

        seat_index = roommgr.get_user_seat(user_id)
        room_info.seats[seat_index].ip = socket.address  # type: ignore[index]

        user_data: dict[str, Any] | None = None
        seats: list[dict[str, Any]] = []
        for i in range(len(room_info.seats)):
            rs = room_info.seats[i]
            online = False
            if rs.userId > 0:
                online = usermgr.is_online(rs.userId)

            seats.append(
                {
                    "userid": rs.userId,
                    "ip": rs.ip,
                    "score": rs.score,
                    "name": rs.name,
                    "online": online,
                    "ready": rs.ready,
                    "seatindex": i,
                }
            )

            if user_id == rs.userId:
                user_data = seats[i]

        # 通知前端
        ret = {
            "errcode": 0,
            "errmsg": "ok",
            "data": {
                "roomid": room_info.id,
                "conf": _conf_to_wire(room_info.conf),
                "numofgames": room_info.numOfGames,
                "seats": seats,
            },
        }
        await socket.emit("login_result", ret)

        # 通知其它客户端
        await usermgr.broacast_in_room("new_user_comes_push", user_data, user_id)

        socket.gameMgr = room_info.gameMgr

        # 玩家上线，强制设置为TRUE
        await socket.gameMgr.set_ready(user_id)

        await socket.emit("login_finished")

        if room_info.dr is not None:
            dr = room_info.dr
            ramaing_time = (dr.endTime - now_ms()) / 1000
            notice_data = {
                "time": ramaing_time,
                "states": dr.states,
            }
            await usermgr.send_msg(user_id, "dissolve_notice_push", notice_data)

    async def on_ready(data: Any) -> None:
        user_id = socket.userId
        if user_id is None:
            return
        await socket.gameMgr.set_ready(user_id)
        await usermgr.broacast_in_room("user_ready_push", {"userid": user_id, "ready": True}, user_id, True)

    # 换牌
    async def on_huanpai(data: Any) -> None:
        if socket.userId is None:
            return
        if data is None:
            return

        huanpai = json.loads(data) if isinstance(data, str) else data

        p1 = huanpai.get("p1")
        p2 = huanpai.get("p2")
        p3 = huanpai.get("p3")
        if p1 is None or p2 is None or p3 is None:
            print("invalid data")
            return
        await socket.gameMgr.huan_san_zhang(socket.userId, p1, p2, p3)

    # 定缺
    async def on_dingque(data: Any) -> None:
        if socket.userId is None:
            return
        que = data
        await socket.gameMgr.ding_que(socket.userId, que)

    # 出牌
    async def on_chupai(data: Any) -> None:
        if socket.userId is None:
            return
        pai = data
        await socket.gameMgr.chu_pai(socket.userId, pai)

    # 碰
    async def on_peng(data: Any) -> None:
        if socket.userId is None:
            return
        await socket.gameMgr.peng(socket.userId)

    # 杠
    async def on_gang(data: Any) -> None:
        if socket.userId is None or data is None:
            return
        pai = -1
        if isinstance(data, bool):
            print("gang:invalid param")
            return
        if isinstance(data, (int, float)):
            pai = int(data)
        elif isinstance(data, str):
            pai = int(js_parse_int(data))
        else:
            print("gang:invalid param")
            return
        await socket.gameMgr.gang(socket.userId, pai)

    # 胡
    async def on_hu(data: Any) -> None:
        if socket.userId is None:
            return
        await socket.gameMgr.hu(socket.userId)

    # 过  遇上胡，碰，杠的时候，可以选择过
    async def on_guo(data: Any) -> None:
        if socket.userId is None:
            return
        await socket.gameMgr.guo(socket.userId)

    # 聊天
    async def on_chat(data: Any) -> None:
        if socket.userId is None:
            return
        chat_content = data
        await usermgr.broacast_in_room(
            "chat_push", {"sender": socket.userId, "content": chat_content}, socket.userId, True
        )

    # 快速聊天
    async def on_quick_chat(data: Any) -> None:
        if socket.userId is None:
            return
        chat_id = data
        await usermgr.broacast_in_room(
            "quick_chat_push", {"sender": socket.userId, "content": chat_id}, socket.userId, True
        )

    # 语音聊天
    async def on_voice_msg(data: Any) -> None:
        if socket.userId is None:
            return
        print(len(data))
        await usermgr.broacast_in_room(
            "voice_msg_push", {"sender": socket.userId, "content": data}, socket.userId, True
        )

    # 表情
    async def on_emoji(data: Any) -> None:
        if socket.userId is None:
            return
        phiz_id = data
        await usermgr.broacast_in_room(
            "emoji_push", {"sender": socket.userId, "content": phiz_id}, socket.userId, True
        )

    # 语音使用SDK不出现在这里

    # 退出房间
    async def on_exit(data: Any) -> None:
        user_id = socket.userId
        if user_id is None:
            return

        room_id = roommgr.get_user_room(user_id)
        if room_id is None:
            return

        # 如果游戏已经开始，则不可以
        if socket.gameMgr.has_began(room_id):
            return

        # 如果是房主，则只能走解散房间
        # 说明：这里历史上只传了一个参数（传进去的其实是 userId），
        # roommgr.is_creator 因此取不到房间、恒返回 false——保留该行为。
        if roommgr.is_creator(user_id):
            return

        # 通知其它玩家，有人退出了房间
        await usermgr.broacast_in_room("exit_notify_push", user_id, user_id, False)

        await roommgr.exit_room(user_id)
        usermgr.delete(user_id)

        await socket.emit("exit_result")
        await socket.disconnect()

    # 解散房间
    async def on_dispress(data: Any) -> None:
        user_id = socket.userId
        if user_id is None:
            return

        room_id = roommgr.get_user_room(user_id)
        if room_id is None:
            return

        # 如果游戏已经开始，则不可以
        if socket.gameMgr.has_began(room_id):
            return

        # 如果不是房主，则不能解散房间
        if roommgr.is_creator(room_id, user_id) is False:
            return

        await usermgr.broacast_in_room("dispress_push", {}, user_id, True)
        await usermgr.kick_all_in_room(room_id)
        await roommgr.destroy(room_id)
        await socket.disconnect()

    # 解散房间
    async def on_dissolve_request(data: Any) -> None:
        user_id = socket.userId
        print(1)
        if user_id is None:
            print(2)
            return

        room_id = roommgr.get_user_room(user_id)
        if room_id is None:
            print(3)
            return

        # 如果游戏未开始，则不可以
        if socket.gameMgr.has_began(room_id) is False:
            print(4)
            return

        ret = socket.gameMgr.dissolve_request(room_id, user_id)
        if ret is not None:
            dr = ret.dr
            ramaing_time = (dr.endTime - now_ms()) / 1000
            notice_data = {
                "time": ramaing_time,
                "states": dr.states,
            }
            print(5)
            await usermgr.broacast_in_room("dissolve_notice_push", notice_data, user_id, True)
        print(6)

    async def on_dissolve_agree(data: Any) -> None:
        user_id = socket.userId

        if user_id is None:
            return

        room_id = roommgr.get_user_room(user_id)
        if room_id is None:
            return

        ret = socket.gameMgr.dissolve_agree(room_id, user_id, True)
        if ret is not None:
            dr = ret.dr
            ramaing_time = (dr.endTime - now_ms()) / 1000
            notice_data = {
                "time": ramaing_time,
                "states": dr.states,
            }
            await usermgr.broacast_in_room("dissolve_notice_push", notice_data, user_id, True)

            do_all_agree = True
            for i in range(len(dr.states)):
                if dr.states[i] is False:
                    do_all_agree = False
                    break

            if do_all_agree:
                await socket.gameMgr.do_dissolve(room_id)

    async def on_dissolve_reject(data: Any) -> None:
        user_id = socket.userId

        if user_id is None:
            return

        room_id = roommgr.get_user_room(user_id)
        if room_id is None:
            return

        ret = socket.gameMgr.dissolve_agree(room_id, user_id, False)
        if ret is not None:
            await usermgr.broacast_in_room("dissolve_cancel_push", {}, user_id, True)

    # 断开链接
    async def on_disconnect(reason: str) -> None:
        user_id = socket.userId
        if not user_id:
            return

        # 如果是旧链接断开，则不需要处理。
        if usermgr.get(user_id) is not socket:
            return

        data = {
            "userid": user_id,
            "online": False,
        }

        # 通知房间内其它玩家
        await usermgr.broacast_in_room("user_state_push", data, user_id)

        # 清除玩家的在线信息
        usermgr.delete(user_id)
        socket.userId = None

    async def on_game_ping(data: Any) -> None:
        user_id = socket.userId
        if not user_id:
            return
        await socket.emit("game_pong")

    socket.on("login", on_login)
    socket.on("ready", on_ready)
    socket.on("huanpai", on_huanpai)
    socket.on("dingque", on_dingque)
    socket.on("chupai", on_chupai)
    socket.on("peng", on_peng)
    socket.on("gang", on_gang)
    socket.on("hu", on_hu)
    socket.on("guo", on_guo)
    socket.on("chat", on_chat)
    socket.on("quick_chat", on_quick_chat)
    socket.on("voice_msg", on_voice_msg)
    socket.on("emoji", on_emoji)
    socket.on("exit", on_exit)
    socket.on("dispress", on_dispress)
    socket.on("dissolve_request", on_dissolve_request)
    socket.on("dissolve_agree", on_dissolve_agree)
    socket.on("dissolve_reject", on_dissolve_reject)
    socket.on("disconnect", on_disconnect)
    socket.on("game_ping", on_game_ping)


async def on_http_request(request: web.Request) -> web.Response:
    """非 socket.io 的 HTTP 请求一律回 `ok`（对应原游戏服上那个 catch-all express 路由）。"""
    return http.send(0, "ok", {})


def _conf_to_wire(conf: Any) -> dict[str, Any]:
    """`login_result` 里下发的 `conf`，键集与 Node 版 `JSON.stringify(roomInfo.conf)` 一致。"""
    return {
        "type": conf.type,
        "baseScore": conf.baseScore,
        "zimo": conf.zimo,
        "jiangdui": conf.jiangdui,
        "hsz": conf.hsz,
        "dianganghua": conf.dianganghua,
        "menqing": conf.menqing,
        "tiandihu": conf.tiandihu,
        "maxFan": conf.maxFan,
        "maxGames": conf.maxGames,
        "creator": conf.creator,
    }
