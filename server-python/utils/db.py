"""SQL 访问层：本仓库**唯一**允许拼 SQL 的地方。

对应 `server/utils/db.ts`。行结构契约在 `shared/db_rows.py`。

与 Node 版的两处有意差异（都是为了 asyncio，不改业务语义）：

1. **异步**：`aiomysql` 是 await 的，所以这里的函数是 `async def`，
   直接 `return` 结果，而不是 Node 版的 `(args..., callback)`。
   调用方从"传回调"改成"await"，逻辑顺序完全一致。
2. **错误不再杀死进程**：Node 版在回调里 `throw err`，而 mysql2 的回调不在
   express 的异常链上，结果是**整个进程退出**。Python 版改为记录日志并把异常抛给
   调用方（aiohttp 会变成 500、socket 处理器会被记下来），进程继续服务。
   这是刻意的健壮性改进，语义上"这次操作失败了"这一点没有变。

其余行为逐字保留，包括几个**历史 bug**（都在各自的函数注释里标出，不要顺手修）：

* `get_account_info` 在口令**正确**时返回 `None`；
* `cost_gems` / `set_room_id_of_user` 的回调恒为 `False`；
* `update_user_history` 的回调恒为 `True`；
* `update_game_result` / `delete_room` / `delete_games` 在参数为 null 时先回调一次
  再继续执行 SQL。
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

import aiomysql
import pymysql.err

from shared.config import MysqlConfig
from shared.db_rows import (
    AccountRow,
    GameRow,
    MessageRow,
    RoomAddrRow,
    RoomRow,
    UserBaseInfoRow,
    UserBriefRow,
    UserRow,
)

from . import crypto

# 行结构契约在 shared/db_rows.py；这里再导出一次，调用方从 db 或 shared.db_rows 引入都行。
__all__ = [
    "AccountRow",
    "DbError",
    "GameRow",
    "MessageRow",
    "QueryResult",
    "RoomAddrRow",
    "RoomRow",
    "UserBaseInfoRow",
    "UserBriefRow",
    "UserRow",
    "account_rows",
    "add_user_gems",
    "archive_games",
    "close",
    "cost_gems",
    "create_account",
    "create_game",
    "create_room",
    "create_user",
    "delete_games",
    "delete_room",
    "get_account_info",
    "get_detail_of_game",
    "get_games_of_room",
    "get_gems",
    "get_message",
    "get_room_addr",
    "get_room_data",
    "get_room_id_of_user",
    "get_room_uuid",
    "get_user_base_info",
    "get_user_data",
    "get_user_data_by_userid",
    "get_user_history",
    "init",
    "is_account_exist",
    "is_room_exist",
    "is_user_exist",
    "ping",
    "query",
    "set_room_id_of_user",
    "update_game_action_records",
    "update_game_result",
    "update_next_button",
    "update_num_of_turns",
    "update_seat_info",
    "update_user_history",
    "update_user_info",
]

#: MySQL 的 ER_DUP_ENTRY，Node 版用 `err.code == 'ER_DUP_ENTRY'` 判断。
ER_DUP_ENTRY = 1062

#: MySQL errno -> 名字，只列本仓库会判别的那些（Node 版拿到的就是这些字符串）。
_ERR_NAMES = {ER_DUP_ENTRY: "ER_DUP_ENTRY"}


class DbError(Exception):
    """数据库错误（对应 Node 版的 `DbError`，带 `code` 字段）。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class QueryResult:
    """一次查询的结果。

    `rows` 是 SELECT 的行（`dict` 列表），写操作时为空。
    `rowcount` 对应 mysql2 的 `affectedRows`，`insert_id` 对应 `insertId`。
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    rowcount: int = 0
    insert_id: int = 0


_pool: aiomysql.Pool | None = None


async def init(config: MysqlConfig) -> None:
    """创建连接池。进程启动时必须先调用它（与原实现一致）。"""
    global _pool
    _pool = await aiomysql.create_pool(
        host=config["HOST"],
        user=config["USER"],
        password=config["PSWD"],
        db=config["DB"],
        port=config["PORT"],
        autocommit=True,
        charset="utf8mb4",
    )


async def close() -> None:
    """关闭连接池（进程退出时调用）。"""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
    _pool = None


def _error_code(error: BaseException) -> str:
    """把 aiomysql/PyMySQL 的异常转成 Node 版那样的 `err.code` 字符串。"""
    args = getattr(error, "args", ())
    if args and isinstance(args[0], int):
        return _ERR_NAMES.get(args[0], str(args[0]))
    return type(error).__name__


async def query(sql: str) -> QueryResult:
    """裸查询逃生口（对应 Node 版导出的 `query`）。

    :param sql: 完整 SQL 文本。
    :return: 查询结果。
    :raises DbError: 连接或执行失败。
    """
    if _pool is None:
        # 原实现在 init 之前会在这里抛 TypeError；这里抛同样性质的错误，不悄悄返回空。
        raise DbError("db.init() 尚未调用", "ENOINIT")
    try:
        async with _pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(sql)
                rows: list[dict[str, Any]] = []
                if cursor.description is not None:
                    rows = list(await cursor.fetchall())
                return QueryResult(rows=rows, rowcount=cursor.rowcount, insert_id=cursor.lastrowid or 0)
    except pymysql.err.MySQLError as error:
        raise DbError(str(error), _error_code(error)) from error


def _rows(result: QueryResult) -> list[dict[str, Any]]:
    """取 SELECT 的行；写操作没有行时返回空表。"""
    return result.rows


async def ping() -> tuple[bool, str | None]:
    """启动自检：只做一次 `SELECT 1`，探测数据库是否真的连得上。

    供启动横幅显示真实状态；探测失败不抛异常、也不要求进程退出——
    `/guest` 等接口并不依赖数据库，进程仍应能对外服务。

    :return: `(ok, detail)`；成功时 detail 为 None。
    """
    if _pool is None:
        return False, "db.init() 尚未调用"
    try:
        async with _pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.fetchall()
        return True, None
    except Exception as error:  # noqa: BLE001 —— 自检本身不允许抛
        return False, _error_code(error) or str(error)


# ---------------------------------------------------------------------------
# t_accounts
# ---------------------------------------------------------------------------


async def is_account_exist(account: Any) -> bool:
    """账号是否存在（**注意**：`/register` 里的用法是反的，见 account_server）。"""
    if account is None:
        return False
    try:
        result = await query(f'SELECT * FROM t_accounts WHERE account = "{account}"')
    except DbError as error:
        print(error)
        return False
    return len(_rows(result)) > 0


async def create_account(account: Any, password: str | None) -> bool:
    """新建账号（口令存 md5）。"""
    if account is None or password is None:
        return False
    psw = crypto.md5(password)
    sql = f'INSERT INTO t_accounts(account,password) VALUES("{account}","{psw}")'
    try:
        await query(sql)
    except DbError as error:
        # 原实现里 ER_DUP_ENTRY 与其它错误回调的都是 false（非重复错误还会再 throw 崩进程）；
        # Python 版统一记日志并返回 False。
        print(error)
        return False
    return True


async def get_account_info(account: Any, password: str | None) -> AccountRow | None:
    """按账号取账号行。

    **历史 bug（移植不修）**：原实现是"口令对得上就返回 null、对不上才返回账号行"，
    与直觉相反。`/auth` 因此永远回 "invalid account"。要修请单独开一次改动。
    """
    if account is None:
        return None
    try:
        result = await query(f'SELECT * FROM t_accounts WHERE account = "{account}"')
    except DbError as error:
        print(error)
        return None

    accounts = _rows(result)
    if len(accounts) == 0:
        return None
    if password is not None and accounts[0].get("password") == crypto.md5(password):
        return None
    return accounts[0]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# t_users
# ---------------------------------------------------------------------------


async def is_user_exist(account: Any) -> bool:
    """玩家档案是否已存在。"""
    if account is None:
        return False
    try:
        result = await query(f'SELECT userid FROM t_users WHERE account = "{account}"')
    except DbError as error:
        print(error)
        return False
    return len(_rows(result)) > 0


async def get_user_data(account: Any) -> UserBriefRow | None:
    """按账号取玩家资料（`name` 出库时做 Base64 解码）。"""
    if account is None:
        return None
    try:
        result = await query(
            "SELECT userid,account,name,lv,exp,coins,gems,roomid"
            f' FROM t_users WHERE account = "{account}"'
        )
    except DbError as error:
        print(error)
        return None

    users = _rows(result)
    if len(users) == 0:
        return None
    # t_users.name 允许 NULL；原实现直接把可能为 null 的值交给 fromBase64（为 null 时抛错），
    # 这里保持同样的取值路径。
    users[0]["name"] = crypto.from_base64(users[0]["name"])
    return users[0]  # type: ignore[return-value]


async def get_user_data_by_userid(userid: Any) -> UserBriefRow | None:
    """按 userid 取玩家资料。"""
    if userid is None:
        return None
    try:
        result = await query(
            "SELECT userid,account,name,lv,exp,coins,gems,roomid"
            f" FROM t_users WHERE userid = {userid}"
        )
    except DbError as error:
        print(error)
        return None

    users = _rows(result)
    if len(users) == 0:
        return None
    users[0]["name"] = crypto.from_base64(users[0]["name"])
    return users[0]  # type: ignore[return-value]


async def add_user_gems(userid: Any, gems: Any) -> bool:
    """增加玩家房卡（渠道/代理接口用）。"""
    if userid is None:
        return False
    sql = f"UPDATE t_users SET gems = gems +{gems} WHERE userid = {userid}"
    print(sql)
    try:
        result = await query(sql)
    except DbError as error:
        print(error)
        return False
    # UPDATE 返回 affectedRows；与原实现的判据一致。
    return result.rowcount > 0


async def get_gems(account: Any) -> dict[str, Any] | None:
    """取玩家的房卡数。"""
    if account is None:
        return None
    try:
        result = await query(f'SELECT gems FROM t_users WHERE account = "{account}"')
    except DbError as error:
        print(error)
        return None

    users = _rows(result)
    if len(users) == 0:
        return None
    return users[0]


async def get_user_history(userId: Any) -> list[Any] | None:
    """取玩家最近 10 局的战绩（存的是 JSON 数组文本）。"""
    if userId is None:
        return None
    try:
        result = await query(f'SELECT history FROM t_users WHERE userid = "{userId}"')
    except DbError as error:
        print(error)
        return None

    users = _rows(result)
    if len(users) == 0:
        return None
    history = users[0].get("history")
    if history is None or history == "":
        return None
    print(len(history))
    return json.loads(history)


async def update_user_history(userId: Any, history: Any) -> bool:
    """写回战绩，并顺手把 roomid 清成 NULL。

    原实现对 UPDATE 结果读 `length`（`ResultSetHeader` 上没有这个属性，运行时是
    `undefined`）：`undefined == 0` 为假，因此**实际总会回调 true**。这里保持同样的结果。
    """
    if userId is None or history is None:
        return False
    payload = json.dumps(history, separators=(",", ":") if isinstance(history, list) else None)
    sql = f'UPDATE t_users SET roomid = null, history = \'{payload}\' WHERE userid = "{userId}"'
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def create_user(
    account: str | None,
    name: str | None,
    coins: int,
    gems: int,
    sex: int,
    headimg: str | None,
) -> bool:
    """新建玩家档案（`name` 入库前做 Base64 编码）。"""
    if account is None or name is None or coins is None or gems is None:
        return False
    # headimg 一律被拼成 SQL 字面量（有值加引号，没有则写 null 这个裸值）。
    headimg_sql = f'"{headimg}"' if headimg else "null"
    name_b64 = crypto.to_base64(name)
    userId = _generate_user_id()

    sql = (
        'INSERT INTO t_users(userid,account,name,coins,gems,sex,headimg)'
        f' VALUES("{userId}", "{account}","{name_b64}",{coins},{gems},{sex},{headimg_sql})'
    )
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def update_user_info(
    userid: str | None,
    name: str,
    headimg: str | None,
    sex: int,
) -> QueryResult | None:
    """按 **account** 更新昵称/头像/性别（形参叫 userid，但 SQL 里比的是 account，与原实现一致）。"""
    if userid is None:
        return None
    headimg_sql = f'"{headimg}"' if headimg else "null"
    name_b64 = crypto.to_base64(name)
    sql = f'UPDATE t_users SET name="{name_b64}",headimg={headimg_sql},sex={sex} WHERE account="{userid}"'
    print(sql)
    try:
        result = await query(sql)
    except DbError as error:
        print(error)
        return None
    return result


async def get_user_base_info(userid: Any) -> UserBaseInfoRow | None:
    """取昵称/性别/头像（账号服 `/base_info` 用）。

    **历史 bug（移植不修）**：原实现不判空行，userid 不存在时会在 `users[0]` 处抛错。
    这里同样让 `IndexError` 抛给调用方。
    """
    if userid is None:
        return None
    sql = f"SELECT name,sex,headimg FROM t_users WHERE userid={userid}"
    print(sql)
    result = await query(sql)
    users = _rows(result)
    users[0]["name"] = crypto.from_base64(users[0]["name"])
    return users[0]  # type: ignore[return-value]


async def cost_gems(userid: Any, cost: Any) -> bool:
    """扣房卡。

    **历史 bug（移植不修）**：原实现读 `result.length > 0`，而 UPDATE 的返回对象没有
    `length`，`undefined > 0` 恒为假——回调**恒为 False**（调用方都忽略这个返回值）。
    """
    sql = f"UPDATE t_users SET gems = gems -{cost} WHERE userid = {userid}"
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return False


async def set_room_id_of_user(userId: Any, roomId: Any) -> bool:
    """设置玩家当前房间（`roomId` 为 None 时写 SQL 的 `null`）。

    **历史 bug（移植不修）**：与 `cost_gems` 同因，回调**恒为 False**。

    注意 `None` 这一支必须拼 **`null` 这个小写字面量**：原实现是字符串拼接
    `'UPDATE ... roomid = ' + null`，JS 会把 `null` 转成 `"null"`；Python 的 f-string
    则会把 `None` 渲染成 `"None"`，MySQL 会把它当成一个不存在的列而报错，
    于是"解散房间后清空玩家 roomid"这一步**静默失败**——玩家在库里仍然留在已解散的
    房间，之后建房会被大厅服以 `user is playing in room now.` 拒绝。
    """
    room_id_sql = f'"{roomId}"' if roomId is not None else "null"
    sql = f'UPDATE t_users SET roomid = {room_id_sql} WHERE userid = "{userId}"'
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return False


async def get_room_id_of_user(userId: Any) -> str | None:
    """取玩家当前所在房间。"""
    try:
        result = await query(f'SELECT roomid FROM t_users WHERE userid = "{userId}"')
    except DbError as error:
        print(error)
        return None
    users = _rows(result)
    if len(users) > 0:
        return users[0].get("roomid")
    return None


# ---------------------------------------------------------------------------
# t_rooms
# ---------------------------------------------------------------------------


async def is_room_exist(roomId: Any) -> bool:
    """房间是否已存在。"""
    try:
        result = await query(f'SELECT * FROM t_rooms WHERE id = "{roomId}"')
    except DbError as error:
        print(error)
        return False
    return len(_rows(result)) > 0


async def create_room(
    roomId: str,
    conf: Any,
    ip: str,
    port: int,
    create_time: int,
) -> str | None:
    """落库新建房间，返回 uuid（毫秒时间戳 + 房间号，19 位）。"""
    uuid = str(int(time.time() * 1000)) + roomId
    base_info = json.dumps(_conf_to_wire(conf), separators=(",", ":"))
    sql = (
        "INSERT INTO t_rooms(uuid,id,base_info,ip,port,create_time)"
        f" VALUES('{uuid}','{roomId}','{base_info}','{ip}',{port},{create_time})"
    )
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return None
    return uuid


async def get_room_uuid(roomId: Any) -> str | None:
    """按房间号取 uuid。

    **历史 bug（移植不修）**：原实现不判空行，房间不存在时会在 `roomRows[0]` 处抛错。
    """
    try:
        result = await query(f'SELECT uuid FROM t_rooms WHERE id = "{roomId}"')
    except DbError as error:
        print(error)
        return None
    return _rows(result)[0]["uuid"]


async def update_seat_info(
    roomId: str,
    seatIndex: int,
    userId: int,
    icon: str,
    name: str,
) -> bool:
    """写座位信息（`icon`/`name` 入库前做 Base64 编码）。"""
    name_b64 = crypto.to_base64(name)
    sql = (
        f'UPDATE t_rooms SET user_id{seatIndex} = {userId},user_icon{seatIndex} = "{icon}",'
        f'user_name{seatIndex} = "{name_b64}" WHERE id = "{roomId}"'
    )
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def update_num_of_turns(roomId: str, numOfTurns: int) -> bool:
    """更新已打局数。"""
    sql = f'UPDATE t_rooms SET num_of_turns = {numOfTurns} WHERE id = "{roomId}"'
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def update_next_button(roomId: str, nextButton: int) -> bool:
    """更新下一局的庄家。"""
    sql = f'UPDATE t_rooms SET next_button = {nextButton} WHERE id = "{roomId}"'
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def get_room_addr(roomId: Any) -> tuple[bool, str | None, int | None]:
    """取房间所在游戏服的地址。"""
    if roomId is None:
        return False, None, None
    try:
        result = await query(f'SELECT ip,port FROM t_rooms WHERE id = "{roomId}"')
    except DbError as error:
        print(error)
        return False, None, None
    addrs = _rows(result)
    if len(addrs) > 0:
        return True, addrs[0].get("ip"), addrs[0].get("port")
    return False, None, None


async def get_room_data(roomId: Any) -> RoomRow | None:
    """取整行房间数据（四个座位的昵称出库时做 Base64 解码）。"""
    if roomId is None:
        return None
    try:
        result = await query(f'SELECT * FROM t_rooms WHERE id = "{roomId}"')
    except DbError as error:
        print(error)
        return None
    room_rows = _rows(result)
    if len(room_rows) > 0:
        row = room_rows[0]
        for index in range(4):
            key = f"user_name{index}"
            row[key] = crypto.from_base64(row[key])
        return row  # type: ignore[return-value]
    return None


async def delete_room(roomId: str) -> bool:
    """删除房间行。"""
    sql = "DELETE FROM t_rooms WHERE id = '{0}'".format(roomId)
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


# ---------------------------------------------------------------------------
# t_games / t_games_archive
# ---------------------------------------------------------------------------


async def create_game(room_uuid: str, index: int, base_info: str) -> int | None:
    """写入一局的基础信息，返回自增主键。"""
    sql = (
        "INSERT INTO t_games(room_uuid,game_index,base_info,create_time)"
        f" VALUES('{room_uuid}',{index},'{base_info}',unix_timestamp(now()))"
    )
    try:
        result = await query(sql)
    except DbError as error:
        print(error)
        return None
    return result.insert_id


async def delete_games(room_uuid: str) -> bool:
    """删除某房间的在局记录（归档后调用）。"""
    sql = "DELETE FROM t_games WHERE room_uuid = '{0}'".format(room_uuid)
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def archive_games(room_uuid: str) -> bool:
    """把在局记录搬进归档表，再删掉在局记录。"""
    sql = "INSERT INTO t_games_archive(SELECT * FROM t_games WHERE room_uuid = '{0}')".format(room_uuid)
    print(sql)
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return await delete_games(room_uuid)


async def update_game_action_records(room_uuid: str, index: int, actions: str) -> bool:
    """写入操作流水 JSON。"""
    sql = (
        "UPDATE t_games SET action_records = '" + actions + "'"
        " WHERE room_uuid = '" + room_uuid + "' AND game_index = " + str(index)
    )
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


async def update_game_result(room_uuid: str, index: int, result: Any) -> bool:
    """写入单局结算结果（四个座位的得分数组）。

    原实现在 `room_uuid == null || result` 为真时先回调一次 false 再继续执行 SQL
    （调用方忽略这个参数），这里只保留"SQL 一定会执行"这一可观察行为。
    """
    if room_uuid is None:
        return False
    payload = json.dumps(result, separators=(",", ":"))
    sql = (
        "UPDATE t_games SET result = '" + payload + "'"
        " WHERE room_uuid = '" + room_uuid + "' AND game_index = " + str(index)
    )
    try:
        await query(sql)
    except DbError as error:
        print(error)
        return False
    return True


# ---------------------------------------------------------------------------
# t_message
# ---------------------------------------------------------------------------


async def get_message(type: Any, version: Any) -> MessageRow | None:
    """取公告/客服消息。

    `version` 为 `"null"` 或空时不加 version 过滤条件（与原实现一致）。
    """
    sql = 'SELECT * FROM t_message WHERE type = "' + str(type) + '"'

    if version == "null":
        version = None

    if version:
        sql += ' AND version != "' + str(version) + '"'

    try:
        result = await query(sql)
    except DbError as error:
        print(error)
        return None
    messages = _rows(result)
    if len(messages) > 0:
        return messages[0]  # type: ignore[return-value]
    return None


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------


def _generate_user_id() -> str:
    """生成 6 位 userid（首位 1-9），与 Node 版 `generateUserId()` 一致。"""
    result = ""
    for i in range(6):
        if i > 0:
            result += str(random.randrange(10))
        else:
            result += str(random.randrange(9) + 1)
    return result


def _conf_to_wire(conf: Any) -> dict[str, Any]:
    """把 `RoomConf` 序列化成 Node 版 `JSON.stringify(conf)` 的键序与键集。

    用显式字典而不是 `dataclasses.asdict`，是为了让落库的 JSON 与 Node 版逐字一致
    （键的顺序、以及 `type` 一定是原样字符串）。
    """
    if isinstance(conf, dict):
        return conf
    return {
        "type": conf.type,
        "baseScore": conf.baseScore,
        "zimo": conf.zimo,
        "jiangdui": conf.jiangdui,
        "hsz": conf.hsz,
        "dianganghua": conf.dianganghua,
        "menqing": conf.menqing,
        "tiandihu": conf.tiandihu,
        "maxFan": conf.maxFan,
        "maxGames": conf.maxGames,
        "creator": conf.creator,
    }


def account_rows(result: QueryResult) -> list[AccountRow]:
    """把查询结果收窄成 `t_accounts` 行（给调用方做显式类型标注用）。"""
    return result.rows  # type: ignore[return-value]
