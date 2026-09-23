# AGENTS.md — 服务端（Node.js 三进程）

本文件在根级 `AGENTS.md` 之上叠加，仅覆盖服务端相关内容。冲突时以本文件为准。

---

## 1. 目录与职责

```
server/
├─ tsconfig.json                     ← 编译器配置（strict 全开，取舍见 docs/ai-native/typescript-migration.md §7）
├─ configs_mac.ts / configs_win.ts   ← 唯一配置来源（函数式导出，两个平台各一份）
├─ start_all.sh / start_all_mac.sh   ← 一键启动三个进程（mac 版带 stop/status/logs，见 §1.2）
├─ package.json / yarn.lock          ← 依赖清单与锁文件（yarn 1.x 是唯一依赖管理方式）
├─ types/                            ← 跨模块共享的**类型模块**（config / domain / protocol / db_rows / globals.d.ts / socket.io.d.ts）
├─ account_server/                   ← 账号服 :9000，含 dealer_api :12581
├─ hall_server/                      ← 大厅服 :9001（客户端）、:9002（游戏服上报）
├─ game_server/                      ← 游戏服 :10000（Socket.IO）、:9003（HTTP）
├─ utils/                            ← db.ts / http.ts / crypto.ts / startup.ts / config.ts 共享层
├─ sql/db_babykylin.sql              ← 建表与初始数据（权威 schema）
├─ tests/                            ← 2016 年的手工脚本（已随迁移改成 `.ts`），**不是自动化测试**
├─ dist/                             ← **编译产物**，不提交（server/.gitignore 已忽略）
└─ node_modules/                     ← 安装产物，**不提交**（server/.gitignore 已忽略）
```

每个进程入口都通过 `process.argv[2]` 读取配置文件（`utils/config.ts` 的 `loadConfigs`）。
**服务端是 TypeScript，跑的是编译产物**：

```bash
cd server
yarn install --frozen-lockfile   # 依赖（含 typescript / @types/node / @types/express）
yarn build                       # tsc -> dist/
node dist/game_server/app.js ../configs_mac.js
```

入口比迁移前只多一个 `dist/` 前缀。`../configs_mac.js` 的相对语义**没变**：`require` 相对
**入口模块目录**解析，编译后入口在 `dist/game_server/`，所以它指向 `dist/configs_mac.js`
（由 `configs_mac.ts` 编译而来）。`dist/` 不存在时先 `yarn build`，`start_all_mac.sh` 也会明确提示。

**`configs_mac.ts` 与 `configs_win.ts` 必须同步修改**。迁移后它们是**不带 BOM 的 UTF-8**：
老 `configs_mac.js` 首行那个 `\ufeff` 已经不复存在，不要再按"别弄丢 BOM"的老经验处理。

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
- **运行时依赖（`dependencies`）只有 4 个**：`express`、`log4js`、`mysql2`、`socket.io`。代码里实际
  `require` 的是 `express`、`mysql2`、`socket.io`；**`log4js` 目前没有任何引用**，仅为历史遗留而保留声明。
- **开发依赖（`devDependencies`）有 3 个**，都是 TypeScript 迁移带进来的：`typescript`、
  `@types/node`、`@types/express`。它们只在 `yarn build` / `yarn typecheck` / 门禁的 `types`
  检查里用到，不进运行时。`yarn.lock` 已随迁移更新，换机时照旧用 `--frozen-lockfile` 安装。
- 锁文件里是 yarn 解析出的版本，与 2016 年那套 node_modules 里的版本**不同**
  （express 4.14.0 → 4.22.x、socket.io 1.4.6 → 1.7.x、log4js 1.0.1 → 1.1.x、
  mysql 2.11.1 → mysql2 3.24.x）。这几个包在 mac + Node 24 上已实测可启动
  （三个进程都能监听端口并完成一次真实登录链路，见 §8）。
- **两个驱动/原生模块的历史包袱都已清掉**，别再引入回来：
  - `fibers`：只支持到 node 8，在 Node 12+ / Apple Silicon 上编译不出来，`require` 直接抛
    "Missing binary"。原先它只服务于 `utils/http.ts` 的同步 HTTP（`getSync`）与账号服
    CORS 中间件的 fiber 包装；现在 `getSync` 已改成回调风格 `getRaw`，中间件直接 `next()`。
  - `mysql`：只支持 `mysql_native_password`，连不上 MySQL 8 默认的
    `caching_sha2_password`（brew 装的 MySQL 8.4 报 `ER_NOT_SUPPORTED_AUTH_MODE`）。
    `mysql2` 是它的超集，`db.ts` 只用到 `createPool` / `getConnection` / `query` / `release`，
    替换是纯 API 兼容的。
- `yarn install` 不再需要编译任何原生扩展，也就**不需要** `--ignore-scripts`。
- 锁文件里的 `resolved` 统一指向 `https://registry.npmjs.org`。
  若你本机配了国内镜像，请显式指定仓库再更新锁文件，否则会把镜像地址写进锁文件：
  `yarn install --registry https://registry.npmjs.org`

`package.json` 里还提供了三个进程的启动脚本（等价于 `node dist/<进程>/app.js ../configs_mac.js`，
**已经是 dist 入口**）：`yarn account` / `yarn hall` / `yarn game`，适合**前台调试单个进程**；
另外还有 `yarn build`（`tsc` → `dist/`）、`yarn typecheck`（只做类型检查）、`yarn clean`（删 `dist/`）。
要起全套用下面的 `start_all_mac.sh`。

### 1.2 一键启动：`repo:server/start_all_mac.sh`

mac 上起停三个进程都用这一个脚本，不要再手敲三条 `nohup`：

```bash
cd server
yarn install --frozen-lockfile && yarn build   # 先装依赖并编译出 dist/
./start_all_mac.sh                  # 一键启动（缺省即 start），随后打印状态表
./start_all_mac.sh status           # 只看状态；全部就绪退出码 0，否则 1
./start_all_mac.sh stop             # SIGTERM 优雅停止（只停本脚本启动的进程）
./start_all_mac.sh restart          # 先停后起
./start_all_mac.sh logs game        # 跟踪某个进程的日志（account / hall / game，缺省全部）
./start_all_mac.sh help             # 帮助（直接读脚本头部注释，两者不会走样）
./start_all_mac.sh --config configs_win.js status   # 换配置文件
```

- **跑的是编译产物**：脚本用 `PROC_ENTRY` 指向 `dist/<进程>/app.js`；`dist/` 里缺入口时会明确
  提示"先执行 `cd server && yarn build`"，而不是等 node 报 `MODULE_NOT_FOUND`。
  `--config` 的三种写法（`../configs_mac.js`、`configs_mac.js`、绝对路径）都认，并且**优先去
  `dist/` 找同名文件**——因为配置的真身是 `dist/configs_mac.js`（`configs_mac.ts` 的编译产物）。
- **端口不写死在脚本里**：脚本用 `node -e` require 配置文件，按字段读出 6 个端口，
  改 `configs_mac.ts` 的端口，状态表自动跟着变；读不出来会明确标注"端口为内置默认值"。
- **状态表**逐进程列出 PID、运行时长、两个端口各自 `[监听中] / [未监听] / [被占用]` 与日志路径。
  `[被占用]` 表示端口在监听但不是本脚本启动的进程；此时 `start` 会拒绝启动该进程并报出占用者 PID。
- 运行期产物：PID 记在 `repo:server/.run/pids`，日志写 `repo:server/logs/<名字>.log`
  （每次启动重写，只对应最近一次运行），二者都已 gitignore。**不再产生 `nohup.out`。**
- "就绪"以端口真的 listening 为准；进程起来又立刻退出（EADDRINUSE、配置写错…）时，
  脚本会贴出该进程日志的最后 12 行。
- 脚本只用 macOS 自带 bash 3.2 的特性。注意 bash 3.2 的多字节坑：`$VAR` 后面紧跟中文必须写成
  `${VAR}`，否则变量展开为空、中文变乱码——脚本头部注释里记了这件事。
- `start_all.sh`（旧/Linux 写法）与 `*.bat` 仍是原先三行 `nohup` / `start` 的形态，**没有**跟进
  这些子命令；但它们的入口**也已经改成 `dist/` 产物**，用之前同样要先 `yarn build`。

---

## 2. 三个进程各自做什么

| 进程 | 入口 | 服务对象 | 传输 |
| --- | --- | --- | --- |
| 账号服 | `repo:server/account_server/app.ts` | 客户端 + 渠道代理 | Express HTTP |
| 大厅服 | `repo:server/hall_server/app.ts` | 客户端 + 游戏服 | Express HTTP |
| 游戏服 | `repo:server/game_server/app.ts` | 客户端 + 大厅服 | Socket.IO + Express HTTP |

绑定的监听端口共 **6 个**（`grep -rn "listen(" server`；行号随 `.ts` 源码，不是 `dist/`）：

| 端口 | 绑定位置 | 用途 |
| --- | --- | --- |
| 9000 | `account_server/account_server.ts:54` | 客户端 → 账号服 |
| 12581 | `account_server/dealer_api.ts:34` | 渠道/代理查询 |
| 9001 | `hall_server/client_service.ts:367` | 客户端 → 大厅服 |
| 9002 | `hall_server/room_service.ts:289` | 游戏服 → 大厅服上报 |
| 10000 | `game_server/socket_service.ts:87` | 客户端 Socket.IO 对局 |
| 9003 | `game_server/http_service.ts:220` | 大厅服 → 游戏服内部调用 |

各 `start()` 返回自己的 `http.Server`，由 `*/app.ts` 交给 `utils/startup.ts` 汇总；横幅只有在
上面 6 个端口（按进程分组）全部真正 listening 之后才打印。

- 账号服 = `account_server.ts`（`/guest`、`/register`、登录…）+ `dealer_api.ts`（`/get_user_info`…）。
  两个服务在同一个进程里，由 `account_server/app.ts` 一起拉起并汇总成一块启动横幅
  （`utils/startup.ts`）。
- 大厅服的 `client_service.ts` 是客户端 HTTP 接口（`/login`、`/create_private_room`、
  `/enter_private_room`、`/get_history_list`、`/get_message`…）；
  `room_service.ts` 负责向游戏服发起 HTTP 调用并维护房间登记。
- 游戏服的 `socket_service.ts` 是**对局协议的唯一入口**（所有 `socket.on(...)`）；
  `http_service.ts` 是给大厅服调用的内部接口（`/get_server_info`、`/create_room`、
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
  签名原语在 `repo:server/utils/crypto.ts`（`md5`），两侧拼接代码分别在
  `repo:server/hall_server/room_service.ts` 与 `repo:server/game_server/socket_service.ts`。
- token 由游戏服的 `tokenmgr.ts` 生成并在 `socket_service.ts` 登录时校验有效期。

---

## 4. 玩法规则：两份并行实现

`repo:server/game_server/gamemgr_xlch.ts`（2488 行）与
`repo:server/game_server/gamemgr_xzdd.ts`（2510 行）约 **86%** 的行逐行相同
（`difflib` ratio 0.864），由 `repo:server/game_server/roommgr.ts` 按 `conf.type` 选择。
两处**调用点**都走同一个懒加载助手 `loadGameManager(type)`（`roommgr.ts:61`），
但传入的变量不同名：

```ts
// roommgr.ts:216  新建房间，读入参
gameMgr:loadGameManager(roomConf.type)
// roommgr.ts:83   从数据库恢复房间，读已落库的 conf
gameMgr:loadGameManager(conf.type)
```

**必须保持懒加载**：两个 gamemgr 文件末尾都有 `setInterval(update,1000)`，顶层同时 require
会跑起两个定时器。

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

映射表（`roommgr.ts`）：`difen → DI_FEN[1,2,5]`、`zuidafanshu → MAX_FAN[3,4,5]`、
`jushuxuanze → JU_SHU[4,8]`、`huansanzhang → hsz`。房间状态持久化在 `t_rooms`，
牌局过程在 `t_games` / `t_games_archive`。

---

## 5. 数据访问层

`repo:server/utils/db.ts` 是**唯一**允许拼 SQL 的地方（导出 36 个函数，其中 `query` 是裸查询逃生口）。
行结构的类型契约在 `repo:server/types/db_rows.ts`，`db.ts` 会把这些类型再导出一次。
业务代码只能调用它的导出，不要自己 `require('mysql2')` 或拼 SQL 字符串。

- 连接池在 `db.init(configs.mysql())` 时创建，**进程启动时必须先 init**。
- 函数风格是 `(args..., callback)`，错误通过 `callback(err, ...)` 传回；没有 Promise。
  迁移到 TS 后同样是回调风格，不要改成 `async`。
- 用户名进出库都走 `repo:server/utils/crypto.ts` 的 Base64 函数（`db.ts` 内部处理）。
- 表结构变更要同时改 `repo:server/sql/db_babykylin.sql`、`db.ts` 里的语句与 `types/db_rows.ts`。
- `db.ping(callback)` 只做一次 `SELECT 1`，供 `utils/startup.ts` 在启动横幅里显示数据库真实状态；
  它不抛异常、也不要求进程退出。

常用函数：`get_user_data`、`get_user_data_by_userid`、`create_user`、`update_user_info`、
`cost_gems`、`add_user_gems`、`create_room`、`get_room_data`、`update_seat_info`、`delete_room`、
`create_game`、`update_game_action_records`、`update_game_result`、`archive_games`、
`get_user_history`、`get_message`、`query`。

---

## 6. 房间内推送事件的角色表

对局内的推送**统一**走 `repo:server/game_server/usermgr.ts` 的助手函数。
该文件导出 8 个函数（`bind`、`del`、`get`、`isOnline`、`getOnlineCount`、`sendMsg`、
`kickAllInRoom`、`broacastInRoom`），其中与推送相关的是这 3 个：

| 函数 | 语义 |
| --- | --- |
| `sendMsg(userId, event, data)` | 发给单个玩家；玩家不在线则静默丢弃 |
| `broacastInRoom(event, data, sender, includingSender)` | 广播给同房间所有座位（拼写就是 `broacast`，**不要"顺手修正"**，否则会漏掉调用点） |
| `kickAllInRoom(roomId)` | 踢出房间内所有连接，不推送事件 |

`userMgr.bind(userId, socket)` 在登录成功时登记连接，`userMgr.del` 在断开时移除。

**唯一的例外是 `socket_service.ts` 里 7 处直接的 `socket.emit`**，全部发生在登录/连接阶段
（此时还没有房间可广播）：`login_result`×4、`login_finished`、`exit_result`、`game_pong`。

- 新增**对局内**推送：用 `sendMsg` / `broacastInRoom`，不要写裸 `socket.emit`。
  理由是语义与可读性（读者一眼知道是"发给房间"还是"发给个人"），
  **不是因为门禁扫不到**——`check:protocol` 同时识别裸 `emit(`，两种写法都能扫到。
- 新增**连接阶段**推送：可以像既有代码那样直接 `socket.emit`。
- 无论哪种写法，客户端的 `addHandler` 都必须同名，并跑 `npm run check:protocol`。

事件清单与方向见 `repo:docs/ai-native/protocol.md`。

---

## 7. 你一定要遵守的约束

1. **离线判据是 `npm run verify`，但服务本身已经能启动**：三个进程都能在 mac + Node 24 上跑起来
   （`fibers` 与 `mysql` 两个历史包袱已清除，见 §1.1），跑之前先 `yarn build`；只有 DB 相关路径
   需要真实 MySQL。启动横幅（`utils/startup.ts`）会如实标注数据库是否连得上，不会把连不上库的
   进程说成"一切正常"。
2. **`server/tests/*.ts` 是历史手工脚本**（`dbtest.ts`、`test.ts` 等，已随迁移从 `.js` 改名），
   会连数据库、会打印而不断言。不要把它们当作测试套件，也不要在 CI/门禁里执行。
3. **不要提交 `nohup.out`、`logs/`、`.run/`、`dist/` 与数据库转储**（`start_all_mac.sh` 的运行期产物见 §1.2）。
4. 端口、密钥、数据库口令集中在 `configs_*.ts`。不要在业务代码里硬编码端口或密钥。
5. `utils/http.ts` 导出的 `send(res, errcode, errmsg, data)` 是**大厅服与游戏服**给客户端/调用方
   返回 JSON 的统一出口，这两个服务里新增接口请沿用它。
   注意**账号服没有跟进这条约定**：`account_server.ts:22` 与 `dealer_api.ts:20` 各自定义了一个
   本地 `function send(res, ret){ res.send(JSON.stringify(ret)) }`，返回结构也更随意。
   改动账号服接口时按它本地的写法来，不要为了"统一"而大改。
6. `server/tests/*.ts`、`server/nohup.out` 等运行期文件不要提交（`nohup.out` 已在根 `.gitignore` 中）。

---

## 8. 改完怎么验证

```bash
npm run verify                 # 全部六项：syntax / types / harness / protocol / smoke / selftest
npm run verify -- --only=types # 只做类型契约检查（no-any 审计 + tsc --noEmit）
npm run check:protocol         # 动了任何推送事件名时必跑
npm run check:smoke            # 动了 mjutils / crypto / http 时必跑
```

`types` 检查分两半：**no-any 审计**零依赖、永远执行（扫所有一方 `.ts`，`: any` / `as any` /
`<any>` / `@ts-ignore` / `@ts-expect-error` 一律失败）；**`tsc --noEmit`** 需要
`server/node_modules/typescript`（`yarn install` 提供），没装时这半报 **skipped** 而不是通过。
`smoke` 则优先直接加载 `.ts` 源码，所以不先 `yarn build` 也能跑。

**服务端现在可以真的启动**，所以动过服务端代码后请顺手起一遍受影响的那个进程：

```bash
cd server
yarn install --frozen-lockfile && yarn build  # 跑的是 dist/ 产物，先编译
./start_all_mac.sh                           # 起全套并打印状态表（§1.2），停用 ./start_all_mac.sh stop
./start_all_mac.sh logs hall                 # 盯某个进程的日志，比翻 nohup.out 方便

# 只想前台跑单个进程时（三个进程各开一个终端）：
node dist/hall_server/app.js ../configs_mac.js
node dist/game_server/app.js ../configs_mac.js
node dist/account_server/app.js ../configs_mac.js
```

每个进程会打印一块启动横幅（`utils/startup.ts`）：

- 只有**所有端口都真正 listening** 才显示"启动成功"；端口被占用时打印占用端口与处理建议，
  并以退出码 1 结束，不再出现"提示说成功、进程随即崩掉"的假象。
- 横幅里的"数据库"一行来自 `db.ping()`，连不上库时会明确写"不可用 — <错误码>"，
  进程继续启动（`/guest` 等接口不依赖数据库）。

DB 相关改动（注册/登录/建房）必须有真实 MySQL 才能确认；做不到时请在提交说明里写出
**"未运行时验证"** 以及依赖了哪些静态证据。宁可承认没验证，也不要暗示已验证。
