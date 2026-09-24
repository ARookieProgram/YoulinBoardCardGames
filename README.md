# 幼麟四川麻将 · 增强版

本仓库基于 **[幼麟棋牌 · 四川麻将开源版](https://github.com/babykylin/babykylin_scmj)**（作者：麒麟子 / 成都幼麟科技有限公司）的**最新代码**，
在上游"可运行的四川麻将完整实现"之上，**新增**了一整套现代化改造与运营能力。

> 阅读顺序建议：想跑起来看 [§5 快速开始](#五快速开始)；关心新增了什么看 [§2 新增总览](#二新增总览相对上游)；
> 想改代码先读 [§12 代码风格约定](#十二代码风格约定迁移红线) 与仓库根的 `AGENTS.md`。

---

## 一、项目简介

一套可运行的开源**四川麻将（血战到底 / 血流成河）**完整实现，四块并列的代码：

| 模块 | 目录 | 技术栈 | 端口 |
| --- | --- | --- | --- |
| 游戏客户端 | `client/` | Cocos Creator **2.4.15** + TypeScript | — |
| 游戏服务端（Node 版） | `server/` | Node.js ≥18 + **TypeScript（`strict`）** + Express + Socket.IO + MySQL | 9000 / 12581 / 9001 / 9002 / 10000 / 9003 |
| 游戏服务端（Python 版） | `server-python/` | **Python 3.14** + asyncio + aiohttp + 自研 Socket.IO 协议层 + aiomysql | 同上（**二选一，不要同时起**） |
| 游戏管理平台 | `server-python/platform_server/` + `admin-platform/` | **Django 6.1 + DRF + SimpleJWT** ／ **Vue 3 + TS + Element Plus + Pinia + Vite** | **8000** / dev 5173 |

两套游戏服务端（Node 版与 Python 版）**端口、HTTP 路由、md5 签名、Socket.IO 事件名、MySQL schema 逐字对应**，
现有客户端一行都不用改就能互换使用。**管理平台是独立的第三块**，跑 8000 端口、用独立的库与账号表，
与游戏服务端**可以同时运行**，但**账号体系完全隔离**。

---

## 二、新增总览（相对上游）

上游只提供"客户端 + Node 版服务端"的 ES5 实现。本仓库在此之上新增了下面这些**代码**（按新增体量排序）：

| # | 新增内容 | 位置 | 说明 |
| --- | --- | --- | --- |
| 1 | **游戏管理平台** | `server-python/platform_server/` + `admin-platform/` | 全新的一块：Django REST 后端 + Vue 3 后台。玩家管理 / 房间管理 / 对局记录 / 管理员账号 / 封禁解封，独立库 `db_scmj_admin` |
| 2 | **Python 3.14 服务端重写版**（三进程） | `server-python/` | 与 Node 版行为一致的完整重写，含**自研 Socket.IO 协议层** `game_server/sio_server.py` |
| 3 | **单人模式（人机对战）** | `server-python/game_server/robotmgr.py` + `client/.../CreateRoom.ts` | 建房面板新增开关，服务端自动补三个机器人，免房卡。**Python 版独有** |
| 4 | **封禁联动链路** | `server/utils/bancheck.ts` + `server-python/utils/bancheck.py` + `apps/players/internal.py` | 管理平台封禁 → 游戏服登录 / 进房时拦下，客户端提示"账号已被封禁" |
| 5 | **对局归档与后台对局记录** | `t_games_archive` + `apps/games/` | 房间结束即归档；后台只读归档表，可看单局四家出牌流水 |
| 6 | **服务端 TypeScript 迁移** | `server/` | ES5 JS → TS（`strict: true`），`tsc` → `server/dist/` 后运行，**行为不变** |
| 7 | **客户端 TypeScript 迁移 + 引擎升级** | `client/` | Cocos Creator 2.0.6 → **2.4.15**；`cc.Class` → ES6 `class` + `@ccclass` / `@property` |
| 8 | **零依赖验证门禁** | `tools/verify.mjs`（**七项检查**） | 本仓库唯一的"完成"判据，`npm run verify` |
| 9 | **AI Native 工程契约** | `AGENTS.md` ×5 + `.dsh/skills/` ×5 + `docs/ai-native/` | 让任何 AI 会话进仓库时不必重新摸索架构 |
| 10 | **依赖与启动工程化** | `yarn.lock`、`start_all_mac.sh`、`utils/startup.ts` | 去掉 `fibers` / `mysql` 两个原生依赖包袱；统一启动横幅与端口自检 |

### 与上游的逐项差异

| 维度 | 上游（babykylin_scmj） | 本仓库 |
| --- | --- | --- |
| 客户端引擎 | Cocos Creator 2.0.6 | **Cocos Creator 2.4.15** |
| 客户端语言 | ES5 JavaScript（`cc.Class`） | **TypeScript**（ES6 `class` + `@ccclass` / `@property`） |
| 服务端语言 | ES5 JavaScript（直接 `node` 运行） | **TypeScript**（`strict`，`tsc` → `server/dist/` 后运行） |
| 服务端第二实现 | 无 | **Python 3.14 重写版**（`server-python/`，同端口同协议） |
| 运营后台 | 无 | **游戏管理平台**（Django 6.1 + Vue 3） |
| 单人模式 | 无 | **有**（Python 版；Node 版未实现） |
| 封禁体系 | 无 | **有**（管理平台落库 + 游戏服 fail-open 校验） |
| Node.js | v6.x（原文注明"高版本可能无法启动"） | 声明 `>=18`，**mac + Node 24 已实测三进程可启动** |
| 依赖管理 | 直接提交 `node_modules` | **yarn 1.x + `yarn.lock`**，`node_modules` 不提交 |
| 数据库驱动 | `mysql`（仅 `mysql_native_password`） | **`mysql2`**（Node）/ **`aiomysql`**（Python），兼容 MySQL 8 的 `caching_sha2_password` |
| 同步 HTTP | `fibers` 原生模块 | 已移除，改回回调风格（`server/utils/http.ts` 的 `getRaw`） |
| 工程化 | 无自动检查 | **零依赖验证门禁 `npm run verify`**（七项）+ AI Native 工程契约 |

> 「本仓库的一方源码一律是 TypeScript」这一点在两个目录都成立；区别只是客户端由 Creator 自己编译、
> 没有构建步骤，服务端则由 `tsc` 编译到 `dist/`。Python 服务端与 Django 后台自然例外。

**所有迁移都是"行为不变"的**：玩法规则、事件名、载荷字段、日志文案一律保留原样，连历史 bug 都刻意保留（见 §4.2）。

---

## 三、系统架构

```
┌──────────────────────────┐        ┌────────────────────────────────────┐
│  游戏客户端                │        │  游戏管理平台（后台，独立第三块）        │
│  Cocos Creator 2.4.15     │        │  admin-platform (Vue 3)  :5173     │
└──────────────────────────┘        │        │ HTTP /api/…               │
   │                                │        ▼                           │
   │ HTTP  →  账号服 :9000  注册/登录/游客 │  platform_server (Django)  :8000   │
   │ HTTP  →  账号服 :12581 渠道/代理 API  │        │                           │
   │ HTTP  →  大厅服 :9001  登录/建房/战绩 │        └─► MySQL db_scmj_admin      │
   │ Socket.IO → 游戏服 :10000 对局实时协议 │             （独立库：管理员 / 封禁流水）│
   │                                └────────────────────────────────────┘
   │                                                 ▲  内部只读接口（共享密钥）
   │                                                 │  /api/internal/players/ban-check/
   ▼                                                 │
┌──────────────────────────────────────────────┐     │
│  游戏服务端（Node 版 server/ 与 Python 版        │─────┘
│  server-python/ 二选一，6 个端口完全一致）        │
│  大厅服 ──HTTP(签名)──► 游戏服 http_service :9003 │
│  游戏服 ──HTTP────────► 大厅服 room_service :9002 │
└──────────────────────────────────────────────┘
   │
   ▼
 MySQL  db_scmj（玩家库：账号 / 房间 / 对局归档；建表见 server/sql/db_babykylin.sql）
```

### 端口与进程

| 进程 | Node 版入口（编译后） | Python 版入口 | 端口 | 用途 |
| --- | --- | --- | --- | --- |
| 账号服 | `dist/account_server/app.js` | `account_server.app` | **9000** | 客户端 HTTP：`/guest`、`/register`、登录… |
| 账号服（同进程） | 同上 | 同上 | **12581** | 代理 API：`/get_user_info`、`/add_user_gems`… |
| 大厅服 | `dist/hall_server/app.js` | `hall_server.app` | **9001** | 客户端 HTTP：`/login`、`/create_private_room`、`/enter_private_room`、`/get_history_list`… |
| 大厅服 | 同上 | 同上 | **9002** | 游戏服 → 大厅服上报 |
| 游戏服 | `dist/game_server/app.js` | `game_server.app` | **10000** | 客户端 Socket.IO 对局协议（唯一入口 `socket_service`） |
| 游戏服 | 同上 | 同上 | **9003** | 大厅服 → 游戏服内部 HTTP（接口都校验 `sign`） |
| **管理平台后端** | — | `platform_server/manage.py` | **8000** | 后台 REST API（JWT） |
| **管理平台前端** | — | `admin-platform`（dev） | **5173** | 后台界面（Vite dev server） |

- 账号服是**一个进程两个 HTTP 服务**（客户端端口 + 代理 API 端口）。
- 三个进程都通过**命令行参数**接收配置文件：`node dist/game_server/app.js ../configs_mac.js` /
  `python -m game_server.app ../configs_mac.py`。
- 启动横幅统一打印：**所有端点真正 listening 之后才显示"启动成功"**，端口被占用时打印明确原因并以非 0 退出；
  传入 `db` 时横幅附带一次数据库连通性自检。
- Game 服与平台 8000 端口**互不冲突**，可以同时运行；但 Node 版与 Python 版游戏服务端**不要同时起**。

### 一次登录的链路

```
1. 客户端 → 账号服  GET /guest                      换取签名与大厅地址
2. 客户端           cc.vv.http.url 切换为账号服下发的大厅地址
3. 客户端 → 大厅服  GET /login?account=&sign=        取得 userid 等资料
4. 客户端 → 大厅服  GET /enter_private_room?...      取得 {ip, port, token, roomid, time, sign}
5. 客户端 → 游戏服  socket.io 连接 ip:port，emit('login', {token, roomid, time, sign})
6. 游戏服          校验 md5(roomid + token + time + ROOM_PRI_KEY) == sign
```

> **改任一侧的签名拼接顺序或密钥，都会导致全部登录失败。** 签名原语在 `server/utils/crypto.ts`（Python 侧
> `server-python/utils/crypto.py`），两侧拼接分别在 `hall_server/room_service` 与 `game_server/socket_service`。
>
> 大厅服的 `/login`、`/create_private_room`、`/enter_private_room` 与游戏服的 socket `login`
> 在校验签名之后、放行之前还会**多问一句管理平台**（封禁校验，fail-open），见 §7。

---

## 四、服务端：Node TypeScript 迁移 与 Python 3.14 重写版

### 4.1 `server/` —— ES5 JavaScript → TypeScript（strict）

- 一方源码全是 `.ts`（含 `server/tests/*.ts`），`strict: true`，用 `tsc` 编译到 `server/dist/` 后运行；
  **跑的是编译产物，改完必须先 `yarn build`**。
- 这次是**行为不变的纯类型迁移**，所以服务端里同样保留 `var` / `function` / 回调写法——
  **不要把 `var` 改成 `let` / `const`，也不要把回调改成箭头函数**；模块语法换成 `import` / `export`。
- 共享类型在 `server/types/`（`config` / `domain` / `protocol` / `db_rows` / `*.d.ts`）。
- 依赖瘦身：移除原生模块 `fibers`（`utils/http.ts` 的同步 HTTP 改回回调风格 `getRaw`），
  数据库驱动 `mysql` → `mysql2`（支持 MySQL 8 默认认证）。

运行时依赖只有 4 个：`express`、`log4js`（历史遗留、当前无引用）、`mysql2`、`socket.io`。

### 4.2 `server-python/` —— Python 3.14 重写版

`server-python/` 是 `server/` 的完整重写：**同样的三个进程、同样的 6 个端口、同样的 HTTP 路由、
同样的 md5 签名、同样的 Socket.IO 事件名、同一套 MySQL schema**。目标是与现有客户端和数据库完全兼容。

```
server-python/
├─ manage.py                    ← 三进程管理（start/stop/status/restart/logs）
├─ start_all_mac.sh             ← 薄壳，接口与 server/start_all_mac.sh 一致
├─ requirements.txt             ← 运行时依赖（4 个）
├─ configs_mac.py / configs_win.py  ← 唯一配置来源（函数式导出，两平台各一份）
├─ shared/                      ← 跨进程共享的类型契约与域模型（不是 types/：会遮蔽标准库）
├─ utils/                       ← crypto / config / db / http / startup / jscompat / bancheck
├─ account_server/              ← 账号服 :9000，含 dealer_api :12581
├─ hall_server/                 ← 大厅服 :9001、:9002
├─ game_server/                 ← 游戏服 :10000、:9003
│   ├─ sio_server.py            ← Engine.IO 3 / Socket.IO 4 协议层（自研）
│   ├─ robotmgr.py              ← 单人模式的机器人（Python 独有）
│   ├─ gamemgr_xlch.py          ← 血流成河
│   └─ gamemgr_xzdd.py          ← 血战到底
├─ platform_server/             ← 管理平台后端（Django，见 §6）
└─ tests/                       ← 离线测试（stdlib unittest，无第三方依赖）
```

#### 为什么自己实现 Socket.IO 协议层

客户端是 vendored 的 **socket.io-client 1.x**（Socket.IO 协议 4 / Engine.IO 协议 3）。两条现成的路都走不通：

- `python-socketio` 5.x / `python-engineio` 4.x **硬编码拒绝 EIO=3**，客户端连握手都过不去；
- 支持 EIO3 的 `python-socketio` 4.6.1 在 **Python 3.14 上跑不起来**：`asyncio.wait()` 从 3.12 起禁止传协程，
  而它正是用 `asyncio.wait([...coroutines])` 实现 `emit` —— 也就是**所有服务端推送**都会抛 `TypeError`。

所以 `game_server/sio_server.py` 自己实现了这一层，只覆盖本仓库真正用到的特性：websocket + polling 两种传输、
五种 Engine.IO 包、三种 Socket.IO 包、JSON 载荷（无二进制 / 无 namespace / 无 ack）。两个容易踩的点：

1. **EIO3 是客户端发 ping、服务端回 pong**（EIO4 反过来）；
2. **服务端才是 CONNECT 包的发起方**：socket.io 1.x 的客户端在默认 namespace 下**不发** `40`，
   它等收到服务端的 `40` 才触发 `connect`。顺序反了就是"客户端永远不 connect"。

#### 与 Node 版的有意差异

移植原则是**行为一致**，以下是刻意不同的地方：

| 差异 | 说明 |
| --- | --- |
| **并发模型** | 回调 + `setTimeout` → `async`/`await` + `asyncio`；`db.*` 直接 `return` 结果。**逻辑顺序与 Node 版一致** |
| **错误不再杀死进程** | Node 版在 db / socket 回调里 `throw err` 会导致整个进程退出；Python 版记录日志并把异常抛给协程调用方，进程继续服务 |
| **历史 bug 一样保留** | 标着"移植不修"的地方 Python 版同样保留，并在函数注释里标明原因（如 `tokenmgr.is_token_valid` 读小写 `lifetime` 导致 token 永不过期、`hall_server.check_account` 签名校验被注释掉等）。要修任何一条都是**单独一次改动** |
| **一处确实改掉的差异** | `utils/http.request_ip()` 把裸 IPv4 补成 `::ffff:a.b.c.d` 对齐 Express 的 `req.ip`；拼 URL 时给 IPv6 主机加方括号（否则 `http://::1:19003/...` 是非法 URL） |
| **`game_over_push` 的键集** | 跟着 `JSON.stringify` 的"有没有赋值"，不是跟着默认值——这些结算字段只在特定分支才被赋值，客户端一律只做真值判断 |

`configs_mac.py` / `configs_win.py` **必须同步修改**。启动方式：

```bash
cd server-python
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 需要 Python 3.14.x
./start_all_mac.sh                 # 启动 + 状态表
./start_all_mac.sh status          # 只查状态；6 个端口全部就绪退出码 0
./start_all_mac.sh logs game        # 跟踪某个进程日志
./start_all_mac.sh stop
```

离线测试（零依赖，必跑）：

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

`tests/test_protocol.py` 是最有价值的一项：它**跨实现比对** Python 推送事件名集合 == `docs/ai-native/protocol.md`
的表格 == Node 源码里的事件名集合，并用**由 Node 实现算出的常量参考向量**校验 Python 的 md5 签名结果。

### 4.3 单人模式（人机对战，Python 版独有）

大厅建房面板底部有一个**代码动态生成**的"单人模式"开关
（`client/assets/scripts/components/CreateRoom.ts` 的 `setupSingleModeToggle`，不改 `hall.fire`）。打开后：

1. 客户端仍然提交同一份 `conf`，只是多带 `single: 1`，并改调大厅服的 `/create_single_room`；
2. 大厅服把 `single: 1` 写进 conf 后转给游戏服（与 `/create_private_room` 同一套签名）；
3. 游戏服建房时预置三个机器人并**跳过房卡校验**，真人进房坐 0 号位，登录后四人齐、直接开局。

机器人是**没有 socket 的普通座位**：`roommgr._seat_robots` 把 1~3 号座位写进 `user_location` 并 `ready=True`，
`usermgr.is_online` 对它们恒返回 `True`（否则 `set_ready` 的"四人齐"判断过不去），推送则因查不到连接被静默丢弃。
真正的出牌由 `game_server/robotmgr.py` 驱动：gamemgr 在 `send_operations` / `begin` / `huan_san_zhang` / `peng`
**四个钩子点**调用 `robotmgr.schedule(...)`，机器人延迟一小段时间后按"能胡就胡 / 能杠就杠 / 能碰就碰 /
先打缺门再打孤张"的确定性策略回调 gamemgr 的动作函数。

解散房间同样要照顾机器人：解散是"四家投票、全票才生效、否则 30 秒超时"，而机器人不会发 `dissolve_agree`。
所以真人申请解散时，`socket_service.on_dissolve_request` 会先用 `robotmgr.auto_agree_dissolve` 替机器人座位投同意票
——真人房主一申请就是四票全同意、房间立刻解散（真人的 `dissolve_reject` 仍然照常撤销申请）。

> **这是 Python 服务端独有的功能**。Node 版 `server/` 没有实现单人模式，客户端对 Node 版点"单人模式"会拿到 404。

`conf.single` **不落库**（`db._conf_to_wire` 的键集与 Node 版一致），所以进程重启后从库里还原的单人房会丢掉这个标记
——单人房本来就是新建即打完的，不影响正常流程。

离线证据是 `server-python/tests/test_robot.py`：策略单测 + 四个座位全交给机器人的**整局模拟**
（两份 gamemgr × 有无换三张），另有"打完一局后机器人保持已准备、第二局开得起来"以及
"真人申请解散即全票通过并立即解散、真人仍然能否决"的回归。

---

## 五、快速开始

### 5.1 环境要求

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| Node.js | **>= 18** | Node 版游戏服务端、验证门禁（mac + Node 24 已实测） |
| yarn | **1.x**（1.22.22） | `server/` 依赖管理，以 `yarn.lock` 为准 |
| MySQL | 5.7 / 8.x | 玩家库 `db_scmj`；MySQL 8 默认认证方式也可（驱动是 `mysql2` / `aiomysql`） |
| Cocos Creator | **2.4.15** | 客户端开发与构建（图形化编辑器，无法在本仓库内无头编译） |
| Python | **3.14.x** | Python 版游戏服务端 + 管理平台后端 |
| npm | 随 Node | _仅_ 管理平台前端 `admin-platform/` |

### 5.2 初始化玩家库

```bash
# 建库建表 + 初始数据（schema 以此文件为权威）
mysql -uroot -p < server/sql/db_babykylin.sql
```

主要数据表：`t_accounts`、`t_users`、`t_guests`、`t_rooms`（存活房间）、`t_games`（在局）/
`t_games_archive`（**新增**：房间结束后的归档）、`t_message`。

### 5.3 启动游戏服务端（Node 版 **或** Python 版，二选一）

**Node 版**

```bash
cd server
yarn install --frozen-lockfile
yarn build                                      # tsc -> dist/
# 按本机情况修改数据库口令等配置（见 configs_mac.ts / configs_win.ts）
./start_all_mac.sh                              # 启动并打印状态表
./start_all_mac.sh status                       # 只看状态；全部就绪退出码 0
./start_all_mac.sh logs game                    # account / hall / game
./start_all_mac.sh stop                         # 优雅停止
./start_all_mac.sh restart
```

> `../configs_mac.js` 的相对语义：`require` 相对**入口模块目录**解析，编译后入口在 `dist/<进程>/`，
> 所以它指向 `dist/configs_mac.js`。若提示缺入口，先执行 `yarn build`。

**Python 版**

```bash
cd server-python
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./start_all_mac.sh
./start_all_mac.sh status
```

也可以前台分别调试单个进程（Node 版 `node dist/<进程>/app.js ../configs_mac.js`，
Python 版 `.venv/bin/python -m <进程>.app ../configs_mac.py`）。

### 5.4 运行客户端

1. 用 **Cocos Creator 2.4.15** 打开 `client/` 目录（**不是**仓库根目录），等待资源导入完成。
2. 按需修改账号服地址：`client/assets/scripts/HTTP.ts` **第 2 行**（默认 `http://127.0.0.1:9000`，
   部署到真机 / 服务器时必须改）。游戏服地址不用改——它由服务端在登录流程里下发。
3. 在编辑器里预览运行，或构建到 **iOS / Android / H5**。

> 客户端**没有构建步骤、也不需要打包器**：`.ts` 由 Creator 自带的 TypeScript 按 `client/tsconfig.json` 编译，
> 产物在 `client/temp/quick-scripts/`（不提交）。新增或改名脚本后必须回编辑器重新导入；
> `.meta` 由 Creator 维护，不要手工编辑。

### 5.5 启动管理平台

```bash
# ---- 后端（Django，:8000）----
mysql -uroot -p -e "CREATE DATABASE db_scmj_admin DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
cd server-python
.venv/bin/pip install -r platform_server/requirements-platform.txt
cd platform_server
cp .env.example .env                            # 按需改 PLATFORM_DB_* / PLATFORM_PLAYER_DB_*
./scripts/run.sh init                           # 建表 + 建初始超级管理员（打印账号口令）
./scripts/run.sh                                # 启动，等 /api/health/ 通过后打印状态表

# ---- 前端（Vue 3，dev :5173）----
cd admin-platform
npm install
npm run dev                                     # → http://127.0.0.1:5173
```

浏览器打开 <http://127.0.0.1:5173/>，用 `run.sh init` 输出的账号登录。
启停脚本 `./scripts/run.sh` 还支持 `stop` / `restart` / `status` / `logs` / `check`（环境自检，不启动）。

### 5.6 配置说明

- 游戏服务端的配置**唯一来源**是 `configs_mac.ts|py` 与 `configs_win.ts|py`（函数式导出，
  `export function account_server(){...}`），**必须同步修改**。端口、密钥（`ACCOUNT_PRI_KEY` / `ROOM_PRI_KEY`）、
  数据库连接都在这里；**不要在业务代码里硬编码端口或密钥**。三进程入口通过 `process.argv[2]` 读配置文件。
- 管理平台后端的配置**只有 `platform_server/config/settings.py` 一个来源**，全部从环境变量读
  （模板见 `platform_server/.env.example`）。关键项：`PLATFORM_DB_*`（**管理平台独立库，不要指向 `db_scmj`**）、
  `PLATFORM_PLAYER_DB_*`（玩家库**只读**别名）、`PLATFORM_SECRET_KEY`（生产必改）、`PLATFORM_INTERNAL_KEY`
  （**必须与游戏服的 `ban_check()["PRI_KEY"]` 逐字一致**）。
- 管理平台前端不直连后端：请求同源 `/api`，由 Vite 代理转发（`VITE_API_PROXY_TARGET`，默认 `http://127.0.0.1:8000`），
  开发期不涉及 CORS。环境变量见 `admin-platform/.env.example`。

---

## 六、游戏管理平台

管理平台由两半组成，**只与彼此通信**，与 `client/` 无关：

| 半 | 目录 | 技术栈 | 端口 |
| --- | --- | --- | --- |
| 后端 | `server-python/platform_server/` | Django 6.1 + DRF + SimpleJWT + django-cors-headers + PyMySQL | 8000 |
| 前端 | `admin-platform/` | Vue 3（`<script setup>` + TS）+ Element Plus + Pinia + Vue Router + Vite | dev 5173 |

### 6.1 账号体系完全隔离（改动前必读的红线）

| | 管理平台 | 游戏服务端 |
| --- | --- | --- |
| 数据库 | **`db_scmj_admin`**（独立库） | `db_scmj` |
| 账号表 | `AdminUser`（`accounts_adminuser`） | `t_accounts` / `t_users` |
| 认证 | JWT（access + 轮换 refresh） | 自研 md5 签名 token |

隔离是需求本身，不是风格选择：

- ❌ 不要复用 `t_accounts` 当管理员表——玩家侧口令是**明文**且玩家可自行注册，拿它做后台等于没有防线；
- ❌ 不要签发 / 校验游戏 token——两套 token 的算法、密钥、信任域都不同；
- ❌ 不要改 `t_accounts.password` 的明文存储方式（要改就成对改两套游戏服务端）；
- ✅ 需要展示玩家数据时，走**唯一一条显式的只读数据源**（见下）；
- ✅ 游戏服要读封禁状态时走 `/api/internal/players/ban-check/`（共享密钥、只读、HTTP），
  不要让游戏服直连 `db_scmj_admin`——那会把平台的表结构变成对外契约。

### 6.2 数据来源：一条显式的只读数据源

唯一读玩家库的地方是 `apps/players/player_source.py`，走 `settings.DATABASES["player"]`，
**只执行 SELECT**（`_assert_read_only()` 硬校验，测试断言玩家库连接上没有非 SELECT）。
玩家库上**没有模型、没有迁移**。

| 数据 | 来源 | 读写 |
| --- | --- | --- |
| 玩家账号 / 昵称 / 房卡 `gems` / 金币 / 等级 / 所在房间 | 玩家库 `t_users` | **只读** |
| 存活房间（配置 / 座位 / 所在游戏服） | 玩家库 `t_rooms` | **只读** |
| 对局记录（**只读归档表 `t_games_archive`**，刻意不读在局表 `t_games`） | 玩家库 | **只读** |
| 封禁状态与封禁流水 | 管理平台库 `players_playerban` | 读写（本平台自己的表） |
| 管理员账号 | 管理平台库 `accounts_adminuser` | 读写 |

> **对局记录为什么只读归档表**：游戏服**每结束一局才写一行** `t_games`，房间打完 / 被解散时才把整房间的
> 对局归档进 `t_games_archive`（`INSERT INTO t_games_archive SELECT * FROM t_games WHERE room_uuid=…`）。
> 所以后台看到的每一局都是终局，房间还在打的对局查不到——这是业务口径，不是遗漏。
>
> `apps/games/decoding.py` 是**全平台唯一"懂玩法"的文件**（牌 id 0~26、动作编号 1~6），
> 改它要同步看 `docs/ai-native/game-rules.md` 与游戏服两份 `gamemgr_*`，
> 因为后台展示的"出牌记录"必须与客户端回放是同一个口径。

### 6.3 后端接口

所有接口返回统一外壳 `{ "code": 0, "message": "ok", "data": { } }`；HTTP 状态码仍然有意义
（前端按状态码决定"是否跳登录页"，按 `code` 决定"弹什么提示"）。

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/health/` | 否 | 健康检查（**不查数据库**，用于区分"进程活着"与"库连不上"） |
| `POST` | `/api/auth/login/` | 否 | 账号 + 口令 → access/refresh + 管理员信息 |
| `POST` | `/api/auth/refresh/` | 否 | refresh → 新 access（**并轮换 refresh**） |
| `GET` | `/api/auth/me/` | 是 | 当前登录管理员信息 |
| `POST` | `/api/auth/logout/` | 是 | 吊销 refresh |
| `GET/POST` | `/api/admins/` | **超级管理员** | 管理员列表 / 新建 |
| `GET` | `/api/admins/overview/` | **超级管理员** | 概览：总数 / 启用 / 停用 / 超级管理员数 |
| `GET/PATCH/DELETE` | `/api/admins/<id>/` | **超级管理员** | 详情 / 改资料与角色（账号名不可改）/ 删除 |
| `POST` | `/api/admins/<id>/status/` | **超级管理员** | 启用 / 停用 |
| `POST` | `/api/admins/<id>/password/` | **超级管理员** | 重置他人口令 |
| `POST` | `/api/admins/me/password/` | 是 | **改自己的口令**（需原口令，任何角色可用） |
| `GET` | `/api/players/` · `/overview/` · `/<id>/` | 是 | 玩家列表 / 概览 / 详情 + 封禁流水 |
| `POST` | `/api/players/<id>/ban/` · `/unban/` | 管理员及以上 | 封禁（可限时）/ 解封 |
| `GET` | `/api/players/<id>/recharges/` | 是 | **预留**：充值记录（返回 `reserved: true`） |
| `GET` | `/api/rooms/` · `/overview/` · `/<room_id>/` | 是 | 存活房间列表 / 概览 / 详情（`room_id` 可为房间号或 uuid） |
| `POST` | `/api/rooms/<room_id>/dissolve/` | 管理员及以上 | **预留**：强制解散（恒返回 `reserved: true`） |
| `GET` | `/api/games/` · `/overview/` | 是 | 归档对局列表 / 概览 |
| `GET` | `/api/games/rooms/<房间号或uuid>/` | 是 | 一个房间的全部归档对局 + 四个座位 |
| `GET` | `/api/games/rooms/<房间号或uuid>/<局号>/` | 是 | **单局详情：四家出牌记录**（时间线 + 每人动作 + 开局快照） |
| `GET` | `/api/games/players/<玩家ID>/` | 是 | 某个玩家的房间战绩（`t_users.history`，最多最近 10 场） |
| `GET` | `/api/internal/players/ban-check/` | **共享密钥** | **内部接口**：给游戏服查封禁状态（不走 JWT） |
| — | `/admin/` | Django session | Django 自带的数据库管理站点（运维兜底，不是本平台前端） |

**业务错误码**只定义在 `apps/common/error_codes.py`（**全平台唯一一份**），按段划分：
`10xxx` 通用、`11xxx` 登录、`12xxx` 玩家管理、`13xxx` 房间管理、`14xxx` 对局记录、`15xxx` 管理员账号管理。
其中 `15004`（不能对自己下手）与 `15005`（不能停用 / 删除 / 降级最后一个启用中的超级管理员）是两条**自锁护栏**，
由后端判定，前端置灰只是提示。前端对应常量在 `admin-platform/src/api/types.ts`，**改一处要同步另一处**。

### 6.4 前端

已交付**登录闭环 + 后台骨架 + 玩家管理 + 房间管理 + 对局记录 + 管理员账号**：

- 登录页（表单校验、错误提示、回车提交、后端可达性探测）；Pinia 登录态 + localStorage 持久化；
- 请求层 axios 拦截器：拆响应外壳 + **401 自动续期并重放原请求**（并发 401 只触发一次刷新）；
- 路由守卫（未登录跳登录页、刷新页面恢复登录态、角色不足挡回控制台）；
- 后台布局（侧边菜单 + 顶栏 + 退出登录 + 修改自己的密码）；
- **玩家管理**：查询 / 房卡展示 / 封禁解封；详情抽屉的「对局记录」Tab 展示最近 10 场战绩，「充值记录」仍是预留入口；
- **房间管理**：只读监控存活房间（列表 / 概览 / 详情：配置、四个座位、所在游戏服），并预留"强制解散"入口；
- **对局记录**：归档列表（关键字 / 玩法 / 日期区间 / 排序 / 分页）+ 概览 + 一个房间的全部对局 +
  **单局出牌记录**（全局时间线 / 分每个玩家的出牌顺序 / 开局手牌与牌墙）+ 某个玩家的最近战绩；
- **管理员账号**（仅超级管理员）：查询 / 新建 / 改资料与角色 / 启停 / 重置口令 / 删除。

加页面只需往 `admin-platform/src/router/routes.ts` 的 `children` 里加一条（带 `meta.title`，可选 `meta.icon`），
**菜单会自动派生**；需要"仅超级管理员"就加 `meta.requiresSuperAdmin: true`。

```bash
cd admin-platform
npm run type-check      # vue-tsc --build（strict，含 noUncheckedIndexedAccess）
npm run build           # type-check + 生产构建到 dist/
```

### 6.5 管理平台怎么验证

```bash
cd server-python/platform_server

# 1) 接口测试（不需要 MySQL）。260 项
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test

# 1b) 建库 SQL 是否与迁移一致（改了模型必跑；sql/db_scmj_admin.sql 是生成产物，不要手改）
./scripts/check_sql_fresh.sh

# 2) 真实 HTTP 端到端。128 项
./scripts/run.sh                      # 启动（等健康检查通过）
./scripts/e2e_login_check.sh
./scripts/run.sh stop
```

> 仓库根门禁的 `check:python` 只会 **AST 解析**本目录每个 `.py` 并跑 `server-python/tests/` 下的离线测试，
> **不会执行 Django 测试**——别以为门禁绿了就等于本平台的测试跑过了。

---

## 七、封禁联动链路

管理平台封禁一个玩家后，游戏服在**登录 / 进房那一刻**拦下他。这条链路是新增代码里唯一一条
**跨模块运行时契约**：

```
管理平台（写）                         游戏服（读）
players_playerban  ──►  GET /api/internal/players/ban-check/
（db_scmj_admin）        ?account=..&sign=md5("account"+account+"player_id"+player_id+PRI_KEY)
                        ◄── { banned, reason, until, … }
```

- 链路两端：`server/utils/bancheck.ts`（Node）与 `server-python/utils/bancheck.py`，
  **行为与签名必须逐字一致**；平台侧是 `apps/players/internal.py`。
- 调用点：大厅服的 `/login`、`/create_private_room`、`/enter_private_room`（以及 Python 独有的 `/create_single_room`），
  和游戏服的 socket `login`。
- 三条运行语义：**fail-open**（超时 / 连不上 / 平台返回非 0 → 放行 + 警告日志，"管理后台挂掉不该让全体玩家登不上游戏"）、
  **缓存**（成功结果按 30 秒缓存，失败后 5 秒冷却）、**共享密钥**（`ban_check()["PRI_KEY"]` 必须等于平台的
  `PLATFORM_INTERNAL_KEY`，不一致表现为"封禁静默失效"）。
- 封禁**最迟 30 秒内生效**，且**不会打断正在进行的对局**（只在登录 / 进房那一刻拦）。
- 客户端提示：大厅服登录被拒见 `client/.../UserMgr.ts`，游戏服进房被拒的业务码是 **`errcode=4`**，
  见 `client/.../GameNetMgr.ts`。

签名参考向量同时钉在两处：`server-python/tests/test_protocol.py::SignatureTest` 与
仓库根 `tools/lib/smoke.mjs`（门禁 `smoke` 项）。

---

## 八、对局归档与后台「对局记录」

- 游戏服**每结束一局**写一行 `t_games`（在局过程，含 `action_records`）；
- **房间结束（打完 / 被解散）**时归档到 `t_games_archive`
  （`INSERT INTO t_games_archive SELECT * FROM t_games WHERE room_uuid='…'`），Node 与 Python 两版都实现；
- 后台"对局记录"**只读归档表**，所以看到的一定是终局；
- `action_records` 是**动作编号序列**（`1 出牌 / 2 摸牌 / 3 碰 / 4 杠 / 5 胡 / 6 自摸`），
  后台由 `apps/games/decoding.py` 解读成中文动作与牌面。

> **回放兼容红线**：动作常量**只能追加**，不能修改或复用；`action_records` 是 `varchar(2048)`，
> 单局动作序列**不能超过 2048 字节**，超长会被静默截断，导致回放不完整。

---

## 九、目录结构

```
babykylin_scmj/
├─ client/                       Cocos Creator 2.4.15 客户端
│  ├─ assets/
│  │  ├─ scenes/                 场景：start / loading / login / createrole / hall / mjgame
│  │  ├─ scripts/                46 个一方脚本（12 个管理器 + components/ 34 个组件）
│  │  │  ├─ Net.ts               socket.io 连接、心跳、addHandler 注册表
│  │  │  ├─ HTTP.ts              XHR 封装（账号服基地址硬编码在第 2 行）
│  │  │  ├─ GameNetMgr.ts        对局状态机 + 网络事件注册与派发（含封禁提示 errcode=4）
│  │  │  ├─ UserMgr.ts           登录 / 用户资料 / 进房（含封禁提示）
│  │  │  └─ components/          34 个场景组件（含 CreateRoom.ts 的"单人模式"开关）
│  │  ├─ prefabs/ anims/ resources/  预制体、动画、牌面与音频资源
│  │  └─ migration/              Creator 从 2.0.x 升级时自动生成的兼容助手
│  ├─ types/                     手写的共享类型声明（cc-vv / domain / cc-augment / globals）
│  ├─ tsconfig.json              Creator 与 tsc --noEmit 共用的编译配置
│  └─ project.json               工程信息（version: 2.4.15）
├─ server/                       Node.js 三进程服务端（TypeScript，编译到 dist/）
│  ├─ account_server/            账号服 :9000（含 dealer_api :12581）
│  ├─ hall_server/               大厅服 :9001 / :9002
│  ├─ game_server/               游戏服 :10000 / :9003
│  ├─ utils/                     db / http / crypto / startup / config / **bancheck**
│  ├─ types/                     共享类型（config / domain / protocol / db_rows / *.d.ts）
│  ├─ sql/db_babykylin.sql       建表与初始数据（玩家库权威 schema）
│  ├─ configs_mac.ts / configs_win.ts   唯一配置来源（函数式导出，两平台各一份）
│  ├─ start_all_mac.sh           macOS 一键启动 / 停止 / 状态 / 日志
│  └─ tests/                     2016 年的手工脚本（非自动化测试）
├─ server-python/                Python 3.14 三进程服务端 + 管理平台后端
│  ├─ shared/ utils/             共享契约 / 工具（db / crypto / startup / **bancheck**）
│  ├─ account_server/ hall_server/ game_server/   三进程（含 sio_server.py、robotmgr.py）
│  ├─ configs_mac.py / configs_win.py   唯一配置来源（必须同步修改）
│  ├─ manage.py / start_all_mac.sh      三进程一键启停
│  ├─ tests/                     离线测试（stdlib unittest，115 项）
│  ├─ docs/                      移植契约（gamemgr-port-contract.md）
│  └─ platform_server/           **管理平台后端**（Django 6.1 + DRF）
│     ├─ config/                 工程配置（settings 是唯一来源）
│     ├─ apps/                   common / accounts（含 /api/admins/）/ players（只读数据源 + 封禁 + 内部接口）
│     │                          / rooms（只读房间）/ games（只读归档 + decoding.py）
│     ├─ sql/db_scmj_admin.sql   建库脚本（**生成产物**，不要手改）
│     └─ scripts/                run.sh / gen_sql.py / check_sql_fresh.sh / e2e_login_check.sh
├─ admin-platform/               **管理平台前端**（Vue 3 + TS + Element Plus）
│  └─ src/                       api / stores / router / layouts / views / components / utils
├─ docs/                         上游资料（部署指南 PDF、代码讲解、版权声明）
├─ docs/ai-native/               给人看的参考文档（协议、玩法、迁移规范、结构图）
├─ .dsh/skills/                  5 个项目技能（按需加载）
├─ tools/                        零依赖验证门禁实现
├─ AGENTS.md                     AI 会话的根级工作契约
└─ package.json                  门禁入口（npm run verify）
```

> `client/library/`、`client/temp/`、`client/local/`、`client/build/`、`server/dist/`、
> `server/node_modules/`、`server/logs/`、`server/.run/`、`server-python/.venv/`、
> `server-python/platform_server/var/`、`admin-platform/dist/`、`admin-platform/node_modules/`
> 都是**工具产物，不要手改也不要提交**。

---

## 十、玩法与协议（上游核心 + 新增口径）

### 10.1 两份并行的玩法实现（改一份必须想另一份）

| 实现 | `conf.type` | Node 版 | Python 版 |
| --- | --- | --- | --- |
| 血流成河 | `"xlch"` | `server/game_server/gamemgr_xlch.ts` | `server-python/game_server/gamemgr_xlch.py` |
| 血战到底 | `"xzdd"`（非 `xlch` 一律走这份） | `gamemgr_xzdd.ts` | `gamemgr_xzdd.py` |

每套服务端内部，这两份文件约 **86% 的行逐行相同**，由 `roommgr` 的懒加载助手
`loadGameManager(type)` / `load_game_manager()` 按 `conf.type` 二选一。

> **硬约束**：改了其中一份而没改另一份，就是线上不一致。每次修改都要明确回答另一份是否同样适用；
> 只属于一种玩法的改动，要在提交说明里写清原因。
>
> **懒加载必须保持**：两个 `gamemgr` 末尾都有每秒跑一次的 `update`（`setInterval` / `asyncio` 任务），
> 顶层同时 `require` / `import` 会跑起两个定时器。

### 10.2 牌的编码

牌是 **0–26 的整数**，顺序 筒 → 条 → 万：`0–8` 筒（1筒–9筒）、`9–17` 条、`18–26` 万。

听牌 / 胡牌判定在 `mjutils`（纯算术、无 IO，因此可离线测试）。
**注意：七对（七小对）当前引擎不认**——`checkCanHu` 只枚举将牌再验证 3N（刻子 / 顺子），
没有"全偶数即胡"的分支。支持七对属于**新特性**，不是修 bug。

### 10.3 房间配置的两层结构

| 层 | 字段 |
| --- | --- |
| 入参 `roomConf`（客户端 `CreateRoom.ts` 提交） | `type`、`difen`、`zimo`、`jiangdui`、`huansanzhang`、`zuidafanshu`、`jushuxuanze`、`dianganghua`、`menqing`、`tiandihu`（单人模式另带 `single: 1`） |
| 落库 `conf`（`t_rooms.base_info`，对局逻辑只认这层） | `type`、`baseScore`、`zimo`、`jiangdui`、`hsz`、`dianganghua`、`menqing`、`tiandihu`、`maxFan`、`maxGames`、`creator` |

映射：`difen → DI_FEN[1,2,5]`、`zuidafanshu → MAX_FAN[3,4,5]`、`jushuxuanze → JU_SHU[4,8]`、
`huansanzhang → hsz`。`createRoom` 会校验入参非空，缺任何一项直接建房失败。

### 10.4 通信协议

- **客户端 → 服务端**：Socket.IO 事件在 `socket_service` 里以 `socket.on(...)` 注册
  （`login`、`ready`、`huanpai`、`dingque`、`chupai`、`peng`、`gang`、`hu`、`guo`、`chat`、
  `quick_chat`、`voice_msg`、`emoji`、`exit`、`dispress`、`dissolve_*`、`game_ping`…）。
- **服务端 → 客户端**：**39 个推送事件**，对局内统一走 `usermgr` 的
  `sendMsg/send_msg` / `broacastInRoom/broacast_in_room`（**拼写就是 `broacast`，不要"顺手修正"**）；
  只有登录 / 连接阶段的少数几处直接 `socket.emit` 是例外。
  客户端在 `GameNetMgr.ts` 用 `cc.vv.net.addHandler(event, fn)` 注册
  （门禁统计到 **44 个客户端处理器**），主流转是：服务端推送 → `Net.ts` → `GameNetMgr` `dispatchEvent` → 组件 `this.node.on`。
- **HTTP 接口**：账号服、大厅服、游戏服内部接口各自独立，客户端 `HTTP.ts` **全部用 GET**，参数走 query string；
  大厅服与游戏服统一用 `utils/http.ts` 的 `send(errcode, errmsg, data)` 返回。

> **事件名是客户端与服务端之间唯一的契约，中间没有任何工具链校验。**
> 新增或重命名任何事件名后，必须跑 `npm run check:protocol`（它会双向比对源码，并校验
> `docs/ai-native/protocol.md` §1 的事件表；Python 侧另由 `tests/test_protocol.py` 对齐，所以三边最终一致）。
> HTTP 路径的增删**不在门禁覆盖范围内**，需人工双向搜索调用方。

---

## 十一、验证门禁：`npm run verify`

这是本仓库唯一的"完成"判据，**零依赖**、无需 `npm install` 即可运行：

```bash
npm run verify                 # 七项全跑（提交前必须全绿）
npm run verify -- --verbose    # 打印每个被检查的文件 / 断言
npm run verify -- --json       # 机器可读结果
npm run verify:list            # 列出检查项
npm run verify -- --only=types # 单跑某一项（七项都可）

# 单项快捷方式
npm run check:syntax     npm run check:protocol    npm run check:smoke
npm run check:python     npm run check:harness     npm run test:tools
```

七项检查（顺序固定 `syntax` → `types` → `harness` → `protocol` → `smoke` → `python` → `selftest`）：

| 检查 | 回答的问题 | 当前结果 |
| --- | --- | --- |
| `syntax` | 一方脚本是否都能被解析（client 47 / server 34，共 81）：`.ts` 用 Node 内置 `module.stripTypeScriptTypes` 擦类型解析（**只解析不执行**，顺带强制只用可擦除语法），`.js` 用 `vm.Script`；并禁止 `server/` 与 `client/assets/scripts/` 残留一方 `.js` | ✅ 81 files parsed |
| `types` | ① 零依赖 **no-any 审计**：`: any` / `as any` / `<any>` / `@ts-ignore` / `@ts-expect-error` 一律失败；并在 `client/` 查残留 `cc.Class(` 与漏写的 `module.exports = <类名>;`（② 有 `server/node_modules/typescript` 时再跑两棵树的 `tsc --noEmit`（strict）） | ⚠️ no-any 通过（80 个 `.ts`），`tsc`：`server/` 通过、`client/` 有一个**既有**失败（`client/creator.d.ts` 第 20915 行缺一个逗号，Creator 自带声明文件，与业务代码无关） |
| `harness` | 指令文件（根 / `client` / `server` 三份 `AGENTS.md`）与 5 个项目技能是否可被发现、格式合法 | ✅ 3 files / 5 skills |
| `protocol` | Socket.IO 事件词汇表是否两端对齐 | ✅ 39 server events / 44 client handlers / 文档表三向一致 |
| `smoke` | 听牌 / 胡牌判定、花色分类、MD5 与 Base64（含中文昵称）、以及**封禁校验的签名向量**（游戏服 ↔ 管理平台之间唯一的运行时契约；**不含算番**） | ✅ 26/26 assertions |
| `python` | ① **无依赖**地 `ast.parse` 每一个一方 `.py`（只解析不执行——import `game_server.app` 会去绑端口）；② 有可用解释器（优先 `server-python/.venv/bin/python`）时跑 `tests/` 的 stdlib unittest，覆盖听牌判定、md5/Base64 向量、跨实现的协议事件名与签名参考向量、db 访问层导出面、以及两份 gamemgr 的**整局四人牌模拟** | ✅ 117 个 `.py` 解析通过；115 个离线测试通过 |
| `selftest` | 检查器自身的解析逻辑是否被改动破坏 | ✅ 24 passed |

缺依赖时**报 skipped 并说明原因，绝不装通过**：`types` 缺 `tsc` 时 ② 跳过、① 照跑；
`python` 缺解释器时 ② 跳过、① 照跑——与 `tsc` 同一套约定。

> **门禁不替你做运行时验证**：它不启动进程、不校验 SQL 执行结果、不算番值、不构建客户端、
> **不扫描 `server-python/platform_server/`**（那里的 `.py` 只被 `ast.parse`，Django 测试要自己跑）。
> 只有真实运行时才能确认的改动，交付说明必须写明"未运行时验证"并列出依赖的静态证据。
>
> **新增可离线验证的纯逻辑时，请顺手往 `tools/lib/smoke.mjs` 加断言**——宁可多一条断言，
> 也不要让"我改对了"停留在口头。

---

## 十二、代码风格约定（迁移红线）

本仓库经历过**行为不变**的迁移，因此源码风格刻意"老派"，**不要顺手现代化**：

1. **保留 `var` / `function` / 回调**：不要把 `var` 改成 `let` / `const`，不要把回调改成箭头函数
   （老代码里有 `for (var i…) { setTimeout(function(){ … i … }) }` 这类闭包，改了就变行为）。
   Python 版对应地保留与 Node 版一致的**逻辑顺序**。
2. **不引入 `any`**：优先精确类型 → `unknown` + 收窄 → 结构类型；跨动态边界用**一次带注释的断言**。
3. **只允许可擦除类型语法**：不许 `enum` / `namespace` / `import x = require()` / 构造函数参数属性
   （门禁的 `syntax` 检查会直接报红）。只导入类型时用 `import type`。
4. **注释一律用中文**，新增注释也沿用。
5. **客户端组件**一律 ES6 `class` + `@ccclass` / `@property`；`@ccclass` **不要传类名**；
   每个类文件末尾必须有 `module.exports = <类名>;`（Creator 的 `require("X")` 取的是 `module.exports`，
   漏了会在启动时抛 `X is not a constructor`）。
6. **不要手工编辑 `.meta` / `.fire`**，不要改 `client/assets/scripts/3rdparty/` 下的 vendored 库。
7. **SQL 只写在 `utils/db.ts` / `utils/db.py`**：它们是唯一访问层，业务代码不要自己 `require('mysql2')` /
   `import aiomysql` 或拼 SQL。管理平台侧的唯一读玩家库通道是 `apps/players/player_source.py`（只 SELECT）。
8. **改数据库结构**要同时改 `server/sql/db_babykylin.sql`、`db.ts` / `db.py` 的语句与类型契约
   （`server/types/db_rows.ts` / `server-python/shared/db_rows.py`）。
9. **改玩法逻辑**先读 `docs/ai-native/game-rules.md`，同一服务端的两份 `gamemgr_*` 同步改；
   涉及协议口径还要同步 `apps/games/decoding.py`。
10. **改服务端类型**后跑 `npm run verify -- --only=types`；**改事件名**后跑 `npm run check:protocol`；
    **改管理平台模型**后跑 `makemigrations` + `./scripts/check_sql_fresh.sh`。

逐条细则见 `docs/ai-native/typescript-migration.md`（Node 服务端）、
`docs/ai-native/client-typescript-migration.md`（客户端）与 `server-python/docs/gamemgr-port-contract.md`（Python 版玩法移植）。

---

## 十三、文档与 AI Native 工程

本仓库按 DeepSeek Harness 的约定组织项目知识，让任何 AI 会话进入仓库时不必重新摸索架构：

| 载体 | 位置 | 加载时机 |
| --- | --- | --- |
| 指令文件 | `AGENTS.md`、`client/AGENTS.md`、`server/AGENTS.md`、`server-python/AGENTS.md`、`server-python/platform_server/AGENTS.md` | 项目根到工作目录逐层叠加；访问某目录下的文件时该目录的指令文件也会被补加载 |
| 私有覆盖 | `AGENTS.local.md`（同目录） | 叠加在同目录 `AGENTS.md` 之上，**不提交** |
| 项目技能 | `.dsh/skills/<name>/SKILL.md` ×5 | 由 `description` 匹配任务后按需加载 |
| 人类文档 | `docs/ai-native/*.md`、各模块 `README.md` | 按需阅读 |

**参考文档**

| 文档 | 内容 |
| --- | --- |
| `docs/ai-native/README.md` | AI Native 开发工程导览 |
| `docs/ai-native/protocol.md` | Socket.IO 协议全景（39 推送 + 客户端事件 + HTTP 接口索引） |
| `docs/ai-native/game-rules.md` | 玩法规格：牌编码、听牌算法、动作常量、房间配置 |
| `docs/ai-native/client-map.md` | 客户端目录边界、脚本分层、组件职责、场景图 |
| `docs/ai-native/typescript-migration.md` | Node 服务端 TS 迁移规范与严格性取舍 |
| `docs/ai-native/client-typescript-migration.md` | 客户端 TS 迁移规范与 `@property` 逐项对应 |
| `docs/ai-native/skills-guide.md` | 技能加载规则与新增模板 |
| `server-python/AGENTS.md` | Python 版三进程的移植契约与有意差异清单 |
| `server-python/platform_server/README.md` | 管理平台后端的完整说明（数据来源、权限边界、接口、验证） |
| `server-python/platform_server/AGENTS.md` | 管理平台后端的隔离红线与五条易踩的坑 |
| `admin-platform/README.md` | 管理平台前端的目录、请求层、令牌续期与加页面方法 |

**项目技能**：`verify-gate`、`server-architecture`、`game-rules`、`client-integration`、`data-layer`。

---

## 十四、已知边界

| 项目 | 原因 / 现状 |
| --- | --- |
| 服务端运行时行为 | 门禁不启动进程；DB 相关路径（注册 / 登录 / 建房）需要真实 MySQL |
| SQL / 迁移的执行结果 | 门禁只做语法与类型检查；管理平台的 SQL 与迁移一致性靠 `check_sql_fresh.sh` |
| 客户端构建与运行 | Creator 2.4.15 依赖图形化编辑器，无法无头编译；`library/`、`temp/` 是本机产物 |
| HTTP 接口路径的增删 | 门禁只覆盖 Socket.IO 事件名，不覆盖 Express / aiohttp 路由与 Django 路由 |
| `.fire` / `.meta` / 美术资源 | 由编辑器维护，需人工在编辑器内验证 |
| 番型算分的业务正确性 | 只有听牌 / 胡牌判定有断言；具体番值需产品确认，无法凭代码自证 |
| 七对（七小对） | **当前引擎未实现**，冒烟断言把"不认七对"这一现状钉住 |
| Node 版 vs Python 版 | Python 版独有**单人模式**（Node 版对 `/create_single_room` 返回 404），其余功能对等 |
| 管理平台的运维动作 | 「强制解散房间」与「充值记录」目前是**预留入口**：后端恒返回 `reserved: true`，要做实需要**平台 → 游戏服**的内部接口 |
| 管理平台登录限流 / 审计 | **未做登录限流**（只有 PBKDF2 迭代成本）；管理员账号的增删改只有日志、**没有落库审计流水** |
| 封禁的时效 | **fail-open**：平台 / 网络故障期间被封玩家能临时进游戏；封禁最迟 30 秒生效，且不打断正在进行的对局 |
| JWT | 只能吊销 refresh，**已签发的 access 在过期前依然有效**（缓解手段是把有效期调短） |
| 玩家昵称搜索 | `t_users.name` 是 Base64 存的，模糊搜索按 Base64 片段匹配，跨字节边界的中间片段可能搜不到；按账号或玩家 ID 搜索永远准确 |
| 房间管理只看存活房间 | `t_rooms` 里没有历史房间（游戏服销毁房间时删掉整行）；要审计结束的对局请读归档表 |
| 房间"状态" | `playing` 的含义是"四个座位都有人"，不是"正在出牌"；`t_rooms` 里没有更细的状态字段 |

---

## 十五、开源协议与致谢

- 本项目基于 **[幼麟棋牌 · 四川麻将开源版](https://github.com/babykylin/babykylin_scmj)**
  （作者：**麒麟子 / 成都幼麟科技有限公司**）的最新代码升级而来。
  **感谢原作者的开源**——上游提供了完整可运行的玩法、客户端美术与 Node 服务端骨架，
  本仓库的所有新增（Python 服务端、管理平台、单人模式、封禁体系、验证门禁）都建立在这份基础之上。
  - 上游同步仓库：[GitHub](https://github.com/babykylin/babykylin_scmj) ·
    [Gitee](https://gitee.com/qilinzi/babykylin_scmj)
  - 上游技术文章：麒麟子博客 <https://qilinzi.blog.csdn.net/>
- 上游开源协议见：<https://github.com/babykylin/babykylin_scmj/wiki/开源协议>。
  使用、分发与二次开发请遵循上游协议；`docs/幼麟棋牌-四川麻将版权声明.docx` 亦为上游资料。
- 感谢开源社区提供的依赖：**Cocos Creator**、**Express**、**Socket.IO**、**MySQL / mysql2 / aiomysql**、
  **aiohttp**、**Django / Django REST framework / SimpleJWT**、**Vue 3 / Element Plus / Pinia / Vite**。
