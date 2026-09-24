---
name: server-architecture
description: The Node.js server trio in this project - account/hall/game processes, ports, the login handshake, HTTP routes, how the game manager is selected, and how to add or rename a Socket.IO push event safely. Use when changing server-side code, adding an API route, or adding a push event.
---

# 服务端架构与协议

三个独立的 Node 进程共享一个 MySQL 库。**判断一个改动该落在哪个进程**，是这里最常见的错误来源。

## 什么时候用

- 改服务端任意文件。
- 新增 HTTP 接口或 Socket.IO 推送。
- 排查"客户端收不到 / 大厅服调不通游戏服"。

## 1. 三进程与端口

| 进程 | 入口 | 端口 | 对谁服务 | 传输 |
| --- | --- | --- | --- | --- |
| 账号服 | `repo:server/account_server/app.ts` | 9000 / 12581 | 客户端、渠道代理 | Express HTTP |
| 大厅服 | `repo:server/hall_server/app.ts` | 9001 / 9002 | 客户端、游戏服 | Express HTTP |
| 游戏服 | `repo:server/game_server/app.ts` | 10000 / 9003 | 客户端、大厅服 | Socket.IO + Express HTTP |

- **服务端源码是 TypeScript（`strict: true`）**，由 `tsc` 编译到 `server/dist/` 后运行，
  跑起来的是编译产物。起之前先 `cd server && yarn install --frozen-lockfile && yarn build`，
  入口比迁移前多一个 `dist/` 前缀：`node dist/game_server/app.js ../configs_mac.js`
  （`yarn account` / `yarn hall` / `yarn game` 也已经是 dist 入口）。
  配置相对路径语义没变：`require` 相对入口模块目录解析，所以 `../configs_mac.js` 指向
  `dist/configs_mac.js`（`configs_mac.ts` 的编译产物）。
- 全部配置来自 `repo:server/configs_mac.ts` 或 `repo:server/configs_win.ts`，
  由 `process.argv[2]` 传给 `utils/config.ts` 的 `loadConfigs()`。
  配置是**函数式导出**（`export function game_server(){...}`），两平台各一份，**必须同步改**。
  老 `configs_mac.js` 首行的 BOM（`\ufeff`）在迁移后已经没有了：`configs_mac.ts` / `configs_win.ts`
  是不带 BOM 的 UTF-8，别再按"别弄丢 BOM"的老经验去处理。

进程内的文件分工：

| 文件 | 角色 |
| --- | --- |
| `repo:server/game_server/socket_service.ts` | **对局协议唯一入口**，所有 `socket.on(...)` 都在这里 |
| `repo:server/game_server/http_service.ts` | 给大厅服调用的内部接口，**四个接口都校验 `sign`** |
| `repo:server/game_server/roommgr.ts` | 房间内存表 + 按 `conf.type` 选择玩法实现 |
| `repo:server/game_server/usermgr.ts` | `userId → socket` 映射与推送助手 |
| `repo:server/game_server/tokenmgr.ts` | 房间登录 token 的生成与有效期校验 |
| `repo:server/hall_server/client_service.ts` | 面向客户端的 HTTP 接口 |
| `repo:server/hall_server/room_service.ts` | 向游戏服发起 HTTP 调用、维护房间登记 |
| `repo:server/account_server/account_server.ts` | 账号注册/登录（`/image` 用 `http.getRaw` 代理图片） |
| `repo:server/account_server/dealer_api.ts` | 渠道/代理查询接口 |
| `repo:server/utils/db.ts` | **唯一** SQL 访问层（驱动是 `mysql2`） |
| `repo:server/utils/http.ts` | 统一 JSON 响应出口 `send()`，另有 `get` / `get2` / `getRaw` |
| `repo:server/utils/startup.ts` | 启动横幅：所有端口 listening 后才报"启动成功"，含数据库自检 |
| `repo:server/utils/crypto.ts` | `md5` / `toBase64` / `fromBase64` |
| `repo:server/utils/config.ts` | `loadConfigs(process.argv[2], __dirname)`：三个入口用它读配置文件 |
| `repo:server/types/` | 跨模块共享的**类型模块**（纯类型，编译后是空模块）：`config.ts` / `domain.ts` / `protocol.ts` / `db_rows.ts` / `globals.d.ts` / `socket.io.d.ts` |

类型与运行时约定见 `repo:docs/ai-native/typescript-migration.md`（迁移规范：目录、构建、可擦除语法、取舍）。

## 2. 登录与进房链路

改签名或房间流程前，必须整条链路一起看：

```
1. 客户端 → 账号服  GET /guest                                 换取签名与大厅地址
2. 客户端            cc.vv.http.url = "http://" + cc.vv.SI.hall   （UserMgr.ts）
3. 客户端 → 大厅服  GET /login?account=&sign=                  取得用户资料
4. 客户端 → 大厅服  GET /enter_private_room?...                返回 {ip, port, token, roomid, time, sign}
5. 客户端 → 游戏服  连接 ip:port，emit('login', {token, roomid, time, sign})
6. 游戏服           校验 md5(roomid + token + time + ROOM_PRI_KEY) == sign，再校验 token 时效
7. 大厅服 / 游戏服  → 管理平台 GET /api/internal/players/ban-check/（封禁校验；fail-open，见下）
```

第 4 步与第 6 步是同一套签名的两侧：拼接顺序、密钥、字段名任意一处不一致，就是**全员登录失败**。
`tokenmgr.ts` 负责 token 生成，`socket_service.ts` 负责校验。

进房的 socket 事件处理器会在登录成功后执行：
`userMgr.bind(userId, socket)` 登记连接、取房间与座位、`socket.gameMgr = roomInfo.gameMgr`，
之后所有业务动作都走 `socket.gameMgr.xxx(...)`。

## 3. 玩法实现的选择

`repo:server/game_server/roommgr.ts` 按 `conf.type` 二选一。注意两处**调用点**的变量不同名：
新建房间读入参 `roomConf.type`（`roommgr.ts:216`），从数据库恢复房间读已落库的 `conf.type`
（`roommgr.ts:83`）。两处都走同一个懒加载助手 `loadGameManager(type)`（`roommgr.ts:61`）：

```ts
function loadGameManager(type: string): GameManager {
	// 动态 require 的模块路径无法静态解析，所以这里是一次断言。
	return require(type == "xlch" ? "./gamemgr_xlch" : "./gamemgr_xzdd") as GameManager;
}
```

**必须保持懒加载**：两个 gamemgr 文件末尾都有 `setInterval(update,1000)`，顶层同时 require
会跑起两个定时器。两份实现约 **86%** 的行逐行相同（`gamemgr_xlch.ts` / `gamemgr_xzdd.ts`），
**改玩法必须考虑两份**。细节见 `repo:.dsh/skills/game-rules/SKILL.md`。

## 4. 推送事件：唯一的正确写法

游戏服的推送**只能**经过 `repo:server/game_server/usermgr.ts`：

| 函数 | 语义 |
| --- | --- |
| `sendMsg(userId, event, data)` | 发给单个玩家；不在线则静默丢弃 |
| `broacastInRoom(event, data, sender, includingSender)` | 广播给同房间座位（**拼写就是 `broacast`**，不要"顺手修正"） |
| `kickAllInRoom(roomId)` | 踢出房间内所有连接 |

登录/连接阶段（此时还没有房间可广播）有 8 处**直接 `socket.emit`** 的例外：
`login_result`(×5)、`login_finished`、`exit_result`、`game_pong`。除此之外不要再写裸 `emit`——
理由是可读性（读者一眼看出"发给房间"还是"发给个人"），
**不是因为门禁扫不到**：`check:protocol` 同时识别裸 `emit(`，两种写法都能扫到。

### 新增一个推送事件的完整清单

1. 服务端：用 `userMgr.sendMsg` 或 `userMgr.broacastInRoom` 推送，事件名用小写蛇形 + `_push`
   后缀（沿用现有命名，如 `game_begin_push`、`user_ready_push`）。
2. 客户端：在 `repo:client/assets/scripts/GameNetMgr.ts` 里
   `cc.vv.net.addHandler("<event>", function(data){ ... self.dispatchEvent("<event>", data); })`；
   再在需要的组件里 `this.node.on("<event>", fn)`。
3. 跑 `npm run check:protocol`，它必须报绿。
4. 在 `repo:docs/ai-native/protocol.md` 的事件表里补一行。

**重命名事件是不可逆的破坏性操作**：必须两侧同时改，并确认没有历史回放依赖它。

## 5. HTTP 接口约定

- 新接口沿用 `repo:server/utils/http.ts` 的 `send(res, errcode, errmsg, data)` 统一出口。
  **但账号服是例外**：`account_server.ts` 与 `dealer_api.ts` 各自定义了本地
  `send(res, ret)` 并直接 `res.send`，返回结构也更随意。改账号服时按它本地写法来。
- 游戏服的内部接口（给大厅服调用）用 `sign` 校验，签名逻辑与登录链路同源。

## 6. 约束与验证

- **服务端已经能在本机启动**（`fibers` 已移除、驱动换成 `mysql2`，见 `repo:server/AGENTS.md` §1.1），
  所以"起一次看看"是有效手段：先 `yarn build` 产出 `dist/`，每个进程会打印启动横幅，
  所有端口真正 listening 才显示"启动成功"，端口被占用会明确报错并以退出码 1 结束。
  只有 DB 路径（注册/登录/建房）需要真实 MySQL。
- 起停三个进程优先用 `repo:server/start_all_mac.sh`（跑的是 `dist/` 产物，缺 `dist/` 会提示先 `yarn build`）：
  `./start_all_mac.sh`（一键起 + 状态表）、`stop`、`restart`、`status`、`logs <名字>`。
  它从配置文件读端口、把 PID 记在 `.run/pids`、日志分进程写 `logs/<名字>.log`，
  状态表会标出端口是 `[监听中]` / `[未监听]` / `[被占用]`（被别人占着时会拒绝启动并报 PID）。
  细节见 `repo:server/AGENTS.md` §1.2。
- `repo:server/tests/` 下是 2016 年的手工脚本（已随迁移改成 `.ts`），会连库、只打印不断言，
  **不是测试套件**。
- 不要提交 `nohup.out`、`logs/`、`.run/`、数据库转储。

```bash
npm run verify             # 六项全跑（含 types 与 selftest）
npm run check:protocol     # 动了任何事件名必跑
npm run check:smoke        # 动了 crypto / mjutils 必跑
```

需要真实运行时才能确认的改动，在提交说明里写"未运行时验证"并列出依赖的静态证据。
