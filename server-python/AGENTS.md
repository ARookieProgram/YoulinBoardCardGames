# AGENTS.md — 服务端（Python 三进程）

本文件在根级 `AGENTS.md` 之上叠加，**仅覆盖 `server-python/`**。
冲突时以本文件为准；与 `server/`（Node 版）相关的内容见 `repo:server/AGENTS.md`。

---

## 1. 这是什么

`server-python/` 是 `server/`（Node.js + TypeScript）的 **Python 3.14 重写版**：
同样的三个进程、同样的 6 个端口、同样的 HTTP 路由、同样的 md5 签名、
同样的 Socket.IO 事件名、同一套 MySQL schema。

**目标是与现有 Cocos 客户端和数据库完全兼容**：客户端一行都不用改，
两套服务端可以互换（但不要同时起，端口会撞）。

技术栈（对应 Node 侧的依赖）：

| Node | Python | 说明 |
| --- | --- | --- |
| `express` | `aiohttp` | HTTP 服务端与客户端 |
| `socket.io` 1.7 | **自研** `game_server/sio_server.py` | 见 §2 |
| `mysql2` | `aiomysql` | 异步驱动，支持 MySQL 8 的 `caching_sha2_password` |
| `node:crypto` | `hashlib` / `base64` | 标准库 |
| 回调 + `setTimeout` | `async`/`await` + `asyncio` | 见 §4 |

### 1.1 目录

```
server-python/
├─ manage.py                    ← 三进程管理（start/stop/status/restart/logs）
├─ start_all_mac.sh             ← manage.py 的薄壳，接口与 server/start_all_mac.sh 一致
├─ requirements.txt             ← 运行时依赖（4 个）
├─ configs_mac.py / configs_win.py  ← 唯一配置来源（函数式导出，两个平台各一份）
├─ shared/                      ← 跨进程共享的类型契约与域模型
│   ├─ config.py                （对应 types/config.ts）
│   ├─ domain.py                （对应 types/domain.ts，含 GameManagerProtocol）
│   ├─ protocol.py              （对应 types/protocol.ts，含 39 个推送事件名清单）
│   └─ db_rows.py               （对应 types/db_rows.ts）
├─ utils/                       ← crypto / config / db / http / startup / jscompat / bancheck
├─ account_server/              ← 账号服 :9000，含 dealer_api :12581
├─ hall_server/                 ← 大厅服 :9001（客户端）、:9002（游戏服上报）
├─ game_server/                 ← 游戏服 :10000（Socket.IO）、:9003（HTTP）
│   ├─ sio_server.py            ← Engine.IO 3 / Socket.IO 4 协议层（自研）
│   ├─ gamemgr_xlch.py          ← 血战到底
│   └─ gamemgr_xzdd.py          ← 另一种玩法
├─ tests/                       ← 离线测试（stdlib unittest，无第三方依赖）
└─ docs/                        ← 移植文档
```

**`shared/` 而不是 `types/`**：`types` 会遮蔽标准库的 `types` 模块
（`dataclasses` 等都会 `import types`），一旦 `server-python/` 出现在 `sys.path` 上就会炸。

### 1.2 安装与运行

```bash
cd server-python
python3 -m venv .venv                     # 需要 Python 3.14.x
.venv/bin/pip install -r requirements.txt

# 单个进程（前台调试）
.venv/bin/python -m game_server.app ../configs_mac.py
.venv/bin/python -m hall_server.app ../configs_mac.py
.venv/bin/python -m account_server.app ../configs_mac.py

# 一键起停（推荐）
./start_all_mac.sh                        # 启动 + 状态表
./start_all_mac.sh status                 # 只查状态；全部就绪退出码 0
./start_all_mac.sh stop
./start_all_mac.sh logs game
```

`configs_mac.py` / `configs_win.py` **必须同步修改**。相对路径按入口模块所在目录解析，
所以 `../configs_mac.py` 与 Node 版 `dist/<进程>/app.js ../configs_mac.js` 的相对语义一致。

## 2. 为什么自己实现 Socket.IO 协议层

客户端是 vendored 的 **socket.io-client 1.x**（Socket.IO 协议 4 / Engine.IO 协议 3）。
两条现成的路都走不通，所以 `game_server/sio_server.py` 自己实现了这一层：

* `python-socketio` 5.x / `python-engineio` 4.x **硬编码拒绝 EIO=3**
  （`engineio/server.py`：`if sid is None and query.get('EIO') != ['4']` 直接 400），
  客户端连握手都过不去；
* 支持 EIO3 的 `python-socketio` 4.6.1 / `python-engineio` 3.13.2 在 **Python 3.14 上跑不起来**：
  `asyncio.wait()` 从 3.12 起禁止传协程，而它正是用 `asyncio.wait([...coroutines])` 实现 `emit`
  —— 也就是**所有服务端推送**都会抛 `TypeError`；另外 `aiohttp` 3.14 下它的 polling 响应
  Content-Type 退化成 `application/octet-stream`，EIO3 的字符串载荷会被客户端当二进制解析。

实现范围只覆盖本仓库真正用到的特性：websocket + polling 两种传输、
open/close/ping/pong/message 五种 Engine.IO 包、connect/disconnect/event 三种 Socket.IO 包、
JSON 载荷（无二进制、无 namespace、无 ack）。两个容易踩的点写在模块文档里：

1. **EIO3 是客户端发 ping、服务端回 pong**（EIO4 反过来）；
2. **服务端才是 CONNECT 包的发起方**：socket.io 1.x 的客户端在默认 namespace 下
   **不发** `40`，它等收到服务端的 `40` 才触发 `connect`。顺序反了就是"客户端永远不 connect"。

改这一层之后，务必用 §5 的"真实客户端联调"再跑一遍。

## 3. 端口与进程

| 进程 | 模块入口 | 端口 |
| --- | --- | --- |
| 账号服 | `account_server.app` | 9000（客户端）、12581（代理 API） |
| 大厅服 | `hall_server.app` | 9001（客户端）、9002（游戏服上报） |
| 游戏服 | `game_server.app` | 10000（客户端 Socket.IO）、9003（HTTP） |

账号服是**一个进程两个 aiohttp 应用**；三者的绑定范围与原实现一致
（客户端端口绑全部网卡，内部端口绑配置里的 host）。

`utils/startup.py` 负责横幅：**端口真的绑定成功才打印"启动成功"**，
端口被占用时打印明确原因并以退出码 1 结束。横幅里 `进程     : PID <pid>` 这一行的格式
**不能改**——`manage.py` 与 shell 脚本靠 `": PID <数字>"` 核对进程身份。

## 4. 与 Node 版的有意差异

移植原则是**行为一致**，以下是刻意不同的地方，改代码前先读这一节。

### 4.1 并发模型：回调 → async/await

Node 版 `db.*` 是 `(args..., callback)`，gamemgr 是同步函数 + `setTimeout`。
Python 版：

* `utils/db.py` 的函数是 `async def`，**直接 `return` 结果**；
* `usermgr.send_msg` / `broacast_in_room` / `kick_all_in_room`、`roommgr.destroy` /
  `enter_room` / `exit_room`、`roommgr.create_room`（返回 `(errcode, roomId)`）都是协程；
* 两份 gamemgr 的对外接口全部是协程（见 `shared/domain.py` 的 `GameManagerProtocol`），
  内部把 `setTimeout(fn, ms)` 写成 `_schedule(ms, fn)`（`asyncio.create_task` + `sleep`）；
* socket 事件处理器注册的就是 `async def`。

**逻辑顺序与 Node 版一致**（该 await 的地方 await，不会打乱先后）。

### 4.2 错误不再杀死进程

Node 版在 db 回调 / socket 回调里 `throw err` 时，异常不在 express 的异常链上，
结果是**整个进程退出**。Python 版改为记录日志并把异常抛给协程调用方
（aiohttp 变成 500、socket 处理器被记下来），进程继续服务。
"这次操作失败了"这一点没变，变的是"不连带杀死整个服"。

### 4.3 历史 bug 一样保留

`server/` 里那些标着"历史 bug，移植不修"的地方，Python 版**同样保留**，
并在各自函数注释里标明原因。已知清单：

| 位置 | 行为 |
| --- | --- |
| `account_server.on_register` | 判断是反的：账号**已存在**才去创建 |
| `account_server.on_auth` | 调用从未定义的 `_get_md5`，必然抛 NameError |
| `db.get_account_info` | 口令**正确**时返回 `None` |
| `db.cost_gems` / `db.set_room_id_of_user` | 回调恒为 `False`（读了 UPDATE 结果上不存在的 `length`） |
| `db.update_user_history` | 回调恒为 `True`（同因） |
| `db.get_user_base_info` / `get_room_uuid` | 不判空行，行不存在时抛异常 |
| `tokenmgr.is_token_valid` | 读的是 `info.lifetime`（小写 t），恒为 `NaN` → **token 永不过期** |
| `roommgr.create_room` | 边界判断是 `> 长度` 而不是 `>= 长度`，索引可能越界 |
| `roommgr.is_creator` | `socket_service` 里有一处只传一个参数，因此恒返回 `False` |
| `game_server/http_service.on_is_room_runing` | 恒回 `runing:true`（判空那行被注释掉了） |
| `hall_server.check_account` | 签名校验本体被注释掉，只查参数存在 |
| `gamemgr.hu` | `game.lastFangGangSeat` 从未被写入，相关比较恒为 false |

要修其中任何一条，都是**单独一次改动**，并且两份 gamemgr（若涉及）与 Node 版要一起决定。

### 4.4 一处确实改掉的差异

`utils/http.request_ip()` 会把裸 IPv4 客户端地址补成 `::ffff:a.b.c.d`，
以对齐 Express 的 `req.ip`（Node 双栈监听的 `socket.remoteAddress` 就是这个形态）。
大厅服 `/login` 会剥掉这个前缀，客户端也因此拿到同样的结果。

另外 `utils/http.py` 在拼 URL 时会给 IPv6 主机加方括号。
Node 版的 `http.request({hostname, port, path})` 把主机与端口分开传，天然没有这个问题；
Python 侧是拼 URL，`http://::1:19003/...` 是非法 URL（游戏服向大厅服注册时对端可能就是 `::1`，
这条路一定会走到）。

### 4.5 `game_over_push` 的键集：跟着 Node 的"有没有赋值"，不是跟着默认值

`JSON.stringify` 会**丢掉值为 `undefined` 的键**，而 `GameSeat` 上一部分结算字段只在特定分支里
才被赋值（`qingyise` / `menqing` / `jingouhu` / `zhongzhang` / `haidihu` / `tianhu` / `dihu` /
`numofgen`），`begin()` 里**没有**初始化它们。`GameState`/`GameSeat` 用 dataclass 表达，
默认值是 `False`/`0`，直接照抄字面量会把这些键**多发出去**。

所以两份 gamemgr 的 `do_game_over` 里，这些键按"原实现是否会写入"逐个决定加不加，
而不是一次性写进字面量：

```python
user_rt = { ... 稳定存在的键 ... }
if sd.qingyise:                 # 只在为真时赋值
    user_rt["qingyise"] = True
if game.conf.menqing:           # 房间开门清时才赋值，值可能是 False
    user_rt["menqing"] = sd.isMenQing
```

**唯一一处近似**：xzdd 的 `zhongzhang`（原实现的条件是"房间开门清 **且** 不是将对"，
而"是不是将对"在 `do_game_over` 里已经拿不到），这里用真值判断，
即"赋过值且为 False"时键会消失。客户端对这几个字段**一律只做真值判断**
（`if(userData.zhongzhang)`，见 `client/assets/scripts/components/GameOver.ts`），
所以不产生可观察差异。要完全一致就得把"是否赋过值"单独记下来，那是一次独立的改动。

### 4.6 单人模式（人机）是 Python 版独有的功能

`game_server/robotmgr.py`、`roommgr._seat_robots`、大厅服的 `/create_single_room` 目前
**只有 `server-python/` 有**，Node 版 `server/` 没有对应实现。这不是移植遗漏，而是这一版
先只做了 Python 侧：

- 客户端（`client/assets/scripts/components/CreateRoom.ts`）已经接好"单人模式"开关；
  对 Node 版大厅服点它会拿到 404，此时两套服务端在这一点上**不对等**。
- 机器人是"没有 socket 的座位"：`usermgr.is_online` 对 `robotmgr` 登记过的 userId 恒返回
  True（`set_ready` 的"四人齐"判断要用），推送则因查不到连接被丢弃。
- gamemgr 侧的钩子只有四处：`send_operations`（覆盖出牌与碰杠胡的响应）、`begin`（开局换牌/定缺）、
  `huan_san_zhang`（换牌结束转定缺）、`peng`（碰完出牌）。两份 gamemgr 都要改。
- **解散房间要替机器人投票**：解散是"四家投票、全票才生效、否则 30 秒超时"，机器人不会发
  `dissolve_agree`。`socket_service.on_dissolve_request` 在广播 `dissolve_notice_push` 之后调用
  `robotmgr.auto_agree_dissolve(room_info)` 把机器人座位置为已同意；四票齐了就立刻
  `do_dissolve`，不等超时。这份逻辑在 `socket_service` 里（不在 gamemgr），
  所以两份 gamemgr 都不需要为此改动；真人的 `dissolve_reject` 撤销分支保持原样。
- `do_game_over` 里机器人保持"已准备"，否则第一局之后 `set_ready` 永远差三家、开不了第二局。
- `conf.single` **不落库**（`utils/db._conf_to_wire` 的键集与 Node 版一致），所以进程重启后
  从库里还原的单人房会丢掉这个标记——单人房本来就是新建即打完的，这一点不影响正常流程。

要补 Node 版，按 `robotmgr.py` 的策略与上面四个钩子点逐个照搬即可；
补完请同步删掉 README §7.5 与本文这一节的"仅 Python"说明。

## 4.7 封禁校验：向管理平台问一句（与 Node 版成对）

大厅服的 `/login`、`/create_private_room`、`/enter_private_room`（含仅 Python 有的
`/create_single_room`）与游戏服的 socket `login` 都会先调一次管理平台
（`platform_server`，默认 127.0.0.1:8000）的内部只读接口：

    GET /api/internal/players/ban-check/?account=..&sign=md5("account"+account+"player_id"+player_id+PRI_KEY)

实现是 `utils/bancheck.py`，与 `server/utils/bancheck.ts` **行为与签名必须逐字一致**；
平台侧是 `apps/players/internal.py`。三条运行语义（改代码前先读模块文档）：

* **fail-open**：超时 / 连不上 / 平台返回非 0 → 放行 + 警告日志（管理后台挂掉不该让
  全体玩家登不上游戏）；
* **缓存**：成功结果按 `CACHE_TTL_MS`（默认 30 秒）缓存，失败后有 5 秒冷却；
* **密钥**：`ban_check()["PRI_KEY"]` 必须等于平台的 `PLATFORM_INTERNAL_KEY`，
  不一致表现为"封禁静默失效"（只有警告日志）。

签名参考向量钉在 `tests/test_protocol.py::SignatureTest`（Node 侧同一条向量在
`tools/lib/smoke.mjs`），行为钉在 `tests/test_bancheck.py`。

## 5. 改完怎么验证

### 5.1 离线测试（零依赖，必跑）

```bash
cd server-python
.venv/bin/python -m unittest discover -s tests -t .      # 全部
.venv/bin/python -m unittest tests.test_protocol -v      # 只跑协议/签名一致性
```

`tests/test_protocol.py` 是最有价值的一项，它跨实现比对：

* Python 服务端真正推送的事件名集合 == `docs/ai-native/protocol.md` §1 的表格 ==
  Node 服务端源码里的事件名集合；
* 进房签名与四个内部接口签名的 md5 结果，比对**由 Node 实现算出来的常量参考向量**
  （自己跟自己比是没有意义的）；
* 两份 gamemgr 导出的函数名、规则常量一致。

`tests/test_mjutils.py` 的用例与仓库根门禁 `tools/lib/smoke.mjs` **逐条对应**，
两侧同时跑绿才说明听牌判定行为一致。

### 5.2 真实客户端联调（改了 `sio_server.py` / 客户端协议相关代码必跑）

协议层无法靠单元测试证明"客户端能连上"。用仓库里 vendored 的真实客户端做端到端：

```python
# 把 vendored 的 socket.io 客户端加载进 Node
global.CC_JSB = false; global.cc = { sys: { isNative: false } };
global.window = global; global.self = global;
const io = require('<repo>/client/assets/scripts/3rdparty/socket-io.js');
const sock = io.connect('http://127.0.0.1:10000', {
  reconnection: false, 'force new connection': true, transports: ['websocket'] });
sock.on('connect', () => sock.emit('login', JSON.stringify({token, roomid, time, sign})));
sock.on('login_result', d => console.log(d));
```

要点：`client/assets/scripts/3rdparty/socket-io.js` 是 UMD，在 Node 里
只要先定义 `CC_JSB` / `cc` / `window` / `self` 就能 `require` 出 `io`。
**这是唯一能证明"客户端真的能连上"的手段**，改了 `sio_server.py` 就必须跑。

### 5.3 起三个进程看一遍

```bash
cd server-python && ./start_all_mac.sh
./start_all_mac.sh status     # 6 个端口全部 [监听中]
./start_all_mac.sh stop
```

进程启动时横幅会显示数据库自检结果；连不上 MySQL 时会明确写"不可用 — <原因>"，
进程仍然启动（`/guest` 等接口不依赖数据库）。

### 5.4 仓库根门禁

```bash
npm run verify            # 七项检查（含 python 那一项）
npm run check:python      # 只跑 Python 的语法 + 离线测试
npm run check:protocol    # 事件名双向比对（Node 侧与 client 侧）
```

`npm run verify` 里的 `syntax` / `types` 两项**不扫描 `server-python/`**
（它们是按 `.ts` 与 `client/` 写的），所以门禁里专门加了一项 **`python`**
（`tools/lib/python.mjs`）：

* **无依赖**地 `ast.parse` 每一个一方 `.py`——只解析不执行，
  因为 import `game_server.app` 会去绑端口；这一半永远会跑；
* 有可用解释器时（优先 `.venv/bin/python`）再跑本目录 `tests/` 里的 stdlib unittest；
  缺依赖时报 **skipped 并说明原因**，绝不装作通过——与 `types` 缺 `tsc` 时同一套约定。
  当前 115 项（含 `tests/test_bancheck.py` 的封禁校验、`test_protocol.py` 的签名向量，
  以及 `tests/test_db_layer.py` 的访问层导出面与两个战绩回放查询）。

所以提交前的完整判据是 `npm run verify` **全绿**（当前 `types` 有一处**既有**失败：
`client/creator.d.ts` 第 20915 行缺一个逗号，与本目录无关）。

## 6. 数据访问层

`utils/db.py` 是**唯一**允许拼 SQL 的地方（与 Node 版同一条约定）。
业务代码只调用它的导出，不要自己 `import aiomysql` 或拼 SQL。
行结构契约在 `shared/db_rows.py`。

**`__all__` 里的每个名字都必须真的有实现**：调用方（大厅服 / 游戏服）只按名字 `await`，
少一个函数就是在运行时抛 `AttributeError`（aiohttp 变成 500），静态检查与 `ast.parse` 都拦不住。
`tests/test_db_layer.py` 用一条通用断言钉住这件事——它的第一个实例就是
`get_games_of_room` / `get_detail_of_game`（客户端"战绩 → 回放"的两个查询）：
这两个函数在移植时只写进了 `__all__`、没写实现，导致 Python 版大厅服的
`/get_games_of_room` 与 `/get_detail_of_game` 一直 500（Node 版正常），后来补上了。
**新增/重命名 db 函数时，两个查询的 SQL 口径要与 Node 版一致**，
并在同一个测试文件里补上对应的断言。

表结构变更要同时改 `repo:server/sql/db_babykylin.sql`、`utils/db.py` 的语句与 `shared/db_rows.py`。

## 7. 玩法规则：两份并行实现

`game_server/gamemgr_xlch.py` 与 `gamemgr_xzdd.py` 与 Node 版一样是**两个独立文件**，
约 86% 逐行相同。`roommgr.load_game_manager()` 按 `conf.type` 懒加载其中一份：

```python
module = "game_server.gamemgr_xlch" if type_ == "xlch" else "game_server.gamemgr_xzdd"
return importlib.import_module(module)
```

**必须保持懒加载**：两个模块在 import 时都会起一个每秒跑一次的 `_update()` 任务
（对应 Node 版末尾的 `setInterval(update,1000)`），同时 import 会跑起两个定时器。

**改了其中一份而没改另一份，就是线上不一致。** 每次修改都要明确回答：另一份是否同样适用？
只属于一种玩法的，在提交说明里写清原因。

移植这两份实现时遵守的保真规则（JS 的 `for...in` 键序、`splice` 的负下标、
`undefined` 与 `null` 在线上的区别、`setTimeout` 的对应写法…）
集中在 `repo:server-python/docs/gamemgr-port-contract.md`，改动前请先读一遍。

## 8. 推送事件

对局内的推送**统一**走 `game_server/usermgr.py`：
`send_msg` / `broacast_in_room`（拼写就是 `broacast`）/ `kick_all_in_room`。
只有登录/连接阶段的 8 处直接 `socket.emit` 是例外
（`login_result`×5、`login_finished`、`exit_result`、`game_pong`）。

新增或重命名事件名之后必须跑 `npm run check:protocol`
（它比对 Node 服务端与客户端两侧的词汇表），并同步
`shared/protocol.py` 的清单与 `repo:docs/ai-native/protocol.md`。
`server-python/tests/test_protocol.py` 会把 Python 侧的推送集合与上面两处对齐，
所以**三边最终都会一致**。

`send_msg(uid, event)`（不带载荷）与 `send_msg(uid, event, None)` 在线上是**不同的包**
（`42["event"]` vs `42["event",null]`，客户端分别拿到 `undefined` 与 `null`）。
`sio_server.NO_DATA` 就是用来区分这两者的默认值，不要图省事统一成 `None`。

## 9. 不要提交

`.venv/`、`__pycache__/`、`logs/`、`.run/`、`nohup.out`（见 `server-python/.gitignore`）。
