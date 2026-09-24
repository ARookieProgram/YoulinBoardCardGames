"""渠道/代理 API（:12581），与账号服同进程（见 account_server/app.py）。

对应 `server/account_server/dealer_api.ts`。

本地 `send_json()` 按账号服的历史约定原样保留（本文件的两个接口实际都走 `http.send`）。

`get_user_data_by_userid` 的 SELECT 列表里没有 headimg 列（见 `utils/db.py`），
原实现读到的 `data.headimg` 恒为 undefined、JSON 序列化时该键**整个消失**。
这里用 `data.get("headimg")` 取，缺键时得到 None，`JSON.stringify` 对应地把键省掉——
但 Python 的 `json.dumps` 会保留值为 `None` 的键，所以下面显式按"有才放"来构造，
以保证返回结构与 Node 版逐字一致。
"""

from __future__ import annotations

from typing import Any

from aiohttp import web

from utils import db, http


def create_routes() -> web.Application:
    """建渠道/代理 API 的 aiohttp 应用。"""
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

    async def on_get_user_info(request: web.Request) -> web.Response:
        userid = http.query_string(request, "userid")
        data = await db.get_user_data_by_userid(userid)
        if data:
            ret: dict[str, Any] = {
                "userid": userid,
                "name": data.get("name"),
                "gems": data.get("gems"),
            }
            # 原实现写的是 data.headimg，而该列不在 SELECT 列表里，运行时是 undefined，
            # JSON.stringify 会丢掉这个键。这里如实复现"有才放"。
            headimg = data.get("headimg", None)
            if headimg is not None:
                ret["headimg"] = headimg
            return http.send(0, "ok", ret)
        return http.send(1, "null")

    async def on_add_user_gems(request: web.Request) -> web.Response:
        userid = http.query_string(request, "userid")
        gems = http.query_string(request, "gems")
        if await db.add_user_gems(userid, gems):
            return http.send(0, "ok")
        return http.send(1, "failed")

    app.router.add_get("/get_user_info", on_get_user_info)
    app.router.add_get("/add_user_gems", on_add_user_gems)
    return app
