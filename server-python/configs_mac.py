"""macOS 开发机配置（唯一配置来源，与 `server/configs_mac.ts` 一一对应）。

三个进程都用命令行参数指定配置文件：

    python -m game_server.app ../configs_mac.py

`utils/config.py` 的 `load_configs()` 按**入口模块所在目录**解析相对路径，
因此 `../configs_mac.py` 指向 `server-python/configs_mac.py`，
与 Node 版 `dist/<进程>/app.js ../configs_mac.js` 的相对语义完全一致。

`mysql()` 与本文件里的口令只为本地开发；连接失败时先检查这里。
"""

from shared.config import (
    AccountServerConfig,
    GameServerConfig,
    HallServerConfig,
    MysqlConfig,
)

HALL_IP = "127.0.0.1"  # 如果非本机访问，这里要变
HALL_CLIENT_PORT = 9001
HALL_ROOM_PORT = 9002

ACCOUNT_PRI_KEY = "^&*#$%()@"
ROOM_PRI_KEY = "~!@#$(*&^%$&"

LOCAL_IP = "localhost"


def mysql() -> MysqlConfig:
    return {
        "HOST": "127.0.0.1",
        "USER": "root",
        "PSWD": "li663399",  # 如果连接失败，请检查这里
        "DB": "db_scmj",  # 如果连接失败，请检查这里
        "PORT": 3306,
    }


def account_server() -> AccountServerConfig:
    """账号服配置。"""
    return {
        "CLIENT_PORT": 9000,
        "HALL_IP": HALL_IP,
        "HALL_CLIENT_PORT": HALL_CLIENT_PORT,
        "ACCOUNT_PRI_KEY": ACCOUNT_PRI_KEY,
        #
        "DEALDER_API_IP": LOCAL_IP,
        "DEALDER_API_PORT": 12581,
        "VERSION": "20161227",
        "APP_WEB": "http://fir.im/2f17",
    }


def hall_server() -> HallServerConfig:
    """大厅服配置。"""
    return {
        "HALL_IP": HALL_IP,
        "CLEINT_PORT": HALL_CLIENT_PORT,
        "FOR_ROOM_IP": LOCAL_IP,
        "ROOM_PORT": HALL_ROOM_PORT,
        "ACCOUNT_PRI_KEY": ACCOUNT_PRI_KEY,
        "ROOM_PRI_KEY": ROOM_PRI_KEY,
    }


def game_server() -> GameServerConfig:
    """游戏服配置。"""
    return {
        "SERVER_ID": "001",
        # 暴露给大厅服的HTTP端口号
        "HTTP_PORT": 9003,
        # HTTP TICK的间隔时间，用于向大厅服汇报情况
        "HTTP_TICK_TIME": 5000,
        # 大厅服IP
        "HALL_IP": LOCAL_IP,
        "FOR_HALL_IP": LOCAL_IP,
        # 大厅服端口
        "HALL_PORT": HALL_ROOM_PORT,
        # 与大厅服协商好的通信加密KEY
        "ROOM_PRI_KEY": ROOM_PRI_KEY,
        # 暴露给客户端的接口
        "CLIENT_IP": HALL_IP,
        "CLIENT_PORT": 10000,
    }
