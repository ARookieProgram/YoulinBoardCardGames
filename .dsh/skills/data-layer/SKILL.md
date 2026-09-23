---
name: data-layer
description: The MySQL schema and the db.js access layer of this project - table purposes, seat column layout, the callback API, and how to add a query or change the schema. Use when changing persistence, adding a db.js function, editing the SQL schema, or debugging data written by the server.
---

# 数据层（MySQL + db.js）

所有持久化都经过**同一个文件**：`repo:server/utils/db.js`（约 750 行，导出 35 个函数）。
Schema 的权威定义在 `repo:server/sql/db_babykylin.sql`。

## 什么时候用

- 新增/修改数据库读写。
- 增删表或字段。
- 排查"数据没写进去 / 读出来是乱码"。

## 1. 表结构

库名 `db_scmj`（配置项 `configs.mysql().DB`）。

| 表 | 主键 | 用途 |
| --- | --- | --- |
| `t_accounts` | `account` | 账号与密码（密码经 `crypto.md5`） |
| `t_guests` | `guest_account` | 游客账号 |
| `t_users` | `userid` (AUTO_INCREMENT) | 玩家资料：`account`、`name`、`sex`、`headimg`、`lv`、`exp`、`coins`、`gems`、`roomid`、`history` |
| `t_rooms` | `uuid` | 房间状态：`id`（8 位房号，UNIQUE）、`base_info`（玩法配置 JSON）、`num_of_turns`、`next_button`、`ip`、`port` + 4 组座位列 |
| `t_games` | `(room_uuid, game_index)` | 进行中的每一局：`base_info`、`snapshots`、`action_records`、`result` |
| `t_games_archive` | `(room_uuid, game_index)` | 与 `t_games` 同构；房间结束时由 `archive_games` 归档 |
| `t_message` | `type` | 公告/消息，按 `version` 做客户端增量拉取 |

**`t_rooms` 的座位是"宽表"**：每个座位 4 列，共 16 列。

```
user_id0   user_icon0   user_name0   user_score0
user_id1   user_icon1   user_name1   user_score1
user_id2   user_icon2   user_name2   user_score2
user_id3   user_icon3   user_name3   user_score3
```

`user_idN = 0` 表示该座位为空。`user_nameN` 以 Base64 存储（见 §4）。
取座位数据时是在 `db.js` 里拼 `user_id + seatIndex` 这类列名，**座位索引 0–3 与"东南西北"直接对应**。

注意 `t_games.action_records` 只有 `varchar(2048)`，回放数据超长会被截断——动作常量只能追加、
不能改值，否则历史回放会解析错。

## 2. 连接池与调用风格

```js
// 进程启动时（app.js 里）必须先 init，否则 pool 为 null
var db = require('../utils/db');
db.init(configs.mysql());
```

- `db.init(config)` 用 `mysql.createPool` 建池，参数来自 `configs.mysql()`：
  `HOST`、`USER`、`PSWD`、`DB`、`PORT`。
- 所有查询函数是**回调风格**：`db.xxx(args..., function(err, data){ ... })`，**没有 Promise**。
  不要用 `await`，也不要为它加 Promise 包装——整个服务端是回调驱动的。
- 每个查询内部 `pool.getConnection` → `conn.query` → `conn.release()`。
  **新增函数必须确保连接被释放**，否则池会被耗尽。
- `db.query(sql, callback)` 导出的是裸查询，仅作为逃生口；业务代码优先用语义函数。

常用函数分组：

| 分组 | 函数 |
| --- | --- |
| 账号 | `is_account_exist`、`create_account`、`get_account_info` |
| 用户 | `is_user_exist`、`create_user`、`get_user_data`、`get_user_data_by_userid`、`get_user_base_info`、`update_user_info` |
| 货币 | `get_gems`、`add_user_gems`、`cost_gems` |
| 战绩 | `get_user_history`、`update_user_history`、`get_games_of_room`、`get_detail_of_game` |
| 房间 | `is_room_exist`、`create_room`、`get_room_data`、`get_room_addr`、`get_room_uuid`、`set_room_id_of_user`、`get_room_id_of_user`、`update_seat_info`、`update_num_of_turns`、`update_next_button`、`delete_room` |
| 牌局 | `create_game`、`update_game_action_records`、`update_game_result`、`delete_games`、`archive_games` |
| 消息 | `get_message` |

## 3. 新增一个查询的步骤

1. 在 `repo:server/utils/db.js` 里按既有风格加函数：
   ```js
   exports.get_something = function(arg, callback){
       callback = callback == null ? nop : callback;   // 沿用 nop 兜底
       pool.getConnection(function(err, conn){
           if(err){ callback(err, null); return; }
           conn.query("SELECT ... WHERE x = ?", [arg], function(qerr, vals){
               conn.release();
               callback(qerr, vals);
           });
       });
   };
   ```
2. **必须用 `?` 占位符传参**，不要拼字符串——现有代码已这么做，拼接会引入注入风险。
3. 如果涉及新字段/新表，同步改 `repo:server/sql/db_babykylin.sql`。
4. 调用方只 `require('../utils/db')`，**不要**在业务代码里 `require('mysql2')` 或写 SQL。

`repo:server/tests/dbtest.js` 是历史手工脚本（会连库、只打印），**不要当作测试**，
也不要在门禁里执行。

## 4. 用户名与 Base64

玩家的 `name` 在写库前经 `crypto.toBase64`，读出后经 `crypto.fromBase64`（`db.js` 内部处理，
业务代码不需要关心）。`repo:server/utils/crypto.js` 的这两个函数在 2026-09 被改为
`Buffer.from(...)`（原先的 `new Buffer()` 在当前 Node 上会打印弃用告警），
UTF-8 非 ASCII 昵称的往返行为已由 `npm run check:smoke` 断言覆盖：

```bash
npm run check:smoke   # 含 "crypto base64 round-trips non-ASCII player names"
```

## 5. 约束与验证

- **不要期待能连库跑通**：需要真实 MySQL 实例与正确的 `configs_*.js` 凭据。
  不要把凭据改成自己的然后提交。
- 无法离线验证 SQL 的**执行结果**；能离线验证的只有语法（`npm run check:syntax`）。
- 改了 `t_games` / `t_games_archive` 的结构，必须同时考虑**历史数据兼容**：
  这两张表是长生命周期的，旧行不会迁移。
- 交付说明里若涉及未连库验证的 SQL，请明确写出"未运行时验证"。
