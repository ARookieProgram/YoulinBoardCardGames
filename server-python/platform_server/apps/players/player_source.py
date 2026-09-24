"""玩家库（`db_scmj`）的**只读**数据源。

这是管理平台读玩家库的**唯一通道**：玩家管理读 `t_users`，房间管理读 `t_rooms`，
对局记录读 `t_games` / `t_games_archive`，全部在这个文件里拼 SQL。新增别的玩家库表时
也放进来，**不要另开第二条通道**（见 `../AGENTS.md` §2 第 1 / 5 条）。

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

`t_games` / `t_games_archive` 是对局记录（对局记录模块读的就是下面那一段）：

* 两张表结构完全相同，`room_uuid` + `game_index` 是联合主键；游戏服**每开一局就写一行**
  `t_games`，房间打完 / 被解散时 `archive_games()` 把它整批搬进 `t_games_archive` 并删掉在局行。
  所以 `t_games` ≈ "还在房间里的对局"，`t_games_archive` ≈ "已经结束房间的对局"（长期保留）；
* `game_index` 从 **0** 开始（`gamemgr.begin()` 里 `gameIndex = room_info.numOfGames`，
  之后 `numOfGames += 1`），所以展示时统一 `round = game_index + 1`；
* `base_info` 是本局的开局快照：`{type, button, index, mahjongs, game_seats}`
  （`mahjongs` 是洗好的 108 张牌墙，`game_seats` 是四家起手牌）；
* `action_records` 是**出牌流水的紧凑 JSON 数组**，每三个一组 `[座位, 动作, 牌]`
  （动作编号与牌 id 的口径见 `apps/games/decoding.py`）；
* `result` 是四个座位本局的得分数组（与 `action_records`、`base_info` 一样是 JSON 文本）；
* **这两张表里没有玩家身份，也没有房间号**：只有座位号与 uuid。玩家身份要另找——
  房间还在 `t_rooms` 里就用座位列，房间已经销毁就只能从
  `t_users.history`（每人最近 10 场，含 uuid / 房间号 / 四家昵称与总分）反查，
  也就是 `resolve_room_identities()` 做的事；两边都查不到时（玩家只打了一局就散场，
  而 `store_history()` 只在 `numOfGames > 1` 时写）座位会显示成"未知玩家"。
  **房间号则一定能还原**：uuid 是"13 位毫秒时间戳 + 6 位房间号"（见 `room_id_from_uuid`），
  而 `_uuids_by_room_id()` 又支持按这个后缀反查，所以"只有一个房间号、房间又已销毁"也查得到。
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


def format_unix_seconds(value: Any) -> str:
    """把 Unix 秒转成 `YYYY-MM-DD HH:mm:ss`（与 `REST_FRAMEWORK.DATETIME_FORMAT` 一致）。

    `create_time` 是秒级时间戳，前端不该自己处理时区，所以在这里按
    `settings.TIME_ZONE`（Asia/Shanghai）格式化好再返回。对局记录模块也用它，
    所以是公开函数（不是 `_` 开头的内部工具）。
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
        "created_at": format_unix_seconds(row.get("create_time")),
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


# ---------------------------------------------------------------------------
# 对局记录（t_games / t_games_archive）
# ---------------------------------------------------------------------------
#
# 对局记录模块（`apps/games/`）读的就是下面这一段的函数。与 `t_users` / `t_rooms` 一样：
# 参数全部走占位符、排序键走白名单、只发 SELECT。
#
# 两张表的取舍写在模块文档里；这里补充三件**只有读库的人才知道**的事：
#
# 1. 房间号（`t_rooms.id`）**不在** `t_games` 里，所以"按房间号查对局"必须先解析成
#    uuid：存活房间查 `t_rooms`，已结束房间只能扫 `t_users.history`（见 `resolve_room_uuids`）；
# 2. 同理，玩家身份也只能靠 `t_users.history` 反查，这一扫是**全表扫 4096 字节的大列**，
#    所以所有扫描都带 `LIMIT`（`HISTORY_SCAN_LIMIT`），并且只在必要时才做；
# 3. 两份表结构一样，所以列表用 `UNION ALL` 合并、再统一排序分页；`game_source` 列标出
#    这一行是从哪张表来的（前端据此显示"进行中 / 已结束"）。

#: 在局对局表（房间还没销毁）。
GAME_LIVE_TABLE: Final[str] = "t_games"

#: 归档对局表（房间已销毁 / 已打完，长期保留）。
GAME_ARCHIVE_TABLE: Final[str] = "t_games_archive"

#: 两张相同结构的表统一取这些列。`base_info` / `action_records` / `result` 都是 JSON 文本。
GAME_COLUMNS: Final[str] = "room_uuid, game_index, base_info, create_time, action_records, result"

#: 对局来源过滤。
GAME_SOURCE_ALL: Final[str] = "all"
GAME_SOURCE_ARCHIVE: Final[str] = "archive"
GAME_SOURCE_LIVE: Final[str] = "live"
GAME_SOURCE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (GAME_SOURCE_ALL, "全部"),
    (GAME_SOURCE_ARCHIVE, "已结束"),
    (GAME_SOURCE_LIVE, "进行中"),
)

#: 来源标识 → 大厅里的说法（前端直接用，避免两边各写一套）。
GAME_SOURCE_LABELS: Final[dict[str, str]] = {
    GAME_SOURCE_ARCHIVE: "已结束",
    GAME_SOURCE_LIVE: "进行中",
}

#: `(表名, 来源标识)`，顺序固定：先归档后在进行，`UNION ALL` 的结果顺序因此是稳定的。
GAME_TABLE_SOURCES: Final[tuple[tuple[str, str], ...]] = (
    (GAME_ARCHIVE_TABLE, GAME_SOURCE_ARCHIVE),
    (GAME_LIVE_TABLE, GAME_SOURCE_LIVE),
)

#: 对局里的玩家身份是从哪儿查到的。
GAME_IDENTITY_ROOMS: Final[str] = "rooms"
GAME_IDENTITY_HISTORY: Final[str] = "history"
GAME_IDENTITY_UNKNOWN: Final[str] = "unknown"

#: 身份来源 → 给运营看的一句话（前端直接展示，不必自己编）。
GAME_IDENTITY_LABELS: Final[dict[str, str]] = {
    GAME_IDENTITY_ROOMS: "来自存活房间表 t_rooms（房间还没销毁）",
    GAME_IDENTITY_HISTORY: "来自玩家战绩 t_users.history（房间已销毁，按 uuid 反查）",
    GAME_IDENTITY_UNKNOWN: "无法确认玩家身份（房间已销毁且没有战绩快照）",
}

#: 允许的排序键 → `UNION ALL` 之后的 `ORDER BY` 片段。**白名单**，不做字符串拼接；
#: 同值时用 `game_index` / `room_uuid` 兜底，否则同一秒结束的多个房间翻页会重复或漏行。
GAME_ORDERING_CHOICES: Final[dict[str, str]] = {
    "-create_time": "create_time DESC, game_index DESC, room_uuid DESC",
    "create_time": "create_time ASC, game_index ASC, room_uuid ASC",
    "-game_index": "game_index DESC, create_time DESC, room_uuid DESC",
    "game_index": "game_index ASC, create_time ASC, room_uuid ASC",
}

#: 默认排序：最新结束 / 最新开局的排在前面。
GAME_DEFAULT_ORDERING: Final[str] = "-create_time"

#: 房间号固定 6 位（游戏服 `roommgr.generate_room_id()` 循环 6 次取随机数字）。
GAME_ROOM_ID_LENGTH: Final[int] = 6

#: uuid 的前缀长度：`utils/db.create_room()` 用 `str(int(time.time()*1000))`（13 位毫秒）。
GAME_UUID_PREFIX_LENGTH: Final[int] = 13

#: uuid 的总长度：13 位毫秒 + 6 位房间号 = 19 位（列定义是 `char(20)`，实际写 19 位）。
GAME_UUID_LENGTH: Final[int] = GAME_UUID_PREFIX_LENGTH + GAME_ROOM_ID_LENGTH

#: 按关键字解析出来的 uuid 最多参与过滤的个数（防止昵称搜出上万条历史）。
GAME_UUID_FILTER_MAX: Final[int] = 200

#: 按房间号后缀反查 uuid 时最多返回几个（同一房间号理论上唯一，留点余量给脏数据）。
GAME_ROOM_ID_LOOKUP_LIMIT: Final[int] = 20

#: 扫 `t_users.history` 时最多取多少行（一局最多 4 个玩家，这个上限非常宽松）。
HISTORY_SCAN_LIMIT: Final[int] = 200

#: 一次 `LIKE ... OR ...` 里最多放多少条模式（一批 = 一次全表扫描）。
HISTORY_SCAN_CHUNK: Final[int] = 20

#: 游戏服每人的战绩只保留最近 10 场（`gamemgr.store_single_history`）。
HISTORY_MAX_ENTRIES: Final[int] = 10

#: `t_users.history` 里一场战绩的字段（口径见 `gamemgr.store_history`）。
_HISTORY_UUID_KEY: Final[str] = "uuid"


def room_id_from_uuid(uuid: Any) -> str:
    """从 uuid 反推房间号（推不出来时返回空串）。

    游戏服 `utils/db.create_room()` 的生成口径是
    `uuid = str(int(time.time() * 1000)) + roomId`，而 `roommgr.generate_room_id()`
    固定生成 6 位数字，所以 uuid 就是 **13 位毫秒时间戳 + 6 位房间号** 的 19 位数字串。

    这是"房间已销毁、又没有战绩快照"时**唯一**还能还原房间号的线索：
    `t_games` / `t_games_archive` 里只有 uuid，没有房间号列。
    """
    text = str(uuid or "").strip()
    if len(text) != GAME_UUID_LENGTH or not text.isdigit():
        return ""
    return text[GAME_UUID_PREFIX_LENGTH:]


def _uuids_by_room_id(room_id: str, *, limit: int = GAME_ROOM_ID_LOOKUP_LIMIT) -> list[str]:
    """按房间号反查 uuid（对局表里只有 uuid，所以按**后缀**匹配）。

    `room_uuid LIKE '%<6 位房间号>'` 用不上索引，是一次全表扫；但这是"只有房间号、
    房间又已经销毁"时唯一的查法，而且结果按"最近还有对局"排序，运营要的多半就是最近那场。

    :param room_id: 6 位房间号。
    :return: uuid 列表（最近有对局的在前）；房间号形态不对时是空列表。
    """
    text = (room_id or "").strip()
    if not text.isdigit() or len(text) != GAME_ROOM_ID_LENGTH:
        return []
    found: list[tuple[int, str]] = []
    for table, _source in GAME_TABLE_SOURCES:
        rows = _run(
            f"SELECT room_uuid, MAX(create_time) AS last_time FROM {table}"
            f" WHERE room_uuid LIKE %s GROUP BY room_uuid LIMIT {int(limit)}",
            [f"%{text}"],
        )
        for row in rows:
            uuid = str(row.get("room_uuid") or "").strip()
            # SQL 的 `LIKE '%xxxxxx'` 只保证后缀；这里再确认一眼长度与后缀，避免脏数据误伤。
            if uuid.endswith(text) and room_id_from_uuid(uuid) == text:
                found.append((int(row.get("last_time") or 0), uuid))
    found.sort(key=lambda item: item[0], reverse=True)
    return list(dict.fromkeys(uuid for _time, uuid in found))


def _parse_json_list(raw: Any) -> list[Any]:
    """把 JSON 文本解析成列表；解析不出来时返回空列表。

    `action_records` / `result` / `history` 都是历史数据，脏一行不该让整页打不开，
    与 `decode_player_name` 同一个取舍。
    """
    if isinstance(raw, list):
        return raw
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_scores(raw: Any) -> list[int]:
    """把 `t_games.result` 解析成四个座位的得分（缺项补 0，最多 4 项）。"""
    scores: list[int] = []
    for item in _parse_json_list(raw)[:ROOM_SEAT_COUNT]:
        try:
            scores.append(int(item))
        except (TypeError, ValueError):
            scores.append(0)
    while len(scores) < ROOM_SEAT_COUNT:
        scores.append(0)
    return scores


def decode_game_base_info(raw: Any) -> dict[str, Any]:
    """把 `t_games.base_info` 解析成开局快照字典（与 `decode_room_conf` 同一取舍）。"""
    return decode_room_conf(raw)


def _normalize_game(row: dict[str, Any]) -> dict[str, Any]:
    """把一行对局记录整理成视图层用的固定字段集。"""
    base_info = decode_game_base_info(row.get("base_info"))
    return {
        "room_uuid": str(row.get("room_uuid") or ""),
        "game_index": int(row.get("game_index") or 0),
        "source": str(row.get("game_source") or GAME_SOURCE_ARCHIVE),
        "create_time": int(row.get("create_time") or 0),
        "created_at": format_unix_seconds(row.get("create_time")),
        "type": str(base_info.get("type") or ""),
        "button": int(base_info.get("button") or 0),
        "result": _parse_scores(row.get("result")),
        "base_info": base_info,
        "action_records": row.get("action_records"),
    }


def _history_seat(entry: Any, index: int) -> dict[str, Any]:
    """把 `history.seats[i]` 的一节整理成与 `t_rooms` 座位同形状的一节。"""
    item = entry if isinstance(entry, dict) else {}
    return {
        "seat_index": index,
        "player_id": int(item.get("userid") or 0),
        "name": decode_player_name(item.get("name")),
        "icon": "",
        "score": int(item.get("score") or 0),
    }


def _history_entry(raw: Any, owner_id: int) -> dict[str, Any] | None:
    """把 `t_users.history` 里的一条战绩整理成固定形状；不是字典就丢弃。"""
    if not isinstance(raw, dict):
        return None
    uuid = str(raw.get(_HISTORY_UUID_KEY) or "").strip()
    if not uuid:
        return None
    seats_raw = raw.get("seats")
    seats_list = seats_raw if isinstance(seats_raw, list) else []
    seats = [
        _history_seat(seats_list[index] if index < len(seats_list) else None, index)
        for index in range(ROOM_SEAT_COUNT)
    ]
    return {
        "uuid": uuid,
        "room_id": str(raw.get("id") or ""),
        "create_time": int(raw.get("time") or 0),
        "seats": seats,
        "owner_id": owner_id,
        # 原始条目的紧凑 JSON：`_scan_history()` 用它做 Python 侧的字面量复核
        # （归一化之后 `userid` 已经改名成 `player_id`，不能拿来比对 LIKE 模式）。
        "_raw": json.dumps(raw, separators=(",", ":"), ensure_ascii=False),
    }


def parse_player_history(raw: Any, owner_id: int = 0) -> list[dict[str, Any]]:
    """把 `t_users.history` 的 JSON 文本解析成战绩条目列表（最近的在前）。

    :param raw: `t_users.history` 列的内容。
    :param owner_id: 这一行属于哪个玩家（`t_users.userid`），一并带出来。
    :return: 每条含 `uuid` / `room_id` / `create_time` / `seats` / `owner_id`。
    """
    entries = [
        entry
        for entry in (_history_entry(item, owner_id) for item in _parse_json_list(raw))
        if entry is not None
    ]
    entries.sort(key=lambda item: item["create_time"], reverse=True)
    return entries[:HISTORY_MAX_ENTRIES]


def _history_literal(pattern: str) -> str:
    """把一条 `LIKE` 模式还原成用于 Python 侧比对的字面量。

    本模块的模式只在**首尾**用 `%`，其余通配符都由 `_escape_like()` 转义过，
    所以先剥掉首尾的 `%`，再还原 `!%` / `!_` / `!!`。
    """
    return pattern.strip("%").replace("!%", "%").replace("!_", "_").replace("!!", "!")


def _scan_history(patterns: list[str]) -> list[dict[str, Any]]:
    """按 `LIKE` 模式扫 `t_users.history`，返回命中的战绩条目。

    **这是本模块唯一的一次全表扫描**（`history` 没有索引，最大 4096 字节），
    所以：模式由调用方精确构造（uuid / 房间号 / 玩家 ID / 昵称，都先过 `_escape_like`）、
    结果带 `LIMIT`、命中行还会在 Python 侧再比一次字面量，避免 `LIKE` 的大小写/通配歧义；
    模式多于 `HISTORY_SCAN_CHUNK` 个时分批查（一批一次扫描），免得拼出一条几百个 `OR` 的 SQL。

    :param patterns: 形如 `%"uuid":"1234"%` 的 `LIKE` 模式列表（转义字符是 `!`）；
        空列表直接返回空。
    """
    unique = list(dict.fromkeys(pattern for pattern in patterns if pattern))
    found: list[dict[str, Any]] = []
    for start in range(0, len(unique), HISTORY_SCAN_CHUNK):
        found.extend(_scan_history_chunk(unique[start : start + HISTORY_SCAN_CHUNK]))
    return found


def _scan_history_chunk(patterns: list[str]) -> list[dict[str, Any]]:
    """`_scan_history` 的单批实现（一批 = 一条 SQL = 一次全表扫描）。"""
    if not patterns:
        return []
    where = " OR ".join([f"history LIKE %s ESCAPE '{LIKE_ESCAPE}'"] * len(patterns))
    rows = _run(
        f"SELECT userid, history FROM {PLAYER_TABLE} WHERE {where} LIMIT {HISTORY_SCAN_LIMIT}",
        list(patterns),
    )
    literals = [_history_literal(pattern) for pattern in patterns]
    found: list[dict[str, Any]] = []
    for row in rows:
        owner_id = int(row.get("userid") or 0)
        for entry in parse_player_history(row.get("history"), owner_id):
            raw_entry = str(entry.get("_raw") or "")
            if any(literal in raw_entry for literal in literals):
                found.append(entry)
    return found


def resolve_room_uuids(keyword: str) -> list[str] | None:
    """把搜索词解析成一批房间 uuid。

    支持五种口径（与房间管理一致的运营习惯）：

    * **uuid**：15 位以上数字（存活房间查 `t_rooms.uuid`；已销毁的房间直接拿它去比对
      `room_uuid`——**这正是身份查不到时唯一还能用的搜索口径**）；
    * **房间号**：最多 8 位（存活房间查 `t_rooms.id`，已结束房间查历史战绩里的 `id`）；
    * **玩家 ID**：纯数字，查历史战绩里的 `userid`；
    * **玩家昵称**：存活房间查座位昵称（`t_rooms.user_nameN`），已销毁房间先按 Base64
      前缀在 `t_users.name` 里找玩家、再查这些玩家的历史战绩。

    :param keyword: 搜索词。
    :return: uuid 列表；`None` 表示"没有关键字，不要加这个过滤条件"，
        空列表表示"关键字解析不出任何房间"（调用方应该直接返回空结果）。
    """
    text = (keyword or "").strip()
    if not text:
        return None

    uuids: set[str] = set()
    name_b64 = _name_to_base64(text)
    is_number = text.isdigit()

    # 1) 存活房间：数字按房间号 / uuid 精确命中，其余按座位昵称匹配。
    #    刻意**不做**"像不像 ID"的前置过滤：昵称是中文，任何形态都可能出现，
    #    参数走占位符，所以让 SQL 自己去比就好（比不出来自然是空结果）。
    if is_number:
        room_rows = _run(
            f"SELECT uuid FROM {ROOM_TABLE} WHERE id = %s OR uuid = %s LIMIT 20", [text, text]
        )
    else:
        seat_clauses = " OR ".join(
            f"user_name{index} LIKE %s ESCAPE '{LIKE_ESCAPE}'" for index in range(ROOM_SEAT_COUNT)
        )
        room_rows = _run(
            f"SELECT uuid FROM {ROOM_TABLE} WHERE {seat_clauses} LIMIT 20",
            [f"%{_escape_like(name_b64)}%"] * ROOM_SEAT_COUNT,
        )
    for row in room_rows:
        uuid = str(row.get("uuid") or "").strip()
        if uuid:
            uuids.add(uuid)

    # 2) 历史战绩：按 uuid / 房间号 / 玩家 ID / 玩家昵称构造 LIKE 模式。
    #    嵌进模式里的搜索词先转义（`_scan_history` 的 SQL 带 `ESCAPE '!'`），
    #    否则昵称里的 `%` / `_` 会变成通配符。
    literal = _escape_like(text)
    patterns = [f'%"uuid":"{literal}"%']
    if is_number:
        patterns.append(f'%"userid":{int(text)},%')
        if len(text) == GAME_ROOM_ID_LENGTH:
            patterns.append(f'%"id":"{literal}"%')
            # 已销毁、又没有战绩快照的房间在 history 里查不到，只能靠 uuid 后缀反查对局表。
            uuids.update(_uuids_by_room_id(text))
        elif len(text) == GAME_UUID_LENGTH:
            # 19 位数字就是 uuid：直接拿它当候选，这样"身份查不到"的房间也能被搜出来。
            uuids.add(text)
    else:
        name_rows = _run(
            f"SELECT userid FROM {PLAYER_TABLE} WHERE name LIKE %s ESCAPE '{LIKE_ESCAPE}' LIMIT 50",
            [f"%{_escape_like(name_b64)}%"],
        )
        for row in name_rows:
            patterns.append(f'%"userid":{int(row.get("userid") or 0)},%')

    for entry in _scan_history(patterns):
        uuids.add(entry["uuid"])

    return sorted(uuids)[:GAME_UUID_FILTER_MAX]


def resolve_room_ref(room_ref: str) -> list[str]:
    """把"房间号 / uuid"定位成**候选 uuid 列表**（按可信度排序）。

    与 `resolve_room_uuids()`（列表页搜索用的宽口径）的区别：**这里绝不把纯数字
    当成玩家 ID**。房间详情 / 单局详情都是"我手上有个房间标识，帮我打开它"，
    把 6 位房间号误当成某个玩家的 ID 会翻出一堆无关房间，那是错的。

    候选顺序（调用方逐个试到有对局为止）：

    1. `t_rooms` 里 `id` 或 `uuid` 精确命中的房间（存活房间是权威）；
    2. `t_users.history` 里 `id` / `uuid` 命中的房间（已销毁的房间，取战绩最新的一条）；
    3. 6 位房间号按**uuid 后缀**反查对局表（已销毁且没有战绩快照的房间只能这样找）；
    4. 入参本身就是 uuid 时（19 位数字），直接把它当 uuid 试一次。

    :param room_ref: 房间号或 uuid（调用方已校验形态）。
    :return: 去重后的候选 uuid 列表；解析不出来时是空列表（调用方返回 14001）。
    """
    text = (room_ref or "").strip()
    if not text:
        return []

    candidates: list[str] = []

    def add(uuid: Any) -> None:
        value = str(uuid or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    for row in _run(
        f"SELECT uuid FROM {ROOM_TABLE} WHERE id = %s OR uuid = %s LIMIT 20", [text, text]
    ):
        add(row.get("uuid"))

    patterns = [f'%"uuid":"{text}"%']
    if len(text) <= GAME_ROOM_ID_LENGTH:
        patterns.append(f'%"id":"{text}"%')
    entries = _scan_history(patterns)
    if entries:
        newest = max(entries, key=lambda item: item["create_time"])
        add(newest["uuid"])

    if text.isdigit() and len(text) == GAME_ROOM_ID_LENGTH:
        for uuid in _uuids_by_room_id(text):
            add(uuid)

    if text.isdigit() and len(text) == GAME_UUID_LENGTH:
        add(text)

    return candidates


def resolve_room_identities(uuids: list[str]) -> dict[str, dict[str, Any]]:
    """把一批房间 uuid 解析成"房间号 + 四个座位"。

    两条数据来源，**存活房间优先**（`t_rooms` 是权威，还带玩法配置）：

    1. `t_rooms`（房间还没销毁）——按 uuid 精确查，索引命中；
    2. `t_users.history`（房间已销毁）——一次全表扫把所有 uuid 一起捞出来
       （见 `_scan_history`）。

    两处都没有的房间（玩家只打了一局就散场）返回空字典里的"未知座位"，
    由上层决定怎么显示，不在这里编造。

    :param uuids: 房间 uuid 列表（调用方已去重）。
    :return: `uuid → {"room_id", "room_type", "seats", "live", "identity_source"}`；
        `identity_source` 是 `"rooms"`（存活房间表）/ `"history"`（历史战绩）/
        `"unknown"`（两处都没查到）；座位固定 4 项，查不到身份时 `player_id` 为 0、`name` 为空串。
    """
    wanted = sorted({str(uuid).strip() for uuid in uuids if str(uuid).strip()})
    resolved: dict[str, dict[str, Any]] = {}
    if not wanted:
        return resolved

    seat_columns = ", ".join(
        f"user_id{index}, user_icon{index}, user_name{index}, user_score{index}"
        for index in range(ROOM_SEAT_COUNT)
    )
    rows = _run(
        f"SELECT uuid, id, base_info, {seat_columns} FROM {ROOM_TABLE}"
        f" WHERE uuid IN ({_placeholders(len(wanted))})",
        list(wanted),
    )
    for row in rows:
        uuid = str(row.get("uuid") or "").strip()
        if not uuid:
            continue
        resolved[uuid] = {
            "room_id": str(row.get("id") or ""),
            "room_type": str(decode_room_conf(row.get("base_info")).get("type") or ""),
            "seats": [_normalize_seat(row, index) for index in range(ROOM_SEAT_COUNT)],
            "live": True,
            "identity_source": GAME_IDENTITY_ROOMS,
        }

    missing = [uuid for uuid in wanted if uuid not in resolved]
    if missing:
        for entry in _scan_history([f'%"uuid":"{uuid}"%' for uuid in missing]):
            resolved.setdefault(
                entry["uuid"],
                {
                    # 战绩里的 `id` 是权威；个别老数据缺这个键时再从 uuid 反推。
                    "room_id": entry["room_id"] or room_id_from_uuid(entry["uuid"]),
                    "room_type": "",
                    "seats": entry["seats"],
                    "live": False,
                    "identity_source": GAME_IDENTITY_HISTORY,
                },
            )

    for uuid in wanted:
        resolved.setdefault(
            uuid,
            {
                # 玩家身份查不到，但**房间号还能从 uuid 反推**（19 位 = 13 位毫秒 + 6 位房间号），
                # 所以列表里不会出现"没有房间号"的一行。
                "room_id": room_id_from_uuid(uuid),
                "room_type": "",
                "seats": _unknown_seats(),
                "live": False,
                "identity_source": GAME_IDENTITY_UNKNOWN,
            },
        )
    return resolved


def _unknown_seats() -> list[dict[str, Any]]:
    """四个"未知玩家"座位（身份查不到时的占位，`player_id` 为 0）。"""
    return [
        {"seat_index": index, "player_id": 0, "name": "", "icon": "", "score": 0}
        for index in range(ROOM_SEAT_COUNT)
    ]


def _game_where_clause(
    *,
    uuids: list[str] | None,
    game_type: str,
    created_from: int | None,
    created_to: int | None,
) -> tuple[str, list[Any]]:
    """拼对局记录的 `WHERE` 子句（两张表通用）。

    :param uuids: 允许的 uuid 列表；`None` 表示不限制（调用方保证空列表不会走到这里）。
    :param game_type: 玩法标识，空串表示不过滤。
    :param created_from: 起始时间（Unix 秒，含）；`None` 表示不限。
    :param created_to: 结束时间（Unix 秒，含）；`None` 表示不限。
    """
    parts: list[str] = []
    params: list[Any] = []

    if uuids is not None:
        ids = sorted({str(uuid) for uuid in uuids if str(uuid)})
        if not ids:
            return " WHERE 1 = 0", []
        parts.append(f"room_uuid IN ({_placeholders(len(ids))})")
        params.extend(ids)

    if game_type:
        # `base_info` 是紧凑 JSON 且 `type` 是第一个键（见 `utils/db._conf_to_wire`）。
        parts.append("base_info LIKE %s ESCAPE '!'")
        params.append(f'%"type":"{_escape_like(game_type)}"%')

    if created_from is not None:
        parts.append("create_time >= %s")
        params.append(int(created_from))
    if created_to is not None:
        parts.append("create_time <= %s")
        params.append(int(created_to))

    if not parts:
        return "", []
    return " WHERE " + " AND ".join(parts), params


def _game_union(
    *,
    uuids: list[str] | None,
    game_type: str,
    created_from: int | None,
    created_to: int | None,
    columns: str,
    tail: str,
) -> tuple[str, list[Any]]:
    """拼"两张表 `UNION ALL` + 排序/分页"的 SQL。

    :param columns: `SELECT` 的列（两张表列名一致）。
    :param tail: `ORDER BY ... LIMIT ...` 之类的尾巴（调用方拼好的白名单片段）。
    :return: `(sql, params)`。
    """
    selects: list[str] = []
    params: list[Any] = []
    for table, source in GAME_TABLE_SOURCES:
        where, where_params = _game_where_clause(
            uuids=uuids,
            game_type=game_type,
            created_from=created_from,
            created_to=created_to,
        )
        selects.append(f"SELECT '{source}' AS game_source, {columns} FROM {table}{where}")
        params.extend(where_params)
    return " UNION ALL ".join(selects) + tail, params


def game_overview(*, recent_seconds: int = 24 * 3600) -> dict[str, int]:
    """对局概览：归档局数 / 在局局数 / 最近一段时间的新局数与房间数。

    :param recent_seconds: "最近"的窗口，默认 24 小时（`create_time` 是秒）。
    """
    threshold = int(time.time()) - max(int(recent_seconds), 0)
    sql, params = _game_union(
        uuids=None,
        game_type="",
        created_from=None,
        created_to=None,
        columns="room_uuid, create_time",
        tail="",
    )
    rows = _run(
        "SELECT"
        " SUM(CASE WHEN game_source = %s THEN 1 ELSE 0 END) AS archived_games,"
        " SUM(CASE WHEN game_source = %s THEN 1 ELSE 0 END) AS live_games,"
        " SUM(CASE WHEN create_time >= %s THEN 1 ELSE 0 END) AS games_last_24h,"
        " COUNT(DISTINCT CASE WHEN create_time >= %s THEN room_uuid END) AS rooms_last_24h"
        f" FROM ({sql}) AS merged_games",
        [GAME_SOURCE_ARCHIVE, GAME_SOURCE_LIVE, threshold, threshold, *params],
    )
    row = rows[0] if rows else {}
    total = int(row.get("archived_games") or 0) + int(row.get("live_games") or 0)
    return {
        "total_games": total,
        "archived_games": int(row.get("archived_games") or 0),
        "live_games": int(row.get("live_games") or 0),
        "games_last_24h": int(row.get("games_last_24h") or 0),
        "rooms_last_24h": int(row.get("rooms_last_24h") or 0),
    }


def search_games(
    *,
    keyword: str = "",
    game_type: str = "",
    source: str = GAME_SOURCE_ALL,
    created_from: int | None = None,
    created_to: int | None = None,
    ordering: str = GAME_DEFAULT_ORDERING,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """按条件分页查询对局记录（两张表一起查）。

    :param keyword: 房间 uuid / 房间号 / 玩家 ID / 玩家昵称，空串表示不过滤。
    :param game_type: 玩法标识，空串表示不过滤。
    :param source: `GAME_SOURCE_*` 之一。
    :param created_from: 起始时间（Unix 秒，含）。
    :param created_to: 结束时间（Unix 秒，含）。
    :param ordering: `GAME_ORDERING_CHOICES` 里的键（调用方已用序列化器校验过）。
    :param page: 页码，从 1 开始。
    :param page_size: 每页条数。
    :return: `(当前页对局列表, 过滤后的总条数)`。
    """
    uuids = resolve_room_uuids(keyword)
    if uuids is not None and not uuids:
        # 关键字解析不出任何房间：直接给空结果，不去扫两张表。
        return [], 0

    active = [table for table, source_id in GAME_TABLE_SOURCES if source in (GAME_SOURCE_ALL, source_id)]
    if not active:
        return [], 0

    selects: list[str] = []
    params: list[Any] = []
    for table, source_id in GAME_TABLE_SOURCES:
        if table not in active:
            continue
        where, where_params = _game_where_clause(
            uuids=uuids,
            game_type=game_type,
            created_from=created_from,
            created_to=created_to,
        )
        selects.append(
            f"SELECT '{source_id}' AS game_source, {GAME_COLUMNS} FROM {table}{where}"
        )
        params.extend(where_params)
    union_sql = " UNION ALL ".join(selects)

    count_rows = _run(f"SELECT COUNT(*) AS total FROM ({union_sql}) AS merged_games", list(params))
    total = int(count_rows[0]["total"]) if count_rows else 0
    if total == 0:
        return [], 0

    order_sql = GAME_ORDERING_CHOICES.get(ordering, GAME_ORDERING_CHOICES[GAME_DEFAULT_ORDERING])
    offset = max(page - 1, 0) * page_size
    rows = _run(f"{union_sql} ORDER BY {order_sql} LIMIT %s OFFSET %s", [*params, page_size, offset])
    return [_normalize_game(row) for row in rows], total


def get_room_games(room_uuid: str) -> list[dict[str, Any]]:
    """取一个房间的全部对局（按局号升序；跨两张表）。

    一个房间的局数上限是 `conf.maxGames`（4 或 8），所以这里不分页、一次取完。
    """
    text = (room_uuid or "").strip()
    if not text:
        return []
    sql, params = _game_union(
        uuids=[text],
        game_type="",
        created_from=None,
        created_to=None,
        columns=GAME_COLUMNS,
        tail=" ORDER BY game_index ASC",
    )
    return [_normalize_game(row) for row in _run(sql, params)]


def get_game(room_uuid: str, game_index: int) -> dict[str, Any] | None:
    """取某一局（`room_uuid` + `game_index`）；不存在时返回 `None`。

    归档表优先：同一局同时出现在两张表里只可能是 `archive_games()` 搬迁途中的一瞬间，
    此时归档表那一行才是"最终形态"。
    """
    text = (room_uuid or "").strip()
    if not text:
        return None
    for table, source in GAME_TABLE_SOURCES:
        rows = _run(
            f"SELECT '{source}' AS game_source, {GAME_COLUMNS} FROM {table}"
            " WHERE room_uuid = %s AND game_index = %s LIMIT 1",
            [text, int(game_index)],
        )
        if rows:
            return _normalize_game(rows[0])
    return None


def count_games_by_room(uuids: list[str]) -> dict[str, int]:
    """统计每个房间的对局条数（一次查询覆盖所有 uuid）。"""
    wanted = sorted({str(uuid).strip() for uuid in uuids if str(uuid).strip()})
    if not wanted:
        return {}
    sql, params = _game_union(
        uuids=wanted,
        game_type="",
        created_from=None,
        created_to=None,
        columns="room_uuid",
        tail="",
    )
    rows = _run(
        f"SELECT room_uuid, COUNT(*) AS total FROM ({sql}) AS merged_games GROUP BY room_uuid",
        params,
    )
    return {str(row["room_uuid"]): int(row["total"] or 0) for row in rows}


def player_history_entries(player_id: int) -> list[dict[str, Any]] | None:
    """按玩家 ID 取他的战绩条目（`t_users.history`）。

    :param player_id: `t_users.userid`。
    :return: 战绩条目列表（最近的在前，最多 10 条）；玩家不存在时 `None`。
    """
    rows = _run(
        f"SELECT userid, history FROM {PLAYER_TABLE} WHERE userid = %s LIMIT 1",
        [int(player_id)],
    )
    if not rows:
        return None
    return parse_player_history(rows[0].get("history"), int(rows[0].get("userid") or 0))
