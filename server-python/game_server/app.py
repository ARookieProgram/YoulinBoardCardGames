"""游戏服进程入口：客户端 Socket.IO（:10000）+ 内部 HTTP（:9003）。

对应 `server/game_server/app.ts`。

用法：

    cd server-python
    .venv/bin/python -m game_server.app ../configs_mac.py

注意：本进程的 Socket.IO 服务**不是** socket.io 官方库，而是
`game_server/sio_server.py` 里自己实现的 Engine.IO 3 / Socket.IO 4 协议层
（原因见该模块的文档注释：官方 Python 库要么拒绝 EIO=3，要么在 Python 3.14 上跑不起来）。
"""

from __future__ import annotations

import os
import sys

from aiohttp import web

from game_server import http_service, socket_service
from utils import bancheck, db, http, startup
from utils.config import config_function, load_configs
from utils.startup import Endpoint

TITLE = "游戏服 (game_server)"


async def main() -> None:
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    configs = load_configs(config_file, os.path.dirname(os.path.abspath(__file__)))

    config = config_function(configs, "game_server")()
    mysql_conf = config_function(configs, "mysql")()
    # 封禁校验（socket 登录 / 进房前问管理平台）。配置见 configs_*.py 的 ban_check()。
    bancheck.init(config_function(configs, "ban_check")())

    await db.init(mysql_conf)

    # 内部 HTTP（供大厅服调用，需签名）
    internal_app = http_service.create_routes(config)

    # 对局协议：socket.io 挂在同一个 aiohttp 应用上，外加原实现里的 catch-all 路由
    global _sio
    socket_app = web.Application()
    sio = socket_service.create_server(config)
    _sio = sio
    sio.attach(socket_app)
    socket_app.router.add_route("*", "/{tail:.*}", socket_service.on_http_request)

    socket_endpoint = Endpoint(
        label="客户端 Socket.IO",
        scheme="http",
        host=str(config["CLIENT_IP"]),
        port=int(config["CLIENT_PORT"]),
        actual_port=int(config["CLIENT_PORT"]),
        note="对局协议",
    )
    http_endpoint = Endpoint(
        label="内部 HTTP",
        scheme="http",
        host=str(config["FOR_HALL_IP"]),
        port=int(config["HTTP_PORT"]),
        actual_port=int(config["HTTP_PORT"]),
        note="供大厅服调用，需签名",
    )

    runners = []
    # 原实现 httpServer.listen(CLIENT_PORT) 不指定 host = 绑全部网卡
    runners.append(
        await startup.listen_or_fail(
            socket_app, None, int(config["CLIENT_PORT"]), socket_endpoint, config_file, TITLE
        )
    )
    runners.append(
        await startup.listen_or_fail(
            internal_app, str(config["FOR_HALL_IP"]), int(config["HTTP_PORT"]), http_endpoint, config_file, TITLE
        )
    )

    http.init_session()
    await sio.start()
    await startup.report(
        title=TITLE,
        config_file=config_file,
        note="游戏服已就绪，按 Ctrl+C 停止服务。",
        endpoints=[socket_endpoint, http_endpoint],
        db_module=db,
        db_label=str(mysql_conf["DB"]) + "@" + str(mysql_conf["HOST"]) + ":" + str(mysql_conf["PORT"]),
    )

    await startup.wait_for_shutdown(runners)


#: 进程退出时要关掉的 Socket.IO 服务（`main()` 里赋值）。
_sio: object | None = None


async def _cleanup() -> None:
    """收尾：停心跳、断开所有对局连接。"""
    http_service.stop_tick()
    if _sio is not None:
        await _sio.close()  # type: ignore[attr-defined]


if __name__ == "__main__":
    startup.run(main(), cleanup=[_cleanup, db.close, http.close_session])
