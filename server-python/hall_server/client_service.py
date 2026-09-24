"""大厅服客户端 HTTP 接口（:9001）。

对应 `server/hall_server/client_service.ts`。

`check_account()` 里的签名校验**历史上就被注释掉了**，只保留了"account / sign 两个参数
必须存在"的检查（保持原样，不要"顺手补回来"）。

进房签名（`/create_private_room`、`/enter_private_room`）必须与游戏服
`socket_service.py` 的登录校验逐字一致：
`md5(roomid + token + time + ROOM_PRI_KEY)`。

**封禁拦截**：`/login` 与三个建房 / 进房接口在动数据库之前先问一次
`utils.bancheck`（管理平台的内部只读接口）。被拦下时返回
`errcode = ERR_ACCOUNT_BANNED(3)`，客户端 `UserMgr.onLogin` 认这个码并把 `errmsg`
原样提示给玩家。问不到平台时是 fail-open 放行，理由见 `utils/bancheck.py`。
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from hall_server import room_service
from utils import bancheck, crypto, db, http
from utils.jscompat import now_ms

#: 账号被封禁时的业务码（客户端 `UserMgr.onLogin` 认这个码弹提示）。
#: 1 是"参数不全"、2 是历史遗留的 login failed，3 空着，正好给封禁。
ERR_ACCOUNT_BANNED = 3

#: `config` 由 `create_routes()` 在开始监听前赋值，所有请求处理里必然已经就绪。
_config: dict[str, Any] | None = None


def _require_config() -> dict[str, Any]:
    if _config is None:
        raise RuntimeError("client_service.create_routes() 尚未调用")
    return _config


async def check_banned(account: str | None) -> web.Response | None:
    """账号被封禁时返回已经构造好的响应；没被封（或问不到平台）时返回 `None`。

    每个需要拦的接口在"取到 account 之后、查库之前"调它一次即可。

    :param account: 客户端带来的账号。
    """
    status = await bancheck.check_account(account)
    if not status.banned:
        return None
    return http.send(ERR_ACCOUNT_BANNED, bancheck.ban_message(status))


def check_account(request: web.Request) -> web.Response | None:
    """校验 `account` / `sign` 两个 query 参数是否存在。

    签名校验本体历史上已被注释掉（见模块文档），保持原样。

    :return: 参数齐全时 None；否则返回一个已经构造好的错误响应。
    """
    account = request.query.get("account")
    sign = request.query.get("sign")
    if account is None or sign is None:
        return http.send(1, "unknown error")
    # 下面这段在原实现里是被注释掉的：
    #   var serverSign = crypto.md5(account + req.ip + config.ACCOUNT_PRI_KEY);
    #   if(serverSign != sign){ http.send(res,2,"login failed."); return false; }
    return None


def create_routes(config: dict[str, Any]) -> web.Application:
    """建大厅服的客户端服务应用。"""
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

    async def on_login(request: web.Request) -> web.Response:
        failed = check_account(request)
        if failed is not None:
            return failed

        ip = http.request_ip(request)
        if "::ffff:" in ip:
            ip = ip[7:]

        account = http.query_string(request, "account")
        # 封禁拦截：在查库之前问平台，被拦下就到此为止（客户端按 errcode=3 提示）。
        banned = await check_banned(account)
        if banned is not None:
            return banned

        data = await db.get_user_data(account)
        if data is None:
            return http.send(0, "ok")

        # 历史行为：`sex` 不在 get_user_data 的 SELECT 里，老代码直接读 `data.sex`
        # 拿到的是 undefined，`JSON.stringify` 会把这个键整个丢掉。
        # 这里同样"有值才放"，保证返回结构与 Node 版逐字一致。
        ret: dict[str, Any] = {
            "account": data.get("account"),
            "userid": data.get("userid"),
            "name": data.get("name"),
            "lv": data.get("lv"),
            "exp": data.get("exp"),
            "coins": data.get("coins"),
            "gems": data.get("gems"),
            "ip": ip,
        }
        sex = data.get("sex")
        if sex is not None:
            ret["sex"] = sex

        user_id = data.get("userid")
        room_id = await db.get_room_id_of_user(user_id)
        # 如果用户处于房间中，则需要对其房间进行检查。如果房间还在，则通知用户进入
        if room_id is not None:
            if await db.is_room_exist(room_id):
                ret["roomid"] = room_id
            else:
                # 如果房间不在了，表示信息不同步，清除掉用户记录
                await db.set_room_id_of_user(user_id, None)
        return http.send(0, "ok", ret)

    async def on_create_user(request: web.Request) -> web.Response:
        failed = check_account(request)
        if failed is not None:
            return failed
        account = http.query_string(request, "account")
        name = http.query_string(request, "name")
        coins = 1000
        gems = 21
        print(name)

        if not await db.is_user_exist(account):
            result = await db.create_user(account, name, coins, gems, 0, None)
            if result is None:
                return http.send(2, "system error.")
            return http.send(0, "ok")
        return http.send(1, "account have already exist.")

    async def on_create_private_room(request: web.Request) -> web.Response:
        # 保持迁移前的原样：这两个字段会被就地清掉（http.send 之后不回读它们）
        data = request.query
        failed = check_account(request)
        if failed is not None:
            return failed

        account = http.query_string(request, "account")
        conf = data.get("conf")
        _ = data.get("account"), data.get("sign")  # 原实现里的 `data.account = null; data.sign = null;`

        banned = await check_banned(account)
        if banned is not None:
            return banned

        user = await db.get_user_data(account)
        if user is None:
            return http.send(1, "system error")

        user_id = user.get("userid")
        name = user.get("name")
        room_id = await db.get_room_id_of_user(user_id)
        if room_id is not None:
            return http.send(-1, "user is playing in room now.")

        err, room_id = await room_service.create_room(account, user_id, conf)
        if err != 0 or room_id is None:
            return http.send(err, "create failed.")

        errcode, enter_info = await room_service.enter_room(user_id, name, room_id)
        if enter_info is not None:
            ret: dict[str, Any] = {
                "roomid": room_id,
                "ip": enter_info.ip,
                "port": enter_info.port,
                "token": enter_info.token,
                "time": now_ms(),
            }
            ret["sign"] = crypto.md5(
                str(ret["roomid"]) + str(ret["token"]) + str(ret["time"]) + _require_config()["ROOM_PRI_KEY"]
            )
            return http.send(0, "ok", ret)
        return http.send(errcode, "room doesn't exist.")

    async def on_create_single_room(request: web.Request) -> web.Response:
        """单人模式建房：与 `/create_private_room` 相同，但强制带上 `single:1`。

        差别只有两处：

        1. 客户端传来的 conf 里补上 `single:1`，其余选项照用——玩法（血流成河 / 血战到底）、
           底分、番数还是玩家在 CreateRoom 面板里选的那一套；
        2. conf 重新序列化后再交给游戏服。大厅服与游戏服各自算一次 md5，用的必须是
           **同一个字符串**，这里传下去的就是那一个。

        游戏服收到 `single` 后会预置三个机器人、并跳过房卡校验（见 `roommgr.create_room`）。
        """
        failed = check_account(request)
        if failed is not None:
            return failed

        account = http.query_string(request, "account")
        conf_raw = request.query.get("conf")
        if conf_raw is None:
            return http.send(-1, "parameters don't match api requirements.")
        try:
            conf = json.loads(conf_raw)
        except ValueError:
            return http.send(-1, "invalid conf.")
        if not isinstance(conf, dict):
            return http.send(-1, "invalid conf.")
        conf["single"] = 1
        conf_str = json.dumps(conf, separators=(",", ":"))

        # 单人模式也拦：封禁是账号级状态，不该因为"只跟机器人打"就绕过去。
        banned = await check_banned(account)
        if banned is not None:
            return banned

        user = await db.get_user_data(account)
        if user is None:
            return http.send(1, "system error")

        user_id = user.get("userid")
        name = user.get("name")
        room_id = await db.get_room_id_of_user(user_id)
        if room_id is not None:
            return http.send(-1, "user is playing in room now.")

        err, room_id = await room_service.create_room(account, user_id, conf_str)
        if err != 0 or room_id is None:
            return http.send(err, "create failed.")

        errcode, enter_info = await room_service.enter_room(user_id, name, room_id)
        if enter_info is not None:
            ret: dict[str, Any] = {
                "roomid": room_id,
                "ip": enter_info.ip,
                "port": enter_info.port,
                "token": enter_info.token,
                "time": now_ms(),
            }
            ret["sign"] = crypto.md5(
                str(ret["roomid"])
                + str(ret["token"])
                + str(ret["time"])
                + _require_config()["ROOM_PRI_KEY"]
            )
            return http.send(0, "ok", ret)
        return http.send(errcode, "room doesn't exist.")

    async def on_enter_private_room(request: web.Request) -> web.Response:
        room_id = http.query_string(request, "roomid")
        if room_id is None:
            return http.send(-1, "parameters don't match api requirements.")
        failed = check_account(request)
        if failed is not None:
            return failed

        account = request.query.get("account")
        banned = await check_banned(account)
        if banned is not None:
            return banned

        user = await db.get_user_data(account)
        if user is None:
            return http.send(-1, "system error")

        user_id = user.get("userid")
        name = user.get("name")

        # 验证玩家状态
        # todo
        # 进入房间
        errcode, enter_info = await room_service.enter_room(user_id, name, room_id)
        if enter_info is not None:
            ret: dict[str, Any] = {
                "roomid": room_id,
                "ip": enter_info.ip,
                "port": enter_info.port,
                "token": enter_info.token,
                "time": now_ms(),
            }
            ret["sign"] = crypto.md5(
                str(room_id) + str(ret["token"]) + str(ret["time"]) + _require_config()["ROOM_PRI_KEY"]
            )
            return http.send(0, "ok", ret)
        return http.send(errcode, "enter room failed.")

    async def on_get_history_list(request: web.Request) -> web.Response:
        failed = check_account(request)
        if failed is not None:
            return failed
        account = request.query.get("account")
        user = await db.get_user_data(account)
        if user is None:
            return http.send(-1, "system error")
        history = await db.get_user_history(user.get("userid"))
        return http.send(0, "ok", {"history": history})

    async def on_get_games_of_room(request: web.Request) -> web.Response:
        uuid = request.query.get("uuid")
        if uuid is None:
            return http.send(-1, "parameters don't match api requirements.")
        failed = check_account(request)
        if failed is not None:
            return failed
        data = await db.get_games_of_room(uuid)
        print(data)
        return http.send(0, "ok", {"data": data})

    async def on_get_detail_of_game(request: web.Request) -> web.Response:
        uuid = request.query.get("uuid")
        index = request.query.get("index")
        if uuid is None or index is None:
            return http.send(-1, "parameters don't match api requirements.")
        failed = check_account(request)
        if failed is not None:
            return failed
        data = await db.get_detail_of_game(uuid, index)
        return http.send(0, "ok", {"data": data})

    async def on_get_user_status(request: web.Request) -> web.Response:
        failed = check_account(request)
        if failed is not None:
            return failed
        account = http.query_string(request, "account")
        data = await db.get_gems(account)
        if data is not None:
            return http.send(0, "ok", {"gems": data.get("gems")})
        return http.send(1, "get gems failed.")

    async def on_get_message(request: web.Request) -> web.Response:
        failed = check_account(request)
        if failed is not None:
            return failed
        type_ = http.query_string(request, "type")
        if type_ is None:
            return http.send(-1, "parameters don't match api requirements.")
        version = http.query_string(request, "version")
        data = await db.get_message(type_, version)
        if data is not None:
            return http.send(0, "ok", {"msg": data.get("msg"), "version": data.get("version")})
        return http.send(1, "get message failed.")

    app.router.add_get("/login", on_login)
    app.router.add_get("/create_user", on_create_user)
    app.router.add_get("/create_private_room", on_create_private_room)
    app.router.add_get("/create_single_room", on_create_single_room)
    app.router.add_get("/enter_private_room", on_enter_private_room)
    app.router.add_get("/get_history_list", on_get_history_list)
    app.router.add_get("/get_games_of_room", on_get_games_of_room)
    app.router.add_get("/get_detail_of_game", on_get_detail_of_game)
    app.router.add_get("/get_user_status", on_get_user_status)
    app.router.add_get("/get_message", on_get_message)
    return app
