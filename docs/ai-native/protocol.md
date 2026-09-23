# Socket.IO 协议全景

本文是 `repo:docs/ai-native/` 参考文档之一，面向人与 AI 的长期事实来源。
**§1 的推送事件表受门禁保护**：`npm run check:protocol` 既比对源码两侧
（服务端推送 vs 客户端处理器），也校验 §1 表格与**服务端源码**一致——
服务端有推送而表里没写、或表里有而服务端没推送，都会报红。
（§2 的客户端事件表不在保护范围内，它记录的是 `socket.on` 注册；改这些事件名请人工同步本表。）

- 方向：§1 全部为 **服务端 → 客户端**（客户端主动请求的事件见 §2）。
- 「作用域」：`房间广播` = 同房间所有座位；`单人` = 指定 `userId`。
- 客户端侧的注册**绝大多数**在 `repo:client/assets/scripts/GameNetMgr.js` 里经
  `cc.vv.net.addHandler(event, fn)` 完成。两个例外见 §4：`push_need_create_role` 注册在
  `components/Login.js`，`game_pong` 由 `Net.js` 直接 `sio.on` 处理。

---

## 1. 服务端推送事件（39 个）

| 事件 | 作用域 | 服务端发出方式 |
| --- | --- | --- |
| `chat_push` | 房间广播 | `broacastInRoom` |
| `dispress_push` | 房间广播 | `broacastInRoom` |
| `dissolve_cancel_push` | 房间广播 | `broacastInRoom` |
| `dissolve_notice_push` | 房间广播 + 单人 | `broacastInRoom` / `sendMsg` |
| `emoji_push` | 房间广播 | `broacastInRoom` |
| `exit_notify_push` | 房间广播 | `broacastInRoom` |
| `exit_result` | 单人（登录 socket） | `socket.emit` |
| `game_action_push` | 单人 | `sendMsg` |
| `game_begin_push` | 单人 | `sendMsg` |
| `game_chupai_notify_push` | 房间广播 | `broacastInRoom` |
| `game_chupai_push` | 房间广播 | `broacastInRoom` |
| `game_dingque_finish_push` | 房间广播 | `broacastInRoom` |
| `game_dingque_notify_push` | 房间广播 | `broacastInRoom` |
| `game_dingque_push` | 单人 | `sendMsg` |
| `game_holds_push` | 单人 | `sendMsg` |
| `game_huanpai_over_push` | 单人 | `sendMsg` |
| `game_huanpai_push` | 单人 | `sendMsg` |
| `game_mopai_push` | 单人 | `sendMsg` |
| `game_num_push` | 单人 | `sendMsg` |
| `game_over_push` | 房间广播 | `broacastInRoom` |
| `game_playing_push` | 房间广播 | `broacastInRoom` |
| `game_pong` | 单人（登录 socket） | `socket.emit` |
| `game_sync_push` | 单人 | `sendMsg` |
| `gang_notify_push` | 房间广播 | `broacastInRoom` |
| `guo_notify_push` | 房间广播 | `broacastInRoom` |
| `guo_result` | 单人 | `sendMsg` |
| `guohu_push` | 单人 | `sendMsg` |
| `hangang_notify_push` | 房间广播 | `broacastInRoom` |
| `hu_push` | 房间广播 | `broacastInRoom` |
| `huanpai_notify` | 单人 | `sendMsg` |
| `login_finished` | 单人（登录 socket） | `socket.emit` |
| `login_result` | 单人（登录 socket） | `socket.emit` |
| `mj_count_push` | 房间广播 + 单人 | `broacastInRoom` / `sendMsg` |
| `new_user_comes_push` | 房间广播 | `broacastInRoom` |
| `peng_notify_push` | 房间广播 | `broacastInRoom` |
| `quick_chat_push` | 房间广播 | `broacastInRoom` |
| `user_ready_push` | 房间广播 | `broacastInRoom` |
| `user_state_push` | 房间广播 | `broacastInRoom` |
| `voice_msg_push` | 房间广播 | `broacastInRoom` |
已确认：客户端对上述 39 个事件**全部**有对应处理器（`npm run check:protocol` 会双向验证）。

---

## 2. 客户端 → 服务端：对局事件

全部在 `repo:server/game_server/socket_service.ts` 里以 `socket.on(...)` 注册。
除 `login` 外都要求已登录（`socket.userId != null`），否则静默忽略。

| 事件 | 数据 | 说明 |
| --- | --- | --- |
| `login` | `{token, roomid, time, sign}` | 进房握手；校验 `md5(roomid+token+time+ROOM_PRI_KEY)` 与 token 时效 |
| `ready` | — | 准备 / 取消准备 |
| `huanpai` | `{p1, p2, p3}` | 换三张（仅 `hsz` 开启的房间） |
| `dingque` | 花色 `0/1/2` | 定缺（筒/条/万） |
| `chupai` | 牌 id `0–26` | 出牌 |
| `peng` | — | 碰 |
| `gang` | — | 杠 |
| `hu` | — | 胡 |
| `guo` | — | 过（放弃碰杠胡） |
| `chat` | 文本 | 房间内文字聊天 |
| `quick_chat` | 索引 | 快捷语 |
| `voice_msg` | 语音数据 | 语音消息 |
| `emoji` | 索引 | 表情 |
| `exit` | — | 退出房间 |
| `dispress` | — | 解散房间（发起） |
| `dissolve_request` | — | 申请解散 |
| `dissolve_agree` | — | 同意解散 |
| `dissolve_reject` | — | 拒绝解散 |
| `game_ping` | — | 心跳；服务端回 `game_pong` |
| `disconnect` | — | 连接断开（socket.io 内置） |

---

## 3. HTTP 接口（不在本检查覆盖范围内）

协议检查只覆盖 Socket.IO。HTTP 接口分布在三处，各自独立演进：

| 归属 | 文件 | 主要路径 |
| --- | --- | --- |
| 账号服 | `repo:server/account_server/account_server.ts` | `/guest`、`/register`、登录 |
| 账号服（代理） | `repo:server/account_server/dealer_api.ts` | `/get_user_info` 等 |
| 大厅服 | `repo:server/hall_server/client_service.ts` | `/login`、`/create_user`、`/create_private_room`、`/enter_private_room`、`/get_history_list`、`/get_games_of_room`、`/get_detail_of_game`、`/get_user_status`、`/get_message` |
| 游戏服（内部） | `repo:server/game_server/http_service.ts` | `/get_server_info`、`/create_room`、`/enter_room`、`/is_room_runing`（**四个都校验 `sign`**；`/get_server_info` 用 `md5(serverid + ROOM_PRI_KEY)`） |

**HTTP 路径的增删不会让门禁报红。** 改这些接口时请人工双向搜索调用方
（客户端搜 `cc.vv.http.sendRequest`，服务端搜 `http.send` / `res.send`）。
注意客户端 `HTTP.js` **只用 GET**，参数走 query string。

返回结构也不统一：大厅服与游戏服走 `utils/http.ts` 的 `send()`（`{errcode, errmsg, data}`），
账号服的两个文件各自定义本地 `send(res, ret)` 直接 `res.send`。

---

## 4. 已知的协议债务

| 项 | 状态 |
| --- | --- |
| `push_need_create_role` | 客户端注册了处理器（在 `components/Login.js`，**不在 `GameNetMgr.js`**），但**服务端从不推送**。已列入 `KNOWN_UNSENT`，属于待清理的死代码；删除会影响登录分支，需产品确认。 |
| 客户端 `connect` / `disconnect` / `reconnect` / `connect_failed` | socket.io 自身的连接事件，非业务推送，检查中排除。 |
| `game_pong` | 不走 `addHandler`，由 `repo:client/assets/scripts/Net.js` 直接 `sio.on` 处理并计算延迟。检查已覆盖该注册路径。 |
| 直连 `socket.emit` | `repo:server/game_server/socket_service.ts` 里有 7 处（`login_result`×4、`login_finished`、`exit_result`、`game_pong`），全部在登录/连接阶段。**检查能扫到它们**，不要以为门禁看不见。 |

---

## 5. 新增推送事件的正确做法

见 `repo:.dsh/skills/server-architecture/SKILL.md` §4。要点复述：

1. 服务端：对局内推送用 `userMgr.sendMsg` / `userMgr.broacastInRoom`；连接阶段的推送可以像既有代码
   那样直接 `socket.emit`。两种写法门禁都能扫到。
2. 客户端在 `GameNetMgr.js` 里 `addHandler` + `dispatchEvent`，组件里 `this.node.on` 订阅。
3. 跑 `npm run check:protocol`。
4. 更新本文 §1 的表格；忘了也不要紧——`npm run check:protocol` 会报红提醒你。
