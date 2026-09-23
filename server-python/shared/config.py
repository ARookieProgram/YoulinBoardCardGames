"""配置文件（configs_mac.py / configs_win.py）的类型契约。

对应 `server/types/config.ts`。配置是**函数式导出**的数据模块，三个进程都通过命令行参数
指定要用哪一份：

    python -m game_server.app ../configs_mac.py

因此模块路径来自命令行，静态分析看不到它的导出，加载动作集中在 `utils/config.py`
的 `load_configs()` 里。这里只描述结构（`TypedDict`）。

注意拼写：`DEALDER_API_IP` / `DEALDER_API_PORT` 与 `CLEINT_PORT` 都是历史拼写错误，
与 Node 版保持一致，不要"顺手修正"。
"""

from typing import TypedDict


class MysqlConfig(TypedDict):
    """MySQL 连接参数（`db.init` 的入参）。"""

    HOST: str
    USER: str
    PSWD: str
    DB: str
    PORT: int


class AccountServerConfig(TypedDict):
    """账号服配置（:9000 客户端、:12581 渠道/代理）。"""

    CLIENT_PORT: int
    HALL_IP: str
    HALL_CLIENT_PORT: int
    ACCOUNT_PRI_KEY: str
    DEALDER_API_IP: str
    DEALDER_API_PORT: int
    VERSION: str
    APP_WEB: str


class HallServerConfig(TypedDict):
    """大厅服配置（:9001 客户端、:9002 游戏服上报）。"""

    HALL_IP: str
    CLEINT_PORT: int
    FOR_ROOM_IP: str
    ROOM_PORT: int
    ACCOUNT_PRI_KEY: str
    ROOM_PRI_KEY: str


class GameServerConfig(TypedDict):
    """游戏服配置（:10000 Socket.IO、:9003 内部 HTTP）。"""

    SERVER_ID: str
    HTTP_PORT: int
    HTTP_TICK_TIME: int
    HALL_IP: str
    FOR_HALL_IP: str
    HALL_PORT: int
    ROOM_PRI_KEY: str
    CLIENT_IP: str
    CLIENT_PORT: int
