"""玩家库（`db_scmj`）的**只读**数据源。

这是管理平台读玩家库的**唯一通道**：玩家管理读 `t_users`，房间管理读 `t_rooms`，
两者都在这个文件里拼 SQL。新增别的玩家库表时也放进来，**不要另开第二条通道**
（见 `../AGENTS.md` §2 第 1 / 5 条）。

为什么需要它
------------

玩家管理要展示 `t_users` 里的账号、昵称、房卡（`gems`）与金币，还要支持
"按账号 / 昵称 / ID 搜索 + 分页"。游戏服现有的 HTTP 接口只能**按 account 取单个玩家**
（大厅服 `/login`、渠道 API `/get_user_info`），没有列表能力，所以按
`../AGENTS.md` §2 第 5 条开一条**只读数据源**。

房间管理（`apps/rooms/`）要展示 `t_rooms` 里的存活房间、配置、座位与所在游戏服，
同样没有现成接口，故复用同一条通道。**注意 `t_rooms` 与 `t_users` 在同一个库里**，
所以"不另开第二条"在这里不是可选项：多一条连接就多一处绕过只读校验的可能。

三条硬边界（改这个文件前先读）
------------------------------

1. **只读**：这里只执行 SELECT。`_assert_read_only()` 会拒绝任何非 SELECT、
   含分号的多语句、以及句子里出现写关键字（INSERT / UPDATE / DELETE / ...）的 SQL。
   这是第二道防线；生产上建议再给 `DATABASES["player"]` 配一个只有 SELECT 权限的账号。
2. **不落模型**：管理平台的 Django 模型与迁移都不在玩家库上（本平台库是 `db_scmj_admin`，
   只放 `AdminUser` 与 `PlayerBan`）。这条路径走的是裸 SQL，不走 ORM。
3. **不复用游戏服的访问层**：不 import `server-python/utils/db.py`，
   也不共享它的连接池——那是游戏服的代码，管理平台碰它会把两边的行为绑死。

字段口径
--------

`t_users.name` 与 `t_rooms.user_name0..3` 入库前都做过 Base64 编码
（见 `utils/db.py` 的 `create_user` / `update_seat_info`），所以读出来必须解码再展示；
解不出来就按原文返回（历史数据可能有例外）。

`t_rooms` 的几个容易误读的点：

* 这张表里只有**尚未销毁**的房间——游戏服的 `roommgr.destroy()` 会删掉整行，
  进程重启时再用这些行把房间恢复回内存。所以它约等于"当前存活房间"；
* 房间配置是 `base_info` 列里的**紧凑 JSON**（`json.dumps(..., separators=(",", ":"))`，
  `type` 是第一个键，见 `utils/db.py` 的 `_conf_to_wire`）；
* 时间是 Unix **秒**（`create_time`），不是 `DATETIME`；
* `conf.single`（单人模式）**不落库**，所以后台看不出一个房间是不是人机房。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
from datetime import datetime, timezone as datetime_timezone
from typing import Any, Final

from django.db import DatabaseError, connections
from django.db.utils import ConnectionDoesNotExist, ImproperlyConfigured
from django.utils import timezone

from .exceptions import PlayerSourceReadOnlyViolation, PlayerSourceUnavailable

logger = logging.getLogger(__name__)

#: 玩家库在 `settings.DATABASES` 里的别名。定义在 `config/settings.py`。
PLAYER_DB_ALIAS: Final[str] = "player"

#: 玩家表名（权威定义在 `server/sql/db_babykylin.sql`）。
PLAYER_TABLE: Final[str] = "t_users"

#: 列表与详情统一取这些列。刻意不取 `history`（最大 4096 字节，列表用不上）。
PLAYER_COLUMNS: Final[str] = "userid, account, name, sex, headimg, lv, exp, coins, gems, roomid"

#: `_assert_read_only()` 拒绝的写关键字（按单词边界匹配，`create_time` 这类列名不受影响）。
_WRITE_KEYWORDS: Final[tuple[str, ...]] = (
    "insert",
    "update",
    "delete",
    "replace",
    "drop",
    "truncate",
    "alter",
    "create",
    "grant",
    "revoke",
)

#: `LIKE` 的转义字符。刻意不用反斜杠：MySQL 的字符串字面量里 `'\'` 要写成 `'\\'`，
#: 而 SQLite 不处理反斜杠转义，同一句 SQL 两边语义会不一致；`!` 在两边行为一致。
LIKE_ESCAPE: Final[str] = "!"

#: 允许的排序键 → SQL 片段。**白名单**，不做字符串拼接，避免 order by 注入。
ORDERING_CHOICES: Final[dict[str, str]] = {
    "-userid": "userid DESC",
    "userid": "userid ASC",
    "-gems": "gems DESC",
    "gems": "gems ASC",
    "-coins": "coins DESC",
    "coins": "coins ASC",
    "-lv": "lv DESC",
    "lv": "lv ASC",
}

#: 默认排序：新注册的玩家排在前面。
DEFAULT_ORDERING: Final[str] = "-userid"


def _assert_read_only(sql: str) -> None:
    """校验一条 SQL 是单条 SELECT。

    :param sql: 待执行的 SQL。
    :raises PlayerSourceReadOnlyViolation: 非 SELECT、含分号、或出现写关键字。
    """
    normalized = " ".join(sql.split())
    lowered = normalized.lower()
    if not lowered.startswith("select"):
        raise PlayerSourceReadOnlyViolation(f"玩家库只允许 SELECT：{normalized[:80]}")
    if ";" in normalized:
        raise PlayerSourceReadOnlyViolation(f"玩家库只允许单条语句：{normalized[:80]}")
    for keyword in _WRITE_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise PlayerSourceReadOnlyViolation(
                f"玩家库只允许只读查询，SQL 里出现了 `{keyword}`：{normalized[:80]}"
            )


def _run(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """执行一条只读 SQL 并取回结果行。

    :param sql: SELECT 语句。
    :param params: 参数（占位符用 `%s`，两种数据库驱动都认）。
    :raises PlayerSourceUnavailable: 玩家库连不上 / 配置错误。
    """
    _assert_read_only(sql)
    try:
        with connections[PLAYER_DB_ALIAS].cursor() as cursor:
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description or []]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except (DatabaseError, ImproperlyConfigured, ConnectionDoesNotExist) as error:
        # 详细原因只进日志；给前端一句可操作的文案，避免把连接串之类的东西吐出去。
        logger.warning("玩家只读数据源查询失败：%s: %s", type(error).__name__, error)
        raise PlayerSourceUnavailable() from error


def _placeholders(count: int) -> str:
    """生成 `%s, %s, ...` 占位符列表。"""
    return ", ".join(["%s"] * count)


def _escape_like(value: str) -> str:
    """转义 `LIKE` 里的通配符（配合 `ESCAPE '!'`）。"""
    return value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", f"{LIKE_ESCAPE}%").replace(
        "_", f"{LIKE_ESCAPE}_"
    )


def _name_to_base64(value: str) -> str:
    """把昵称按游戏服的入库口径编码成 Base64（用于昵称搜索）。"""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def decode_player_name(raw: Any) -> str:
    """把 `t_users.name` 的 Base64 还原成昵称。

    解不出来（历史脏数据、本来就是明文）时**按原文返回**，不抛异常——
    后台列表不该因为一行脏数据整页打不开。
    """
    if raw is None:
        return ""
    text = str(raw)
    if not text:
        return ""
    try:
        return base64.b64decode(text, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return text


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    """把一行玩家记录整理成视图层用的固定字段集（缺列时给默认值）。"""
    return {
        "player_id": int(row.get("userid") or 0),
        "account": row.get("account") or "",
        "name": decode_player_name(row.get("name")),
        "sex": row.get("sex"),
        "headimg": row.get("headimg"),
        "lv": int(row.get("lv") or 0),
        "exp": int(row.get("exp") or 0),
        "coins": int(row.get("coins") or 0),
        "gems": int(row.get("gems") or 0),
        "roomid": row.get("roomid") or "",
    }


def _where_clause(
    *,
    keyword: str,
    only_ids: list[int] | None,
    exclude_ids: list[int] | None,
) -> tuple[str, list[Any]]:
    """拼 `WHERE` 子句。

    :param keyword: 搜索词（账号 / 昵称 / 纯数字时按 userid 精确匹配）。
    :param only_ids: 只保留这些 userid（用于"只看封禁中"）。
    :param exclude_ids: 排除这些 userid（用于"只看正常"）。
    :return: `(where_sql, params)`；没有条件时 `where_sql` 为空串。
    """
    parts: list[str] = []
    params: list[Any] = []

    text = keyword.strip()
    if text:
        clauses = [
            f"account LIKE %s ESCAPE '{LIKE_ESCAPE}'",
            f"name LIKE %s ESCAPE '{LIKE_ESCAPE}'",
        ]
        params.extend([f"%{_escape_like(text)}%", f"%{_escape_like(_name_to_base64(text))}%"])
        if text.isdigit():
            # 纯数字搜索词同时按 userid 精确命中（运营最常拿到的就是 ID）。
            clauses.append("userid = %s")
            params.append(int(text))
        parts.append("(" + " OR ".join(clauses) + ")")

    if only_ids is not None:
        ids = sorted({int(item) for item in only_ids})
        if not ids:
            # 空集合 = 一条都不匹配；让调用方拿到空结果，而不是退化成"全表"。
            return " WHERE 1 = 0", []
        parts.append(f"userid IN ({_placeholders(len(ids))})")
        params.extend(ids)

    if exclude_ids:
        ids = sorted({int(item) for item in exclude_ids})
        if ids:
            parts.append(f"userid NOT IN ({_placeholders(len(ids))})")
            params.extend(ids)

    if not parts:
        return "", []
    return " WHERE " + " AND ".join(parts), params


def count_players() -> int:
    """玩家总数（用于概览卡片）。"""
    rows = _run(f"SELECT COUNT(*) AS total FROM {PLAYER_TABLE}", [])
    return int(rows[0]["total"]) if rows else 0


def get_player(player_id: int) -> dict[str, Any] | None:
    """按 userid 取一个玩家；不存在时返回 `None`。"""
    rows = _run(
        f"SELECT {PLAYER_COLUMNS} FROM {PLAYER_TABLE} WHERE userid = %s LIMIT 1",
        [int(player_id)],
    )
    return _normalize(rows[0]) if rows else None


def get_player_by_account(account: str) -> dict[str, Any] | None:
    """按 account 取一个玩家；不存在时返回 `None`。

    `t_users.account` 上有唯一索引，所以这是一次索引精确查找（内部封禁校验接口
    每来一次登录就会走一次，必须走索引）。

    :param account: 玩家账号（游戏侧的 `t_users.account`）。
    """
    text = (account or "").strip()
    if not text:
        return None
    rows = _run(
        f"SELECT {PLAYER_COLUMNS} FROM {PLAYER_TABLE} WHERE account = %s LIMIT 1",
        [text],
    )
    return _normalize(rows[0]) if rows else None


def search_players(
    *,
    keyword: str = "",
    ordering: str = DEFAULT_ORDERING,
    page: int = 1,
    page_size: int = 20,
    only_ids: list[int] | None = None,
    exclude_ids: list[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """按条件分页查询玩家。

    :param keyword: 搜索词，空串表示不过滤。
    :param ordering: `ORDERING_CHOICES` 里的键（调用方已用序列化器校验过）。
    :param page: 页码，从 1 开始。
    :param page_size: 每页条数。
    :param only_ids: 只保留这些 userid；`None` 表示不限制。
    :param exclude_ids: 排除这些 userid。
    :return: `(当前页玩家列表, 过滤后的总条数)`。
    """
    where, params = _where_clause(keyword=keyword, only_ids=only_ids, exclude_ids=exclude_ids)

    count_rows = _run(f"SELECT COUNT(*) AS total FROM {PLAYER_TABLE}{where}", list(params))
    total = int(count_rows[0]["total"]) if count_rows else 0
    if total == 0:
        return [], 0

    order_sql = ORDERING_CHOICES.get(ordering, ORDERING_CHOICES[DEFAULT_ORDERING])
    offset = max(page - 1, 0) * page_size
    rows = _run(
        f"SELECT {PLAYER_COLUMNS} FROM {PLAYER_TABLE}{where}"
        f" ORDER BY {order_sql} LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    )
    return [_normalize(row) for row in rows], total


# ---------------------------------------------------------------------------
# 房间（t_rooms）
# ---------------------------------------------------------------------------
#
# 房间管理（`apps/rooms/`）读的就是下面这几个函数。与 `t_users` 一样：
# 参数全部走占位符、排序键走白名单、只发 SELECT。

#: 房间表名（权威定义在 `server/sql/db_babykylin.sql`）。
ROOM_TABLE: Final[str] = "t_rooms"

#: 座位数固定为 4：`t_rooms` 是宽表，列名是 `user_id0..user_id3`，没有座位子表。
ROOM_SEAT_COUNT: Final[int] = 4

#: 列表与详情统一取这些列（含四个座位的 ID / 头像 / 昵称 / 得分）。
ROOM_COLUMNS: Final[str] = (
    "uuid, id, base_info, create_time, num_of_turns, next_button, ip, port, "
    "user_id0, user_icon0, user_name0, user_score0, "
    "user_id1, user_icon1, user_name1, user_score1, "
    "user_id2, user_icon2, user_name2, user_score2, "
    "user_id3, user_icon3, user_name3, user_score3"
)

#: 玩法标识 → 大厅里的名字。
#:
#: 口径来自客户端：`CreateRoom.getType()` 的索引 0 / 1 分别是 `xzdd` / `xlch`，
#: 大厅场景（`client/assets/scenes/hall.fire`）里 `xzdd_title` 的标签是"血战到底"、
#: `xlch_title` 是"血流成河"；服务端也印证这一点——`gamemgr_xzdd` 在"三家胡牌"时
#: 就结束本局（`if num_of_hued == 3`），而 `gamemgr_xlch` 继续打。
#: 注意 `docs/ai-native/game-rules.md` §1 把 `xlch` 也称作"血战到底"，那是按服务端
#: 文件的口径写的；后台面向运营，这里采用**玩家在大厅里看到的名字**。
ROOM_TYPE_LABELS: Final[dict[str, str]] = {"xzdd": "血战到底", "xlch": "血流成河"}

#: 列表页的状态过滤。状态由**座位占用**推导：
#: * `waiting`——还有空位（等玩家进来）；
#: * `playing`——四个座位都有人（房间还在 `t_rooms` 里就意味着还没被销毁）。
ROOM_STATE_ALL: Final[str] = "all"
ROOM_STATE_WAITING: Final[str] = "waiting"
ROOM_STATE_PLAYING: Final[str] = "playing"
ROOM_STATE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ROOM_STATE_ALL, "全部"),
    (ROOM_STATE_WAITING, "未满座"),
    (ROOM_STATE_PLAYING, "已满座"),
)

#: 允许的排序键 → SQL 片段。**白名单**，不做字符串拼接；同值时用 `id` 兜底，
#: 否则同一秒创建的多个房间在翻页时可能重复或漏掉。
ROOM_ORDERING_CHOICES: Final[dict[str, str]] = {
    "-create_time": "create_time DESC, id DESC",
    "create_time": "create_time ASC, id ASC",
    "-num_of_turns": "num_of_turns DESC, create_time DESC, id DESC",
    "num_of_turns": "num_of_turns ASC, create_time DESC, id DESC",
}

#: 默认排序：最新创建的房间排在前面。
ROOM_DEFAULT_ORDERING: Final[str] = "-create_time"

#: "满座"的 SQL 判定（四个座位都有人）。
_ROOM_FULL_SQL: Final[str] = (
    "user_id0 > 0 AND user_id1 > 0 AND user_id2 > 0 AND user_id3 > 0"
)


def decode_room_conf(raw: Any) -> dict[str, Any]:
    """把 `t_rooms.base_info` 的 JSON 解析成字典。

    解析不出来（历史脏数据、建表默认值 `'0'`）时返回空字典：后台列表不该因为
    一行坏数据整页打不开，与 `decode_player_name` 同一取舍。
    """
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_unix_seconds(value: Any) -> str:
    """把 Unix 秒转成 `YYYY-MM-DD HH:mm:ss`（与 `REST_FRAMEWORK.DATETIME_FORMAT` 一致）。

    `create_time` 是秒级时间戳，前端不该自己处理时区，所以在这里按
    `settings.TIME_ZONE`（Asia/Shanghai）格式化好再返回。
    """
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    moment = datetime.fromtimestamp(seconds, tz=datetime_timezone.utc)
    return timezone.localtime(moment).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_conf(raw: Any) -> dict[str, Any]:
    """把落库的 `base_info` 收窄成固定键集的房间配置。

    只做键名转换与类型兜底，不做业务解释（`zimo` / `dianganghua` 这类枚举的中文名
    由前端映射），这样新增玩法设置时后台不会因为不认识的键而报错。
    """
    conf = decode_room_conf(raw)
    return {
        "type": str(conf.get("type") or ""),
        "base_score": int(conf.get("baseScore") or 0),
        "max_fan": int(conf.get("maxFan") or 0),
        "max_games": int(conf.get("maxGames") or 0),
        "creator": int(conf.get("creator") or 0),
        "zimo": int(conf.get("zimo") or 0),
        "dianganghua": int(conf.get("dianganghua") or 0),
        "jiangdui": bool(conf.get("jiangdui")),
        "hsz": bool(conf.get("hsz")),
        "menqing": bool(conf.get("menqing")),
        "tiandihu": bool(conf.get("tiandihu")),
    }


def _normalize_seat(row: dict[str, Any], index: int) -> dict[str, Any]:
    """取第 `index` 个座位（`index` 取 0..3）。空座位的 `player_id` 是 0。"""
    return {
        "seat_index": index,
        "player_id": int(row.get(f"user_id{index}") or 0),
        "name": decode_player_name(row.get(f"user_name{index}")),
        "icon": row.get(f"user_icon{index}") or "",
        "score": int(row.get(f"user_score{index}") or 0),
    }


def _normalize_room(row: dict[str, Any]) -> dict[str, Any]:
    """把一行房间记录整理成视图层用的固定字段集。"""
    seats = [_normalize_seat(row, index) for index in range(ROOM_SEAT_COUNT)]
    occupied = sum(1 for seat in seats if seat["player_id"] > 0)
    conf = _normalize_conf(row.get("base_info"))
    return {
        "uuid": str(row.get("uuid") or ""),
        "room_id": str(row.get("id") or ""),
        "type": conf["type"],
        "state": (
            ROOM_STATE_PLAYING if occupied >= ROOM_SEAT_COUNT else ROOM_STATE_WAITING
        ),
        "seat_count": ROOM_SEAT_COUNT,
        "occupied_seats": occupied,
        "create_time": int(row.get("create_time") or 0),
        "created_at": _format_unix_seconds(row.get("create_time")),
        "num_of_turns": int(row.get("num_of_turns") or 0),
        "next_button": int(row.get("next_button") or 0),
        "ip": row.get("ip") or "",
        "port": int(row.get("port") or 0),
        "conf": conf,
        "seats": seats,
    }


def _room_where_clause(
    *,
    keyword: str,
    room_type: str,
    state: str,
) -> tuple[str, list[Any]]:
    """拼房间列表的 `WHERE` 子句。

    :param keyword: 搜索词（纯数字时同时匹配房间号 / uuid / 座位玩家 ID，否则按座位昵称）。
    :param room_type: 玩法标识；空串表示不过滤。
    :param state: `ROOM_STATE_*` 之一。
    :return: `(where_sql, params)`；没有条件时 `where_sql` 为空串。
    """
    parts: list[str] = []
    params: list[Any] = []

    text = keyword.strip()
    if text:
        clauses: list[str] = []
        if text.isdigit():
            # 运营手里最常见的三个键：房间号、uuid、坐在里面的玩家 ID。
            clauses.extend(["id = %s", "uuid = %s"])
            params.extend([text, text])
            for index in range(ROOM_SEAT_COUNT):
                clauses.append(f"user_id{index} = %s")
                params.append(int(text))
        # 座位昵称与玩家库一样是 Base64 存的（`utils/db.update_seat_info`）。
        for index in range(ROOM_SEAT_COUNT):
            clauses.append(f"user_name{index} LIKE %s ESCAPE '{LIKE_ESCAPE}'")
            params.append(f"%{_escape_like(_name_to_base64(text))}%")
        parts.append("(" + " OR ".join(clauses) + ")")

    if room_type:
        # `base_info` 是紧凑 JSON 且 `type` 是第一个键，所以这个形态是稳定的
        # （见 `utils/db._conf_to_wire`）；调用方已用序列化器把取值限制在已知玩法内。
        parts.append("base_info LIKE %s ESCAPE '!'")
        params.append(f'%"type":"{_escape_like(room_type)}"%')

    if state == ROOM_STATE_PLAYING:
        parts.append(f"({_ROOM_FULL_SQL})")
    elif state == ROOM_STATE_WAITING:
        parts.append(f"NOT ({_ROOM_FULL_SQL})")

    if not parts:
        return "", []
    return " WHERE " + " AND ".join(parts), params


def count_rooms() -> int:
    """当前存活房间总数（用于概览卡片）。"""
    rows = _run(f"SELECT COUNT(*) AS total FROM {ROOM_TABLE}", [])
    return int(rows[0]["total"]) if rows else 0


def room_overview(*, recent_seconds: int = 24 * 3600) -> dict[str, int]:
    """房间概览：总数 / 已满座 / 未满座 / 最近一段时间新建的房间数。

    :param recent_seconds: "最近"的窗口，默认 24 小时（`create_time` 是秒）。
    """
    threshold = int(time.time()) - max(int(recent_seconds), 0)
    rows = _run(
        "SELECT COUNT(*) AS total,"
        f" SUM(CASE WHEN {_ROOM_FULL_SQL} THEN 1 ELSE 0 END) AS full_rooms,"
        " SUM(CASE WHEN create_time >= %s THEN 1 ELSE 0 END) AS recent_rooms"
        f" FROM {ROOM_TABLE}",
        [threshold],
    )
    row = rows[0] if rows else {}
    total = int(row.get("total") or 0)
    full = int(row.get("full_rooms") or 0)
    return {
        "total_rooms": total,
        "playing_rooms": full,
        "waiting_rooms": max(total - full, 0),
        "created_last_24h": int(row.get("recent_rooms") or 0),
    }


def get_room(room_ref: str) -> dict[str, Any] | None:
    """按房间号（`t_rooms.id`）或 uuid 取一个房间；不存在时返回 `None`。

    两种标识都可以：运营从列表点进来带的是 6 位房间号，排查问题时手上可能只有 uuid。
    两个列上都有唯一索引，所以这是一次索引精确查找。
    """
    text = (room_ref or "").strip()
    if not text:
        return None
    rows = _run(
        f"SELECT {ROOM_COLUMNS} FROM {ROOM_TABLE} WHERE id = %s OR uuid = %s LIMIT 1",
        [text, text],
    )
    return _normalize_room(rows[0]) if rows else None


def search_rooms(
    *,
    keyword: str = "",
    room_type: str = "",
    state: str = ROOM_STATE_ALL,
    ordering: str = ROOM_DEFAULT_ORDERING,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """按条件分页查询房间。

    :param keyword: 搜索词，空串表示不过滤。
    :param room_type: 玩法标识（已知玩法），空串表示不过滤。
    :param state: `ROOM_STATE_*` 之一。
    :param ordering: `ROOM_ORDERING_CHOICES` 里的键（调用方已用序列化器校验过）。
    :param page: 页码，从 1 开始。
    :param page_size: 每页条数。
    :return: `(当前页房间列表, 过滤后的总条数)`。
    """
    where, params = _room_where_clause(keyword=keyword, room_type=room_type, state=state)

    count_rows = _run(f"SELECT COUNT(*) AS total FROM {ROOM_TABLE}{where}", list(params))
    total = int(count_rows[0]["total"]) if count_rows else 0
    if total == 0:
        return [], 0

    order_sql = ROOM_ORDERING_CHOICES.get(ordering, ROOM_ORDERING_CHOICES[ROOM_DEFAULT_ORDERING])
    offset = max(page - 1, 0) * page_size
    rows = _run(
        f"SELECT {ROOM_COLUMNS} FROM {ROOM_TABLE}{where}"
        f" ORDER BY {order_sql} LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    )
    return [_normalize_room(row) for row in rows], total
