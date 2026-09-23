"""数据库行结构（`utils/db.py` 查询结果的结构描述）。

对应 `server/types/db_rows.ts`。权威来源是 `repo:server/sql/db_babykylin.sql`
与 `utils/db.py` 里的 SQL 语句。这里按"SQL 实际读写的列"给出结构，不照抄整张表：
例如 `get_user_data` 只 SELECT 少数列，就用 `UserBriefRow` 描述，
避免调用方以为自己拿到了 `history`。

aiomysql 对 INT 列返回 `int`、VARCHAR 列返回 `str`、允许 NULL 的列返回 `None`；
下面的类型按这个规则标注。老代码用 `!= null` 判断是否存在，因此可空列显式写 `| None`。
"""

from typing import TypedDict


class AccountRow(TypedDict):
    """`t_accounts` 行（`SELECT *`）。"""

    account: str
    password: str


class UserRow(TypedDict):
    """`t_users` 行（`SELECT *`）。"""

    userid: int
    account: str
    name: str | None
    sex: int | None
    headimg: str | None
    lv: int
    exp: int
    coins: int
    gems: int
    roomid: str | None
    history: str


class UserBriefRow(TypedDict):
    """`get_user_data` / `get_user_data_by_userid` 显式 SELECT 的那几列。"""

    userid: int
    account: str
    name: str | None
    lv: int
    exp: int
    coins: int
    gems: int
    roomid: str | None


class UserBaseInfoRow(TypedDict):
    """`get_user_base_info` 的三列（`name, sex, headimg`）。"""

    name: str | None
    sex: int | None
    headimg: str | None


class RoomRow(TypedDict):
    """`t_rooms` 行（`SELECT *`）。"""

    uuid: str
    id: str
    base_info: str
    create_time: int
    num_of_turns: int
    next_button: int
    user_id0: int
    user_icon0: str
    user_name0: str
    user_score0: int
    user_id1: int
    user_icon1: str
    user_name1: str
    user_score1: int
    user_id2: int
    user_icon2: str
    user_name2: str
    user_score2: int
    user_id3: int
    user_icon3: str
    user_name3: str
    user_score3: int
    ip: str | None
    port: int | None


class RoomAddrRow(TypedDict):
    """`t_rooms` 只取地址时的两列（`get_room_addr`）。"""

    ip: str | None
    port: int | None


class GameRow(TypedDict):
    """`t_games` / `t_games_archive` 行（两表结构相同）。"""

    room_uuid: str
    game_index: int
    base_info: str
    create_time: int
    snapshots: str | None
    action_records: str | None
    result: str | None


class MessageRow(TypedDict):
    """`t_message` 行（`SELECT *`）。"""

    type: str
    msg: str
    version: str
