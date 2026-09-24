"""Windows 配置（唯一配置来源，与 `server/configs_win.ts` 一一对应）。

用法与 mac 版完全相同，只是换成这个文件：

    python -m game_server.app ../configs_win.py

**改端口或密钥时必须同时改 `configs_mac.py` 与本文件**（Node 版同一条约定）。
与 mac 版的两处有意差异（沿用 Node 版）：数据库名是 `db_babykylin`、MySQL 无口令。
"""

from shared.config import (
    AccountServerConfig,
    BanCheckConfig,
    GameServerConfig,
    HallServerConfig,
    MysqlConfig,
)

HALL_IP = "127.0.0.1"
HALL_CLIENT_PORT = 9001
HALL_ROOM_PORT = 9002

ACCOUNT_PRI_KEY = "^&*#$%()@"
ROOM_PRI_KEY = "~!@#$(*&^%$&"

#: 封禁校验：与 `configs_mac.py` 同名同值（两份配置必须同步改），
#: 且 `BAN_CHECK_PRI_KEY` 必须等于 platform_server 的 `PLATFORM_INTERNAL_KEY`。
BAN_CHECK_PRI_KEY = "scmj-ban-check-dev-key"
PLATFORM_IP = "127.0.0.1"
PLATFORM_PORT = 8000

LOCAL_IP = "localhost"


def mysql() -> MysqlConfig:
    return {
        "HOST": "127.0.0.1",
        "USER": "root",
        "PSWD": "",
        "DB": "db_babykylin",
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
        "HTTP_PORT": 9003,
        "HTTP_TICK_TIME": 5000,
        "HALL_IP": LOCAL_IP,
        "FOR_HALL_IP": LOCAL_IP,
        "HALL_PORT": HALL_ROOM_PORT,
        "ROOM_PRI_KEY": ROOM_PRI_KEY,
        "CLIENT_IP": HALL_IP,
        "CLIENT_PORT": 10000,
    }


def ban_check() -> BanCheckConfig:
    """封禁校验配置（与 `configs_mac.py` 同结构，说明见那一份）。"""
    return {
        "ENABLE": True,
        "HOST": PLATFORM_IP,
        "PORT": PLATFORM_PORT,
        "PRI_KEY": BAN_CHECK_PRI_KEY,
        "TIMEOUT_MS": 1000,
        "CACHE_TTL_MS": 30000,
    }

