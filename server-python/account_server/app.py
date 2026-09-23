"""账号服进程入口：账号服（:9000）+ 渠道/代理 API（:12581）。

对应 `server/account_server/app.ts`。

用法：

    cd server-python
    .venv/bin/python -m account_server.app ../configs_mac.py

与 Node 版一致：**先初始化数据库连接池，再建两个 HTTP 服务**，
最后由 `utils/startup.py` 汇总成一块启动横幅（两个端口都真的 listening 才算就绪）。
"""

from __future__ import annotations

import os
import sys

from account_server import account_server, dealer_api
from utils import db, http, startup
from utils.config import config_function, load_configs
from utils.startup import Endpoint

TITLE = "账号服 (account_server)"


async def main() -> None:
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    configs = load_configs(config_file, os.path.dirname(os.path.abspath(__file__)))

    mysql_conf = config_function(configs, "mysql")()
    await db.init(mysql_conf)

    config = config_function(configs, "account_server")()
    hall_addr = str(config["HALL_IP"]) + ":" + str(config["HALL_CLIENT_PORT"])

    client_app = account_server.create_routes(config, hall_addr)
    dealer_app = dealer_api.create_routes()

    # 账号服的客户端端口在原实现里是 app.listen(port)（不指定 host = 绑全部网卡）；
    # 渠道 API 是 app.listen(port, DEALDER_API_IP)。这里保持同样的绑定范围。
    client_endpoint = Endpoint(
        label="客户端 HTTP",
        scheme="http",
        host=str(config["HALL_IP"]),
        port=int(config["CLIENT_PORT"]),
        actual_port=int(config["CLIENT_PORT"]),
        note="/guest /register /auth",
    )
    dealer_endpoint = Endpoint(
        label="渠道/代理 API",
        scheme="http",
        host=str(config["DEALDER_API_IP"]),
        port=int(config["DEALDER_API_PORT"]),
        actual_port=int(config["DEALDER_API_PORT"]),
    )

    runners = []
    runner = await startup.listen_or_fail(
        client_app, None, int(config["CLIENT_PORT"]), client_endpoint, config_file, TITLE
    )
    runners.append(runner)

    runner = await startup.listen_or_fail(
        dealer_app,
        str(config["DEALDER_API_IP"]),
        int(config["DEALDER_API_PORT"]),
        dealer_endpoint,
        config_file,
        TITLE,
    )
    runners.append(runner)

    http.init_session()
    await startup.report(
        title=TITLE,
        config_file=config_file,
        note="账号服已就绪，按 Ctrl+C 停止服务。",
        endpoints=[client_endpoint, dealer_endpoint],
        db_module=db,
        db_label=str(mysql_conf["DB"]) + "@" + str(mysql_conf["HOST"]) + ":" + str(mysql_conf["PORT"]),
    )

    await startup.wait_for_shutdown(runners)


if __name__ == "__main__":
    startup.run(main(), cleanup=[db.close, http.close_session])
