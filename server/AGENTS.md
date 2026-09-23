# AGENTS.md — 服务端（Node.js 三进程）

本文件在根级 `AGENTS.md` 之上叠加，仅覆盖服务端相关内容。冲突时以本文件为准。

---

## 1. 目录与职责

```
server/
├─ configs_mac.js / configs_win.js   ← 唯一配置来源（函数式导出，两个平台各一份）
├─ start_all.sh / start_all_mac.sh   ← nohup 方式拉起三个进程
├─ package.json / yarn.lock          ← 依赖清单与锁文件（yarn 1.x 是唯一依赖管理方式）
├─ account_server/                   ← 账号服 :9000，含 dealer_api :12581
├─ hall_server/                      ← 大厅服 :9001（客户端）、:9002（游戏服上报）
├─ game_server/                      ← 游戏服 :10000（Socket.IO）、:9003（HTTP）
├─ utils/                            ← db.js / http.js / crypto.js 共享层
├─ sql/db_babykylin.sql              ← 建表与初始数据（权威 schema）
├─ tests/                            ← 2016 年的手工脚本，**不是自动化测试**
└─ node_modules/                     ← 安装产物，**不提交**（server/.gitignore 已忽略）
```

每个进程入口都通过 `process.argv[2]` 读取配置文件：

```bash
node game_server/app.js ../configs_mac.js
```

**`configs_mac.js` 与 `configs_win.js` 必须同步修改**，并且注意 `configs_mac.js` 带有 BOM
（首行是 `\ufeffvar HALL_IP`），编辑时不要把它弄丢。

### 1.1 依赖管理：yarn 1.x

服务端依赖用 **yarn** 管理，`repo:server/package.json` 声明、`repo:server/yarn.lock` 锁定：

```bash
cd server
yarn install --frozen-lockfile   # 按锁文件安装（CI / 换机时用这个）
yarn install                     # 改了依赖才用；会更新 yarn.lock
yarn add <pkg>                   # 新增依赖，不要手改 package.json 后不更新锁文件
```

- **`node_modules` 不再提交**（历史上曾把整个目录提交进 git），由 `repo:server/.gitignore` 忽略。
  锁文件才是唯一依据；`package-lock.json` 也已被忽略，不要把它提交回来。
- 直接依赖只有 5 个：`express`、`fibers`、`log4js`、`mysql`、`socket.io`。
  代码里实际 `require` 的是前 4 个加 `socket.io`；**`log4js` 目前没有任何引用**，
  仅为历史遗留而保留声明。
- 锁文件里是 yarn 解析出的版本，与 2016 年那套 node_modules 里的版本**不同**
  （express 4.14.0 → 4.22.x、socket.io 1.4.6 → 1.7.x、mysql 2.11.1 → 2.18.x、
  log4js 1.0.1 → 1.1.x）。这四个包在 Node 24 上 `require` 与建 Express app 均已实测通过；
  但**整套服务没有运行时验证**——游戏服/大厅服会先加载 `fibers`，账号服直接依赖它，
  在当前 Node 上 `require('fibers')` 就抛 "Missing binary"（§7.1）。
- `yarn install` 默认会执行 `fibers` 的 install 脚本（`node build.js`）去编译原生扩展。
  当前 Node 上这一步不会成功（fibers 1.0.15 只支持到 node 8 左右）；
  用 `--ignore-scripts` 可以只装 JS 依赖，但账号服依然无法启动。
- 锁文件里的 `resolved` 统一指向 `https://registry.npmjs.org`。
  若你本机配了国内镜像，请显式指定仓库再更新锁文件，否则会把镜像地址写进锁文件：
  `yarn install --registry https://registry.npmjs.org`

`package.json` 里还提供了三个进程的启动脚本（等价于 `node app.js ../configs_mac.js`）：
`yarn account` / `yarn hall` / `yarn game`；`start_all*.sh` 与 `*.bat` 保持原先直接 `node` 的写法不变。

---

## 2. 三个进程各自做什么

| 进程 | 入口 | 服务对象 | 传输 |
| --- | --- | --- | --- |
| 账号服 | `repo:server/account_server/app.js` | 客户端 + 渠道代理 | Express HTTP |
| 大厅服 | `repo:server/hall_server/app.js` | 客户端 + 游戏服 | Express HTTP |
| 游戏服 | `repo:server/game_server/app.js` | 客户端 + 大厅服 | Socket.IO + Express HTTP |

绑定的监听端口共 **6 个**（`grep -rn "listen(" server`）：

| 端口 | 绑定位置 | 用途 |
| --- | --- | --- |
| 9000 | `account_server/account_server.js:20` | 客户端 → 账号服 |
| 12581 | `account_server/dealer_api.js:15` | 渠道/代理查询 |
| 9001 | `hall_server/client_service.js:301` | 客户端 → 大厅服 |
| 9002 | `hall_server/room_service.js:212` | 游戏服 → 大厅服上报 |
| 10000 | `game_server/socket_service.js:30` | 客户端 Socket.IO 对局 |
| 9003 | `game_server/http_service.js:177` | 大厅服 → 游戏服内部调用 |

- 账号服 = `account_server.js`（`/guest`、`/register`、登录…）+ `dealer_api.js`（`/get_user_info`…）。
  它 `require('fibers')`，**在当前 Node 上无法启动**（见根 `AGENTS.md` §3.3）。
- 大厅服的 `client_service.js` 是客户端 HTTP 接口（`/login`、`/create_private_room`、
  `/enter_private_room`、`/get_history_list`、`/get_message`…）；
  `room_service.js` 负责向游戏服发起 HTTP 调用并维护房间登记。
- 游戏服的 `socket_service.js` 是**对局协议的唯一入口**（所有 `socket.on(...)`）；
  `http_service.js` 是给大厅服调用的内部接口（`/get_server_info`、`/create_room`、
  `/enter_room`、`/is_room_runing`）。**四个接口都校验 `sign`**，
  `/get_server_info` 用的是 `md5(serverid + ROOM_PRI_KEY)`。

---

## 3. 一次登录的完整链路

理解这条链路，才能判断一个改动该落在哪个进程：

```
1. 客户端 → 账号服  GET  /guest                              换取签名与大厅地址
2. 客户端    cc.vv.http.url 切换为 "http://" + cc.vv.SI.hall  （UserMgr.js）
3. 客户端 → 大厅服  GET  /login?account=&sign=               取得 userid 等资料
4. 客户端 → 大厅服  GET  /enter_private_room?...             取得 {ip, port, token, roomid, time, sign}
5. 客户端 → 游戏服  socket.io 连接 ip:port，然后 emit('login', {token, roomid, time, sign})
6. 游戏服   校验 md5(roomid + token + time + ROOM_PRI_KEY) == sign
```

客户端的 HTTP 封装（`HTTP.js`）**全部用 GET**，参数走 query string。

- 第 4 步的 `sign` 与第 6 步的校验必须一致：**改任一侧的拼接顺序或密钥就会导致全部登录失败**。
  签名原语在 `repo:server/utils/crypto.js`（`md5`），两侧拼接代码分别在
  `repo:server/hall_server/room_service.js` 与 `repo:server/game_server/socket_service.js`。
- token 由游戏服的 `tokenmgr.js` 生成并在 `socketservice` 登录时校验有效期。

---

## 4. 玩法规则：两份并行实现

`repo:server/game_server/gamemgr_xlch.js`（2289 行）与 `repo:server/game_server/gamemgr_xzdd.js`
（2298 行）约 **86%** 的行逐行相同（`difflib` ratio 0.857），由 `repo:server/game_server/roommgr.js`
按 `conf.type` 选择。注意两处选择点的变量不同名：

```js
// roommgr.js:147  新建房间，读入参
if(roomConf.type == "xlch"){ roomInfo.gameMgr = require("./gamemgr_xlch"); }
// roommgr.js:34   从数据库恢复房间，读已落库的 conf
if(roomInfo.conf.type == "xlch"){ roomInfo.gameMgr = require("./gamemgr_xlch"); }
```

| 常量 | 值 |
| --- | --- |
| `ACTION_CHUPAI` | 1 |
| `ACTION_MOPAI` | 2 |
| `ACTION_PENG` | 3 |
| `ACTION_GANG` | 4 |
| `ACTION_HU` | 5 |
| `ACTION_ZIMO` | 6 |

两份文件的常量与导出函数集相同，差异集中在番型判定与流程分支。**修改前先明确该改动属于
哪种玩法**；属于两者共同的，两份都要改；只属于一种的，要在提交说明里写清楚。

房间配置分两层，**不要混淆**：

- **入参 `roomConf`**（`createRoom` 校验，来自 `CreateRoom.js`）：`type`、`difen`、`zimo`、
  `jiangdui`、`huansanzhang`、`zuidafanshu`、`jushuxuanze`、`dianganghua`、`menqing`、`tiandihu`。
  缺任何一个都会 `callback(1,null)` 建房失败。
- **落库 `conf`**（写进 `t_rooms.base_info`，对局逻辑只认这一层）：
  `type`、`baseScore`、`zimo`、`jiangdui`、`hsz`、`dianganghua`、`menqing`、`tiandihu`、
  `maxFan`、`maxGames`、`creator`。

映射表（`roommgr.js`）：`difen → DI_FEN[1,2,5]`、`zuidafanshu → MAX_FAN[3,4,5]`、
`jushuxuanze → JU_SHU[4,8]`、`huansanzhang → hsz`。房间状态持久化在 `t_rooms`，
牌局过程在 `t_games` / `t_games_archive`。

---

## 5. 数据访问层

`repo:server/utils/db.js` 是**唯一**允许拼 SQL 的地方（750 行，导出 35 个函数）。
业务代码只能调用它的导出，不要自己 `require('mysql')` 或拼 SQL 字符串。

- 连接池在 `db.init(configs.mysql())` 时创建，**进程启动时必须先 init**。
- 函数风格是 `(args..., callback)`，错误通过 `callback(err, ...)` 传回；没有 Promise。
- 用户名进出库都走 `repo:server/utils/crypto.js` 的 Base64 函数（`db.js` 内部处理）。
- 表结构变更要同时改 `repo:server/sql/db_babykylin.sql` 与 `db.js` 里的语句。

常用函数：`get_user_data`、`get_user_data_by_userid`、`create_user`、`update_user_info`、
`cost_gems`、`add_user_gems`、`create_room`、`get_room_data`、`update_seat_info`、`delete_room`、
`create_game`、`update_game_action_records`、`update_game_result`、`archive_games`、
`get_user_history`、`get_message`、`query`。

---

## 6. 房间内推送事件的角色表

对局内的推送**统一**走 `repo:server/game_server/usermgr.js` 的助手函数。
该文件导出 8 个函数（`bind`、`del`、`get`、`isOnline`、`getOnlineCount`、`sendMsg`、
`kickAllInRoom`、`broacastInRoom`），其中与推送相关的是这 3 个：

| 函数 | 语义 |
| --- | --- |
| `sendMsg(userId, event, data)` | 发给单个玩家；玩家不在线则静默丢弃 |
| `broacastInRoom(event, data, sender, includingSender)` | 广播给同房间所有座位（拼写就是 `broacast`，**不要"顺手修正"**，否则会漏掉调用点） |
| `kickAllInRoom(roomId)` | 踢出房间内所有连接，不推送事件 |

`userMgr.bind(userId, socket)` 在登录成功时登记连接，`userMgr.del` 在断开时移除。

**唯一的例外是 `socket_service.js` 里 7 处直接的 `socket.emit`**，全部发生在登录/连接阶段
（此时还没有房间可广播）：`login_result`×4、`login_finished`、`exit_result`、`game_pong`。

- 新增**对局内**推送：用 `sendMsg` / `broacastInRoom`，不要写裸 `socket.emit`。
  理由是语义与可读性（读者一眼知道是"发给房间"还是"发给个人"），
  **不是因为门禁扫不到**——`check:protocol` 同时识别裸 `emit(`，两种写法都能扫到。
- 新增**连接阶段**推送：可以像既有代码那样直接 `socket.emit`。
- 无论哪种写法，客户端的 `addHandler` 都必须同名，并跑 `npm run check:protocol`。

事件清单与方向见 `repo:docs/ai-native/protocol.md`。

---

## 7. 你一定要遵守的约束

1. **不要依赖能启动服务来验证改动**：账号服需要 `fibers`，`db.js` 需要真实 MySQL。
   能用的是 `npm run verify`。
2. **`server/tests/*.js` 是历史手工脚本**（`dbtest.js`、`test.js` 等），会连数据库、会打印而不
   断言。不要把它们当作测试套件，也不要在 CI/门禁里执行。
3. **不要提交 `nohup.out`、日志与数据库转储。**
4. 端口、密钥、数据库口令集中在 `configs_*.js`。不要在业务代码里硬编码端口或密钥。
5. `utils/http.js` 导出的 `send(res, errcode, errmsg, data)` 是**大厅服与游戏服**给客户端/调用方
   返回 JSON 的统一出口，这两个服务里新增接口请沿用它。
   注意**账号服没有跟进这条约定**：`account_server.js:11` 与 `dealer_api.js:9` 各自定义了一个
   本地 `function send(res, ret){ res.send(JSON.stringify(ret)) }`，返回结构也更随意。
   改动账号服接口时按它本地的写法来，不要为了"统一"而大改。
6. `server/tests/*.js`、`server/nohup.out` 等运行期文件不要提交（`nohup.out` 已在根 `.gitignore` 中）。

---

## 8. 改完怎么验证

```bash
npm run verify                 # 全部五项，含协议一致性与行为冒烟
npm run check:protocol         # 动了任何推送事件名时必跑
npm run check:smoke            # 动了 mjutils / crypto 时必跑
```

若改动需要真实运行时（数据库、fibers）才能确认，请在提交说明里明确写出
**"未运行时验证"** 以及你依赖了哪些静态证据。宁可承认没验证，也不要暗示已验证。
