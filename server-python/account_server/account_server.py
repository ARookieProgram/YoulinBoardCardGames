"""账号服 HTTP 服务（:9000）：注册 / 登录 / 游客 / 微信登录 / 头像代理。

对应 `server/account_server/account_server.ts`。

与 Node 版一致，本文件**没有**跟进 `utils/http.py` 的统一出口，
而是保留自己的本地 `send_json()`（返回结构也比大厅服/游戏服随意）。

两处历史 bug 忠实保留（移植不修，要修请单独开一次改动）：

1. `/register` 的判断是反的——`is_user_exist` 为真（账号**已存在**）才去创建；
2. `/auth` 调用了一个本文件从未定义的 `get_md5`，那一分支必然抛 NameError
   （Node 版是 ReferenceError）。
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from utils import crypto, db, http

APP_WEB_DEFAULT = "http://fir.im/2f17"


def send_json(payload: dict[str, Any]) -> web.Response:
    """本地 JSON 出口：账号服的历史约定（不要改成 utils/http 的 `send`）。"""
    return http.json_response(payload)


def _get_md5(content: str) -> str:
    """历史 bug 的忠实保留（见 `/auth` 处理器的说明）。

    原 `account_server.js` 的 `/auth` 分支调用了一个**本文件从未定义**的 `get_md5`，
    因此那一分支必然抛 ReferenceError。移植的目标是行为不变，所以这里不是"补上实现"，
    而是把这个必然抛错的事实写成一个能通过检查的桩：调用点、抛错类型与原实现一致
    （Python 里对应 NameError）。
    """
    raise NameError("name 'get_md5' is not defined")


#: 微信开放平台的应用信息：键是 `/wechat_auth` 的 os 参数（Android / iOS）。
_APP_INFO: dict[str, dict[str, str] | None] = {
    "Android": {
        "appid": "wxe39f08522d35c80d",
        "secret": "fa88e3a3ca5a11b06499902cea4b9c01",
    },
    "iOS": {
        "appid": "wxcb508816c5c4e2a4",
        "secret": "7de38489ede63089269e3410d5905038",
    },
}


def create_routes(config: dict[str, Any], hall_addr: str) -> web.Application:
    """建账号服的 aiohttp 应用。

    :param config: 账号服配置（`configs_*.py` 的 `account_server()`）。
    :param hall_addr: `HALL_IP:HALL_CLIENT_PORT`，`/guest` 与 `/get_serverinfo` 会下发它。
    """
    app = web.Application()

    @web.middleware
    async def cors(request: web.Request, handler: Any) -> web.StreamResponse:
        # 设置跨域访问（与原实现的中间件逐项对应）
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "X-Requested-With"
        response.headers["Access-Control-Allow-Methods"] = "PUT,POST,GET,DELETE,OPTIONS"
        response.headers["X-Powered-By"] = " 3.2.1"
        if "Content-Type" not in response.headers:
            response.headers["Content-Type"] = "application/json;charset=utf-8"
        return response

    app.middlewares.append(cors)

    async def on_register(request: web.Request) -> web.Response:
        account = http.query_string(request, "account")
        password = http.query_string(request, "password")

        def fn_failed() -> web.Response:
            return send_json({"errcode": 1, "errmsg": "account has been used."})

        def fn_succeed() -> web.Response:
            return send_json({"errcode": 0, "errmsg": "ok"})

        # 历史 bug 忠实保留：这里的判断是反的（存在才创建）。
        if await db.is_user_exist(account):
            if await db.create_account(account, password):
                return fn_succeed()
            return fn_failed()
        print("account has been used.")
        return fn_failed()

    async def on_get_version(request: web.Request) -> web.Response:
        return send_json({"version": config["VERSION"]})

    async def on_get_serverinfo(request: web.Request) -> web.Response:
        return send_json(
            {
                "version": config["VERSION"],
                "hall": hall_addr,
                "appweb": config["APP_WEB"],
            }
        )

    async def on_guest(request: web.Request) -> web.Response:
        account = "guest_" + str(http.query_string(request, "account"))
        sign = crypto.md5(account + http.request_ip(request) + config["ACCOUNT_PRI_KEY"])
        return send_json(
            {
                "errcode": 0,
                "errmsg": "ok",
                "account": account,
                "halladdr": hall_addr,
                "sign": sign,
            }
        )

    async def on_auth(request: web.Request) -> web.Response:
        account_in = http.query_string(request, "account")
        password = http.query_string(request, "password")

        info = await db.get_account_info(account_in, password)
        if info is None:
            return send_json({"errcode": 1, "errmsg": "invalid account"})

        account = "vivi_" + str(http.query_string(request, "account"))
        # 历史 bug（移植不修）：原实现调用的是本文件从未定义的 get_md5()。
        # 这行位于 db 的结果之后，抛出的 NameError 会冒泡到 aiohttp（Node 版里
        # 它不在 express 的异常链上，会直接结束账号服进程）。
        # 迁移只把"必然抛错"这个事实写成可读的桩函数，不改行为；要修请单独开一次改动
        # （改用 crypto.md5）。
        sign = _get_md5(account + http.request_ip(request) + config["ACCOUNT_PRI_KEY"])
        return send_json({"errcode": 0, "errmsg": "ok", "account": account, "sign": sign})

    async def get_access_token(code: str, os_name: str) -> http.HttpResult:
        info = _APP_INFO.get(os_name)
        if info is None:
            # 原实现这里**没有 return**：它先回调失败，然后继续往下走并在 info.appid 处
            # 抛异常。净效果是"未知 os 时抛 TypeError"，这里保留同样的取值路径。
            print("unknown os: " + os_name)
        data = {
            "appid": info["appid"],  # type: ignore[index]
            "secret": info["secret"],  # type: ignore[index]
            "code": code,
            "grant_type": "authorization_code",
        }
        return await http.get2("https://api.weixin.qq.com/sns/oauth2/access_token", data, True)

    async def get_state_info(access_token: str, openid: str) -> http.HttpResult:
        data = {"access_token": access_token, "openid": openid}
        return await http.get2("https://api.weixin.qq.com/sns/userinfo", data, True)

    async def create_user(account: str, name: str, sex: int, headimgurl: str) -> None:
        coins = 1000
        gems = 21
        if not await db.is_user_exist(account):
            await db.create_user(account, name, coins, gems, sex, headimgurl)
        else:
            await db.update_user_info(account, name, headimgurl, sex)

    async def on_wechat_auth(request: web.Request) -> web.Response:
        code = http.query_string(request, "code")
        os_name = http.query_string(request, "os")
        if code is None or code == "" or os_name is None or os_name == "":
            return web.Response(text="")
        print(os_name)

        result = await get_access_token(code, os_name)
        if result.ok:
            access_token = result.data.get("access_token")
            openid = result.data.get("openid")
            result2 = await get_state_info(str(access_token), str(openid))
            if result2.ok:
                openid = result2.data.get("openid")
                nickname = result2.data.get("nickname")
                sex = result2.data.get("sex")
                headimgurl = result2.data.get("headimgurl")
                account = "wx_" + str(openid)
                await create_user(account, str(nickname), int(sex), str(headimgurl))
                sign = crypto.md5(account + http.request_ip(request) + config["ACCOUNT_PRI_KEY"])
                return send_json(
                    {
                        "errcode": 0,
                        "errmsg": "ok",
                        "account": account,
                        "halladdr": hall_addr,
                        "sign": sign,
                    }
                )
            return web.Response(text="")
        return send_json({"errcode": -1, "errmsg": "unkown err."})

    async def on_base_info(request: web.Request) -> web.Response:
        userid = http.query_string(request, "userid")
        data = await db.get_user_base_info(userid)
        # 原实现不做空判断：userid 缺失时 db 会回调 null，这里同样在取字段时抛
        # TypeError（行为不变）。
        return send_json(
            {
                "errcode": 0,
                "errmsg": "ok",
                "name": data["name"],  # type: ignore[index]
                "sex": data["sex"],  # type: ignore[index]
                "headimgurl": data["headimg"],  # type: ignore[index]
            }
        )

    async def on_image(request: web.Request) -> web.Response:
        url = http.query_string(request, "url")
        if not url:
            return http.send(1, "invalid url", {})
        if not url.startswith("http://") and not url.startswith("https://"):
            return http.send(1, "invalid url", {})

        url = url.split(".jpg")[0]

        # 原实现据此决定用 http 还是 https；aiohttp 直接从 URL 的 scheme 选协议，
        # 这里保留这行是为了让取值路径与 Node 版读起来一致。
        _safe = url.startswith("https://")
        print(url)
        # 代理拉取远程图片：拿到原始字节后再回写响应。
        content_type, data = await http.get_bytes(url)
        if not content_type or not data:
            # 原实现传的是 `true`：迁移前的 http.js 是非严格模式，给 boolean 挂
            # errcode/errmsg 只是静默失效，响应体因此是 JSON.stringify(true) == "true"。
            # 这里直接写出原来的响应体：对外行为逐字不变。
            return web.Response(text=json.dumps(True), content_type="application/json", charset="utf-8")
        return web.Response(body=data, content_type=content_type)

    app.router.add_get("/register", on_register)
    app.router.add_get("/get_version", on_get_version)
    app.router.add_get("/get_serverinfo", on_get_serverinfo)
    app.router.add_get("/guest", on_guest)
    app.router.add_get("/auth", on_auth)
    app.router.add_get("/wechat_auth", on_wechat_auth)
    app.router.add_get("/base_info", on_base_info)
    app.router.add_get("/image", on_image)
    return app
