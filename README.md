# 幼麟四川麻将（Cocos Creator 2.4.15 · TypeScript 版）

> 本项目基于 [幼麟棋牌 babykylin_scmj](https://github.com/babykylin/babykylin_scmj) 的**最新代码**，
> 做了两项主要升级：
>
> 1. **客户端引擎升级**：Cocos Creator `2.0.6` → **`2.4.15`**（引擎 `cocos2d-html5`）；
> 2. **服务端语言升级**：ES5 JavaScript → **TypeScript（`strict: true`）**，由 `tsc` 编译到
>    `server/dist/` 后运行。
>
> 顺带完成的工程化改造：客户端源码迁移到 TypeScript（组件用 ES6 `class` + `@ccclass` / `@property`）、
> 依赖改用 yarn 1.x 锁定、移除 `fibers` / `mysql` 两个原生依赖包袱、引入零依赖验证门禁
> `npm run verify`。**所有迁移都是"行为不变"的**：玩法规则、事件名、载荷字段、日志文案一律保留原样。

一套可运行的开源四川麻将完整实现，包含 **血战到底** 与 **血流成河** 两种玩法。

---

## 一、与上游版本的差异

| 维度 | 上游（babykylin_scmj） | 本仓库 |
| --- | --- | --- |
| 客户端引擎 | Cocos Creator 2.0.6 | **Cocos Creator 2.4.15** |
| 客户端语言 | ES5 JavaScript（`cc.Class`） | **TypeScript**（ES6 `class` + `@ccclass` / `@property`） |
| 服务端语言 | ES5 JavaScript（直接 `node` 运行） | **TypeScript**（`strict`，`tsc` → `server/dist/` 后运行） |
| Node.js | v6.x（原文注明"高版本可能无法启动"） | 声明 `>=18`，**mac + Node 24 已实测三进程可启动** |
| 依赖管理 | 直接提交 `node_modules` | **yarn 1.x + `yarn.lock`**，`node_modules` 不提交 |
| 数据库驱动 | `mysql`（仅 `mysql_native_password`） | **`mysql2`**（兼容 MySQL 8 的 `caching_sha2_password`） |
| 同步 HTTP | `fibers` 原生模块 | 已移除，改回回调风格（`utils/http.ts` 的 `getRaw`） |
| 工程化 | 无自动检查 | **零依赖验证门禁 `npm run verify`**（六项检查）+ AI Native 工程契约 |

> 「本仓库的源码一律是 TypeScript」这一点在两个目录都成立；区别只是客户端由 Creator 自己编译，
> 没有构建步骤，服务端则由 `tsc` 编译到 `dist/`。

---

## 二、主要功能

**玩法**

- 四川麻将 **血战到底**（`type = "xzdd"`）
- 四川麻将 **血流成河**（`type = "xlch"`）
- 定缺、换三张（`hsz` 开关）
- 碰 / 杠（明杠、暗杠、点杠）/ 胡（点炮、自摸）/ 过
- 房卡房间：底分（`difen`）、自摸加底（`zimo`）、将对（`jiangdui`）、最大番数（`zuidafanshu`）、
  局数（`jushuxuanze`，4 / 8 局）、点杠花（`dianganghua`）、门清（`menqing`）、天地胡（`tiandihu`）
- **单人模式（人机）**：建房面板里打开"单人模式"，服务端自动补三个机器人陪打，免房卡
  （目前只在 Python 服务端实现，见 §7.5）

**大厅与社交**

- 账号注册 / 登录 / 游客登录（`/guest`）
- 创建房间、输入房号加入、解散房间
- 战绩列表与房间详情、**牌局回放**
- 文字聊天、快捷语、表情、**语音消息**
- 断线重连、全屏幕适配

**服务端**

- 账号服 / 大厅服 / 游戏服三进程分离，可分布式多进程部署
- 房间状态与牌局过程持久化到 MySQL，可重启恢复
- 游戏服对外暴露 Socket.IO 对局协议，内部 HTTP 接口带签名校验

---

## 三、技术栈

| 部分 | 技术栈 |
| --- | --- |
| 客户端 `client/` | Cocos Creator **2.4.15**（`cocos2d-html5`）+ **TypeScript**（`target: es6`、`module: commonjs`、`strict`），socket.io 客户端为 vendored 的 `3rdparty/socket-io.js` |
| 服务端 `server/` | Node.js（`>=18`）+ **TypeScript 5**（`strict: true`，`tsc` → `dist/`）+ Express + Socket.IO 1.x + MySQL（`mysql2`） |
| 数据库 | MySQL（库名 `db_scmj`，字符集 `utf8`） |
| 依赖管理 | **yarn 1.22**（`server/yarn.lock` 为准） |
| 验证门禁 | 零依赖的 `tools/verify.mjs`（唯一"完成"判据） |

服务端运行时依赖只有 4 个：`express`、`log4js`（历史遗留、当前无引用）、`mysql2`、`socket.io`；
开发依赖 3 个（TypeScript 迁移带入）：`typescript`、`@types/node`、`@types/express`。

---

## 四、系统架构

```
                        ┌──────────────────────────────────────────┐
                        │        客户端（Cocos Creator 2.4.15）      │
                        └──────────────────────────────────────────┘
   HTTP  ──────────────────────────►  账号服 account_server  :9000   注册 / 登录 / 游客
   HTTP  ──────────────────────────►  账号服 dealer_api      :12581  渠道 / 代理侧查询
   HTTP  ──────────────────────────►  大厅服 hall_server      :9001   登录 / 建房 / 战绩
   Socket.IO ──────────────────────►  游戏服 game_server      :10000  对局内全部实时协议
                        ▲
                        │ HTTP（内部调用，需签名）
   大厅服 ──────────────┘          游戏服 http_service      :9003   建房 / 进房 / 查询
   游戏服 ──────────────────────►  大厅服 room_service      :9002   向大厅服上报
                        │
                        ▼
                   MySQL  db_scmj（server/sql/db_babykylin.sql）
```

### 端口与进程

| 进程 | 入口（编译后） | 端口 | 用途 |
| --- | --- | --- | --- |
| 账号服 | `dist/account_server/app.js` | **9000** | 客户端 HTTP：`/guest`、`/register`、登录… |
| 账号服（同进程） | `dist/account_server/app.js` | **12581** | 代理 API：`/get_user_info`、`/add_user_gems`… |
| 大厅服 | `dist/hall_server/app.js` | **9001** | 客户端 HTTP：`/login`、`/create_private_room`、`/enter_private_room`、`/get_history_list`… |
| 大厅服 | `dist/hall_server/app.js` | **9002** | 游戏服 → 大厅服上报 |
| 游戏服 | `dist/game_server/app.js` | **10000** | 客户端 Socket.IO 对局协议（唯一入口 `socket_service.ts`） |
| 游戏服 | `dist/game_server/app.js` | **9003** | 大厅服 → 游戏服内部 HTTP（四个接口都校验 `sign`） |

三个进程的启动横幅由 `server/utils/startup.ts` 统一打印：**只有所有端口真正 listening 之后才显示
"启动成功"**；端口被占用会打印占用者并以非 0 退出；传入 `db` 时横幅附带一次数据库连通性自检。

### 一次登录的链路

```
1. 客户端 → 账号服  GET /guest                      换取签名与大厅地址
2. 客户端           cc.vv.http.url 切换为账号服下发的大厅地址
3. 客户端 → 大厅服  GET /login?account=&sign=        取得 userid 等资料
4. 客户端 → 大厅服  GET /enter_private_room?...      取得 {ip, port, token, roomid, time, sign}
5. 客户端 → 游戏服  socket.io 连接 ip:port，emit('login', {token, roomid, time, sign})
6. 游戏服          校验 md5(roomid + token + time + ROOM_PRI_KEY) == sign
```

> **改任一侧的签名拼接顺序或密钥，都会导致全部登录失败。** 签名原语在 `server/utils/crypto.ts`，
> 两侧拼接分别在 `server/hall_server/room_service.ts` 与 `server/game_server/socket_service.ts`。

---

## 五、目录结构

```
babykylin_scmj/
├─ client/                       Cocos Creator 2.4.15 客户端
│  ├─ assets/
│  │  ├─ scenes/                 场景：start / loading / login / createrole / hall / mjgame
│  │  ├─ scripts/                46 个一方脚本（管理器 + components/ 34 个组件）
│  │  │  ├─ Net.ts               socket.io 连接、心跳、addHandler 注册表
│  │  │  ├─ HTTP.ts              XHR 封装（账号服基地址硬编码在第 2 行）
│  │  │  ├─ GameNetMgr.ts        对局状态机 + 网络事件注册与派发
│  │  │  ├─ UserMgr.ts           登录 / 用户资料 / 进房
│  │  │  └─ components/          34 个场景组件
│  │  ├─ prefabs/ anims/ resources/  预制体、动画、牌面与音频资源
│  │  └─ migration/              Creator 从 2.0.x 升级时自动生成的兼容助手
│  ├─ types/                     手写的共享类型声明（cc-vv / domain / cc-augment / globals）
│  ├─ tsconfig.json              Creator 与 tsc --noEmit 共用的编译配置
│  └─ project.json               工程信息（version: 2.4.15）
├─ server/                       Node.js 三进程服务端
│  ├─ account_server/            账号服 :9000（含 dealer_api :12581）
│  ├─ hall_server/               大厅服 :9001 / :9002
│  ├─ game_server/               游戏服 :10000 / :9003
│  ├─ utils/                     db.ts / http.ts / crypto.ts / startup.ts / config.ts
│  ├─ types/                     共享类型（config / domain / protocol / db_rows / *.d.ts）
│  ├─ sql/db_babykylin.sql       建表与初始数据（权威 schema）
│  ├─ configs_mac.ts / configs_win.ts   唯一配置来源（函数式导出，两平台各一份）
│  ├─ start_all_mac.sh           macOS 一键启动 / 停止 / 状态 / 日志
│  ├─ tests/                     2016 年的手工脚本（非自动化测试）
│  └─ dist/                      编译产物（不提交）
├─ docs/ai-native/               给人看的参考文档（协议、玩法、迁移规范、结构图）
├─ .dsh/skills/                  5 个项目技能（按需加载）
├─ tools/                        零依赖验证门禁实现
├─ AGENTS.md                     AI 会话的根级工作契约
└─ package.json                  门禁入口（npm run verify）
```

> `client/library/`、`client/temp/`、`client/local/`、`client/build/`、`server/dist/`、
> `server/node_modules/`、`server/logs/`、`server/.run/` 都是**工具产物，不要手改也不要提交**。

---

## 六、快速开始

### 6.1 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Node.js | **>= 18** | 服务端运行；mac + Node 24 已实测通过 |
| yarn | **1.x**（1.22.22） | 服务端依赖管理，`yarn.lock` 为准 |
| MySQL | 5.7 / 8.x | 默认认证方式已是 `caching_sha2_password` 也可（驱动是 `mysql2`） |
| Cocos Creator | **2.4.15** | 客户端开发与构建（图形化编辑器，无法在本仓库内无头编译） |

### 6.2 初始化数据库

```bash
# 建库建表 + 初始数据（schema 以此文件为权威）
mysql -uroot -p < server/sql/db_babykylin.sql
```

主要数据表：`t_accounts`、`t_users`、`t_guests`、`t_rooms`（房间状态）、`t_games` /
`t_games_archive`（牌局过程与归档）、`t_message`。

### 6.3 启动服务端

```bash
cd server

# 1) 安装依赖并编译（跑的是 dist/ 产物，必须先 build）
yarn install --frozen-lockfile
yarn build                     # tsc -> dist/

# 2) 按本机情况修改数据库口令等配置（见 6.5）
#    server/configs_mac.ts  /  server/configs_win.ts

# 3) 一键启动三个进程（macOS）
./start_all_mac.sh             # 启动并打印状态表
./start_all_mac.sh status      # 只看状态；全部就绪退出码 0
./start_all_mac.sh logs game   # 跟踪某个进程日志（account / hall / game）
./start_all_mac.sh stop        # 优雅停止
./start_all_mac.sh restart     # 先停后起
```

也可以前台分别调试单个进程（三个终端）：

```bash
node dist/account_server/app.js ../configs_mac.js
node dist/hall_server/app.js   ../configs_mac.js
node dist/game_server/app.js   ../configs_mac.js

# 等价于 package.json 里的：yarn account / yarn hall / yarn game
```

> `../configs_mac.js` 的相对语义没变：`require` 相对**入口模块目录**解析，编译后入口在
> `dist/<进程>/`，所以它指向 `dist/configs_mac.js`（由 `configs_mac.ts` 编译而来）。
> 若提示 `dist/` 里缺入口，先执行 `yarn build`。

### 6.4 运行客户端

1. 用 **Cocos Creator 2.4.15** 打开 `client/` 目录（不是仓库根目录），等待资源导入完成。
2. 按需修改账号服地址：`client/assets/scripts/HTTP.ts` **第 2 行**
   （默认 `http://127.0.0.1:9000`，部署到真机/服务器时必须改）。
   游戏服地址不用改——它由服务端在登录流程里下发。
3. 在编辑器里预览运行，或构建到 **iOS / Android / H5**。

> 客户端**没有构建步骤、也不需要打包器**：`.ts` 由 Creator 自带的 TypeScript 按
> `client/tsconfig.json` 编译，产物在 `client/temp/quick-scripts/`（不提交）。
> 新增或改名脚本后必须回编辑器重新导入；`.meta` 由 Creator 维护，不要手工编辑。

### 6.5 配置说明

- 配置的**唯一来源**是 `server/configs_mac.ts` 与 `server/configs_win.ts`，两者是**函数式导出**
  （`export function account_server(){...}`），**必须同步修改**。
- 端口、密钥（`ACCOUNT_PRI_KEY` / `ROOM_PRI_KEY`）、数据库连接都在这里；
  **不要在业务代码里硬编码端口或密钥**。
- `configs_mac.ts` 的 `mysql()` 里的 `HOST` / `USER` / `PSWD` / `DB` 是数据库连接点，
  默认库名 `db_scmj`，连接失败时先检查这里。
- 三进程入口通过 `process.argv[2]` 读配置文件（`utils/config.ts` 的 `loadConfigs`）。

---

## 七、玩法实现

### 7.1 两份并行的玩法实现（改一份必须想另一份）

| 实现 | `conf.type` | 文件 |
| --- | --- | --- |
| 血流成河 | `"xlch"` | `server/game_server/gamemgr_xlch.ts` |
| 血战到底 | `"xzdd"`（非 `xlch` 一律走这份） | `server/game_server/gamemgr_xzdd.ts` |

两份文件约 **86% 的行逐行相同**，由 `server/game_server/roommgr.ts` 里的懒加载助手
`loadGameManager(type)` 按 `conf.type` 二选一。

> **硬约束**：改了其中一份而没改另一份，就是线上不一致。每次修改都要明确回答另一份是否同样适用；
> 只属于一种玩法的改动，要在提交说明里写清原因。
> 懒加载**必须保持**：两个 `gamemgr` 文件末尾都有 `setInterval(update, 1000)`，
> 顶层同时 `require` 会跑起两个定时器。

### 7.2 牌的编码

牌是 **0–26 的整数**，顺序 筒 → 条 → 万：

| 值 | 花色 | 牌 |
| --- | --- | --- |
| `0–8` | 筒 | 1筒 – 9筒 |
| `9–17` | 条 | 1条 – 9条 |
| `18–26` | 万 | 1万 – 9万 |

听牌 / 胡牌判定在 `server/game_server/mjutils.ts`（纯算术、无 IO，因此可离线测试）。
**注意：七对（七小对）当前引擎不认**——`checkCanHu` 只枚举将牌再验证 3N（刻子/顺子），
没有"全偶数即胡"的分支。支持七对属于**新特性**，不是修 bug。

### 7.3 动作记录与回放兼容红线

```
ACTION_CHUPAI = 1   ACTION_MOPAI = 2   ACTION_PENG = 3
ACTION_GANG   = 4   ACTION_HU    = 5   ACTION_ZIMO = 6
```

动作序列写入 `t_games.action_records`（`varchar(2048)`），回放时按这些常量解释。

1. 常量值**只能追加**，不能修改或复用；
2. 单局动作序列**不能超过 2048 字节**，超长会被静默截断，导致回放不完整。

### 7.4 房间配置的两层结构

| 层 | 字段 |
| --- | --- |
| 入参 `roomConf`（客户端 `CreateRoom.ts` 提交） | `type`、`difen`、`zimo`、`jiangdui`、`huansanzhang`、`zuidafanshu`、`jushuxuanze`、`dianganghua`、`menqing`、`tiandihu` |
| 落库 `conf`（`t_rooms.base_info`，对局逻辑只认这层） | `type`、`baseScore`、`zimo`、`jiangdui`、`hsz`、`dianganghua`、`menqing`、`tiandihu`、`maxFan`、`maxGames`、`creator` |

映射：`difen → DI_FEN[1,2,5]`、`zuidafanshu → MAX_FAN[3,4,5]`、`jushuxuanze → JU_SHU[4,8]`、
`huansanzhang → hsz`。`createRoom` 会校验入参非空，缺任何一项直接建房失败。
单人模式会在入参 `roomConf` 里多带一个 `single: 1`（Python 版用它决定是否补机器人、免房卡，
见 §7.5）；它**不落库**，`base_info` 的键集与 Node 版保持一致。

### 7.5 单人模式（人机）

大厅建房面板底部有一个**代码动态生成**的"单人模式"开关（`client/assets/scripts/components/CreateRoom.ts`
的 `setupSingleModeToggle`，不改 `hall.fire`）。打开后：

1. 客户端仍然提交同一份 `conf`，只是多带 `single: 1`，并改调大厅服的 `/create_single_room`；
2. 大厅服把 `single: 1` 写进 conf 后转给游戏服（与 `/create_private_room` 同一套签名）；
3. 游戏服建房时预置三个机器人并跳过房卡校验，真人进房坐 0 号位，登录后四人齐、直接开局。

机器人是**没有 socket 的普通座位**：`roommgr._seat_robots` 把 1~3 号座位写进 `user_location`
并 `ready=True`，`usermgr.is_online` 对它们恒返回 True（否则 `set_ready` 的"四人齐"判断过不去），
推送则因查不到连接被静默丢弃。真正的出牌由 `game_server/robotmgr.py` 驱动：gamemgr 在
`send_operations` / `begin` / `huan_san_zhang` / `peng` 四个钩子点调用 `robotmgr.schedule(...)`，
机器人延迟一小段时间后按"能胡就胡 / 能杠就杠 / 能碰就碰 / 先打缺门再打孤张"的确定性策略回调
gamemgr 的动作函数。

解散房间同样要照顾机器人：解散是"四家投票、全票才生效、否则 30 秒超时"，而机器人不会发
`dissolve_agree`。所以真人申请解散时，`socket_service.on_dissolve_request` 会先用
`robotmgr.auto_agree_dissolve` 替机器人座位投同意票——真人房主一申请就是四票全同意、房间立刻解散，
不用等满 30 秒（真人的 `dissolve_reject` 仍然照常撤销申请）。

> **这是 Python 服务端独有的功能**（`server-python/`）。Node 版 `server/` 没有实现单人模式，
> 因此目前两套服务端在这一点上不对等；客户端对 Node 版点"单人模式"会拿到 404。

离线证据是 `server-python/tests/test_robot.py`：策略单测 + 四个座位全交给机器人的整局模拟
（两份 gamemgr × 有无换三张），另有"打完一局后机器人保持已准备、第二局开得起来"以及
"真人申请解散即全票通过并立即解散、真人仍然能否决"的回归。

---

## 八、通信协议

- **客户端 → 服务端**：Socket.IO 事件在 `server/game_server/socket_service.ts` 里以
  `socket.on(...)` 注册（`login`、`ready`、`huanpai`、`dingque`、`chupai`、`peng`、`gang`、`hu`、
  `guo`、`chat`、`quick_chat`、`voice_msg`、`emoji`、`exit`、`dispress`、`dissolve_*`、`game_ping`…）。
- **服务端 → 客户端**：**39 个推送事件**，对局内统一走 `server/game_server/usermgr.ts` 的
  `sendMsg(userId, event, data)` / `broacastInRoom(event, data, sender, includingSender)`
  （拼写就是 `broacast`，**不要"顺手修正"**）；只有登录/连接阶段的 7 处直接 `socket.emit`。
  客户端在 `client/assets/scripts/GameNetMgr.ts` 用 `cc.vv.net.addHandler(event, fn)` 注册，
  主流转是：服务端推送 → `Net.ts` → `GameNetMgr` `dispatchEvent` → 组件 `this.node.on`。
- **HTTP 接口**：账号服、大厅服、游戏服内部接口各自独立，客户端 `HTTP.ts` **全部用 GET**，
  参数走 query string；大厅服与游戏服统一用 `utils/http.ts` 的 `send(errcode, errmsg, data)` 返回。

> **事件名是客户端与服务端之间唯一的契约，中间没有任何工具链校验。**
> 新增或重命名任何事件名后，必须跑 `npm run check:protocol`（它会双向比对源码，
> 并校验 `docs/ai-native/protocol.md` §1 的事件表）。
> HTTP 路径的增删**不在门禁覆盖范围内**，需人工双向搜索调用方。

---

## 九、验证门禁：`npm run verify`

这是本仓库唯一的"完成"判据，**零依赖、可离线运行**（唯一例外见下），不需要 `npm install`：

```bash
npm run verify                 # 六项全跑（提交前必须全绿）
npm run verify -- --verbose    # 打印每个被检查的文件 / 断言
npm run verify -- --json       # 机器可读结果
npm run verify:list            # 列出检查项
npm run verify -- --only=types # 单跑某一项（六项都可）

# 单项快捷方式
npm run check:syntax
npm run check:protocol
npm run check:smoke
npm run check:harness
npm run test:tools             # 校验检查器自身
```

六项检查（顺序固定 `syntax` → `types` → `harness` → `protocol` → `smoke` → `selftest`）：

| 检查 | 回答的问题 |
| --- | --- |
| `syntax` | 80 个一方脚本（client 47 / server 33）是否都能解析：`.ts` 用 Node 内置 `module.stripTypeScriptTypes` 擦类型解析（只解析不执行，顺带强制只用可擦除语法）；同时校验脚本 `.meta` 与场景组件绑定，并禁止残留一方 `.js` |
| `types` | ① 零依赖 **no-any 审计**：`: any` / `as any` / `<any>` / `@ts-ignore` / `@ts-expect-error` 一律失败；并在 `client/` 查残留 `cc.Class(` 与漏写的 `module.exports = <类名>;`；② 有 `server/node_modules/typescript` 时跑两棵树的 `tsc --noEmit`（strict）。缺编译器时 ② 报 **skipped**，① 照跑 |
| `harness` | 3 份 `AGENTS.md` + 5 个技能是否可被发现、格式合法 |
| `protocol` | Socket.IO 事件词汇表是否两端对齐（39 推送 / 44 处理器 / 文档表三向一致） |
| `smoke` | 听牌/胡牌判定、花色分类、MD5、Base64（含中文昵称）等 19 条断言（**不含算番**） |
| `selftest` | 检查器自身的解析逻辑是否被改动破坏 |

本仓库当前状态：**六项全绿**。

**新增可离线验证的纯逻辑时，请顺手往 `tools/lib/smoke.mjs` 加断言**——宁可多一条断言，
也不要让"我改对了"停留在口头。

> 门禁**不替你做运行时验证**：它不启动进程、不校验 SQL 执行结果、不算番值、不构建客户端。
> 只有真实运行时才能确认的改动，交付说明必须写明"未运行时验证"并列出依赖的静态证据。

---

## 十、代码风格约定（迁移红线）

本仓库经历过**行为不变**的迁移，因此源码风格刻意"老派"，**不要顺手现代化**：

1. **保留 `var` / `function` / 回调**：不要把 `var` 改成 `let` / `const`，不要把回调改成箭头函数
   （老代码里有 `for (var i…) { setTimeout(function(){ … i … }) }` 这类闭包，改了就变行为）。
2. **不引入 `any`**：优先精确类型 → `unknown` + 收窄 → 结构类型；跨动态边界用**一次带注释的断言**。
3. **只允许可擦除类型语法**：不许 `enum` / `namespace` / `import x = require()` / 构造函数参数属性
   （门禁的 `syntax` 检查会直接报红）。只导入类型时用 `import type`。
4. **注释一律用中文**，新增注释也沿用。
5. **客户端组件**一律 `ES6 class` + `@ccclass` / `@property`；`@ccclass` **不要传类名**；
   每个类文件末尾必须有 `module.exports = <类名>;`（Creator 的 `require("X")` 取的是
   `module.exports`，漏了会在启动时抛 `X is not a constructor`）。
6. **不要手工编辑 `.meta` / `.fire`**，不要改 `client/assets/scripts/3rdparty/` 下的 vendored 库。
7. **SQL 只写在 `server/utils/db.ts`**：它是唯一访问层，业务代码不要自己 `require('mysql2')` 或拼 SQL。
8. **改数据库结构**要同时改 `server/sql/db_babykylin.sql`、`db.ts` 的语句与 `server/types/db_rows.ts`。
9. **改玩法逻辑**先读 `docs/ai-native/game-rules.md`，两份 `gamemgr_*` 同步改。
10. **改服务端类型**后跑 `npm run verify -- --only=types`；**改事件名**后跑 `npm run check:protocol`。

逐条细则见 `docs/ai-native/typescript-migration.md`（服务端）与
`docs/ai-native/client-typescript-migration.md`（客户端）。

---

## 十一、文档与 AI Native 工程

本仓库按 DeepSeek Harness 的约定组织项目知识，让任何 AI 会话进入仓库时不必重新摸索架构：

| 载体 | 位置 | 加载时机 |
| --- | --- | --- |
| 指令文件 | `AGENTS.md`、`client/AGENTS.md`、`server/AGENTS.md` | 项目根到工作目录逐层叠加 |
| 项目技能 | `.dsh/skills/<name>/SKILL.md` ×5 | 由 `description` 匹配任务后按需加载 |
| 人类文档 | `docs/ai-native/*.md` | 按需阅读 |

**参考文档**

| 文档 | 内容 |
| --- | --- |
| `docs/ai-native/README.md` | AI Native 开发工程导览 |
| `docs/ai-native/protocol.md` | Socket.IO 协议全景（39 推送 + 20 客户端事件 + HTTP 接口索引） |
| `docs/ai-native/game-rules.md` | 玩法规格：牌编码、听牌算法、动作常量、房间配置 |
| `docs/ai-native/client-map.md` | 客户端目录边界、脚本分层、组件职责、场景图 |
| `docs/ai-native/typescript-migration.md` | 服务端 TS 迁移规范与严格性取舍 |
| `docs/ai-native/client-typescript-migration.md` | 客户端 TS 迁移规范与 `@property` 逐项对应 |
| `docs/ai-native/skills-guide.md` | 技能加载规则与新增模板 |

**项目技能**：`verify-gate`、`server-architecture`、`game-rules`、`client-integration`、`data-layer`。

---

## 十二、明确的边界：哪些东西没有被自动验证

| 项目 | 原因 |
| --- | --- |
| 服务端运行时行为 | 门禁不启动进程；DB 相关路径（注册/登录/建房）需要真实 MySQL |
| SQL 的执行结果 | 无数据库实例，门禁只做语法与类型检查 |
| 客户端构建与运行 | Creator 2.4.15 依赖图形化编辑器，无法无头编译；`library/`、`temp/` 是本机产物 |
| HTTP 接口路径的增删 | 门禁只覆盖 Socket.IO 事件名，不覆盖 Express 路由 |
| `.fire` / `.meta` / 美术资源 | 由编辑器维护，需人工在编辑器内验证 |
| 番型算分的业务正确性 | 只有听牌/胡牌判定有断言；具体番值需产品确认，无法凭代码自证 |
| 七对（七小对） | **当前引擎未实现**，冒烟断言把"不认七对"这一现状钉住 |

---

## 十三、开源协议与致谢

- 本项目基于 **[幼麟棋牌 · 四川麻将开源版](https://github.com/babykylin/babykylin_scmj)**
  （作者：麒麟子 / 成都幼麟科技有限公司）的最新代码升级而来，感谢原作者的开源。
  上游同步仓库：[GitHub](https://github.com/babykylin/babykylin_scmj) ·
  [Gitee](https://gitee.com/qilinzi/babykylin_scmj)。
- 上游开源协议见：
  <https://github.com/babykylin/babykylin_scmj/wiki/开源协议>。
- 上游技术文章：麒麟子博客 <https://qilinzi.blog.csdn.net/>。
