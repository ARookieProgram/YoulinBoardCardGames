"""玩家库（`db_scmj`）的**只读**数据源。

为什么需要它
------------

玩家管理要展示 `t_users` 里的账号、昵称、房卡（`gems`）与金币，还要支持
"按账号 / 昵称 / ID 搜索 + 分页"。游戏服现有的 HTTP 接口只能**按 account 取单个玩家**
（大厅服 `/login`、渠道 API `/get_user_info`），没有列表能力，所以按
`../AGENTS.md` §2 第 5 条开一条**只读数据源**。

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

`t_users.name` 入库前做过 Base64 编码（见 `utils/db.py` 的 `create_user`），
所以读出来必须解码再展示；解不出来就按原文返回（历史数据可能有例外）。
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from typing import Any, Final

from django.db import DatabaseError, connections
from django.db.utils import ConnectionDoesNotExist, ImproperlyConfigured

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
