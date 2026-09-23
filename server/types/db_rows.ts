/**
 * 数据库行结构（`utils/db.ts` 的查询结果类型）。
 *
 * 权威来源是 `repo:server/sql/db_babykylin.sql` 与 `utils/db.ts` 里的 SQL 语句。
 * 这里按"SQL 实际读写的列"给出结构，不照抄整张表：例如 `get_user_data` 只 SELECT 少数列，
 * 就用 `UserBriefRow` 描述，避免调用方以为自己拿到了 `history`。
 *
 * 迁移说明：`mysql2` 对 INT 列返回 `number`、VARCHAR 列返回 `string`、允许 NULL 的列返回 `null`，
 * 下面的类型按这个规则标注。老代码用 `!= null` 判断是否存在，因此可空列必须显式写 `| null`。
 */

/** `t_accounts` 行（`SELECT *`）。 */
export interface AccountRow {
  account: string;
  password: string;
}

/** `t_users` 行（`SELECT *`）。 */
export interface UserRow {
  userid: number;
  account: string;
  name: string | null;
  sex: number | null;
  headimg: string | null;
  lv: number;
  exp: number;
  coins: number;
  gems: number;
  roomid: string | null;
  history: string;
}

/** `get_user_data` / `get_user_data_by_userid` 显式 SELECT 的那几列。 */
export interface UserBriefRow {
  userid: number;
  account: string;
  name: string | null;
  lv: number;
  exp: number;
  coins: number;
  gems: number;
  roomid: string | null;
}

/** `get_user_base_info` 的三列（`name, sex, headimg`）。 */
export interface UserBaseInfoRow {
  name: string | null;
  sex: number | null;
  headimg: string | null;
}

/** `t_rooms` 行（`SELECT *`）。 */
export interface RoomRow {
  uuid: string;
  id: string;
  base_info: string;
  create_time: number;
  num_of_turns: number;
  next_button: number;
  user_id0: number;
  user_icon0: string;
  user_name0: string;
  user_score0: number;
  user_id1: number;
  user_icon1: string;
  user_name1: string;
  user_score1: number;
  user_id2: number;
  user_icon2: string;
  user_name2: string;
  user_score2: number;
  user_id3: number;
  user_icon3: string;
  user_name3: string;
  user_score3: number;
  ip: string | null;
  port: number | null;
}

/** `t_rooms` 只取地址时的两列（`get_room_addr`）。 */
export interface RoomAddrRow {
  ip: string | null;
  port: number | null;
}

/** `t_games` / `t_games_archive` 行（两表结构相同）。 */
export interface GameRow {
  room_uuid: string;
  game_index: number;
  base_info: string;
  create_time: number;
  snapshots: string | null;
  action_records: string | null;
  result: string | null;
}

/** `t_message` 行（`SELECT *`）。 */
export interface MessageRow {
  type: string;
  msg: string;
  version: string;
}
