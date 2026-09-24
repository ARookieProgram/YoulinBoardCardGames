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
    BanCheckConfig,
    GameServerConfig,
    HallServerConfig,
    MysqlConfig,
)

HALL_IP = "127.0.0.1"  # 如果非本机访问，这里要变
HALL_CLIENT_PORT = 9001
HALL_ROOM_PORT = 9002

ACCOUNT_PRI_KEY = "^&*#$%()@"
ROOM_PRI_KEY = "~!@#$(*&^%$&"

#: 封禁校验的共享密钥。**必须与 platform_server 的 PLATFORM_INTERNAL_KEY 一致**：
#: 不一致时游戏服是 fail-open（照常放行）并打警告日志，表现为"封禁静默失效"。
#: 生产必须换成随机长串，并同时更新平台侧的环境变量。
BAN_CHECK_PRI_KEY = "scmj-ban-check-dev-key"

#: 管理平台（platform_server）的地址——封禁校验就打在它身上。
PLATFORM_IP = "127.0.0.1"
PLATFORM_PORT = 8000

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


def ban_check() -> BanCheckConfig:
    """封禁校验配置（大厅服与游戏服都用它）。

    游戏服在登录 / 进房前调管理平台的内部只读接口
    `GET /api/internal/players/ban-check/`，问这个玩家有没有被封：

    * `PRI_KEY` 与 platform_server 的 `PLATFORM_INTERNAL_KEY` 必须逐字一致；
    * 超时 / 连不上 / 平台报错一律 **fail-open 放行**并打警告日志——
      管理后台挂掉不该让全体玩家登不上游戏；
    * `CACHE_TTL_MS` 决定"后台点了封禁"到"玩家被拦下"的最大延迟。

    平台没部署时把 `ENABLE` 设为 False，连 HTTP 请求都不会发。
    """
    return {
        "ENABLE": True,
        "HOST": PLATFORM_IP,
        "PORT": PLATFORM_PORT,
        "PRI_KEY": BAN_CHECK_PRI_KEY,
        "TIMEOUT_MS": 1000,
        "CACHE_TTL_MS": 30000,
    }

