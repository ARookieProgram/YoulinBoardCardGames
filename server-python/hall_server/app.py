"""大厅服进程入口：客户端 HTTP（:9001）+ 游戏服上报（:9002）。

对应 `server/hall_server/app.ts`。

用法：

    cd server-python
    .venv/bin/python -m hall_server.app ../configs_mac.py
"""

from __future__ import annotations

import os
import sys

from hall_server import client_service, room_service
from utils import bancheck, db, http, startup
from utils.config import config_function, load_configs
from utils.startup import Endpoint

TITLE = "大厅服 (hall_server)"


async def main() -> None:
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    configs = load_configs(config_file, os.path.dirname(os.path.abspath(__file__)))

    config = config_function(configs, "hall_server")()
    mysql_conf = config_function(configs, "mysql")()
    # 封禁校验（登录 / 建房 / 进房前问管理平台）。配置见 configs_*.py 的 ban_check()。
    bancheck.init(config_function(configs, "ban_check")())

    await db.init(mysql_conf)

    client_app = client_service.create_routes(config)
    room_app = room_service.create_routes(config)

    client_endpoint = Endpoint(
        label="客户端 HTTP",
        scheme="http",
        host=str(config["HALL_IP"]),
        port=int(config["CLEINT_PORT"]),
        actual_port=int(config["CLEINT_PORT"]),
        note="/login /enter_private_room",
    )
    room_endpoint = Endpoint(
        label="游戏服上报 HTTP",
        scheme="http",
        host=str(config["FOR_ROOM_IP"]),
        port=int(config["ROOM_PORT"]),
        actual_port=int(config["ROOM_PORT"]),
        note="/register_gs",
    )

    runners = []
    runners.append(
        await startup.listen_or_fail(client_app, None, int(config["CLEINT_PORT"]), client_endpoint, config_file, TITLE)
    )
    runners.append(
        await startup.listen_or_fail(
            room_app, str(config["FOR_ROOM_IP"]), int(config["ROOM_PORT"]), room_endpoint, config_file, TITLE
        )
    )

    http.init_session()
    await startup.report(
        title=TITLE,
        config_file=config_file,
        note="大厅服已就绪，按 Ctrl+C 停止服务。",
        endpoints=[client_endpoint, room_endpoint],
        db_module=db,
        db_label=str(mysql_conf["DB"]) + "@" + str(mysql_conf["HOST"]) + ":" + str(mysql_conf["PORT"]),
    )

    await startup.wait_for_shutdown(runners)


if __name__ == "__main__":
    startup.run(main(), cleanup=[db.close, http.close_session])
