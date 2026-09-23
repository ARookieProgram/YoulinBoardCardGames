---
name: client-integration
description: How to add or change client-side behaviour in the Cocos Creator client and wire it to the server - cc.vv singletons, addHandler/dispatchEvent flow, scene changes, and the .meta/.fire rules. Use when editing client components, adding a network event handler, or changing game UI flow.
---

# 客户端集成

Cocos Creator **2.4.15** 客户端。改客户端的难点不在写 UI，而在**正确接进现有的网络与单例骨架**，
并且守住"哪些文件不能手改"的边界。

## 什么时候用

- 新增/修改 `repo:client/assets/scripts/components/` 下的组件。
- 新增一个服务端推送事件在客户端的处理。
- 改场景跳转或登录/重连流程。

## 1. 一条推送的完整旅程

新增事件时，必须在这条链路的每一段都动手，缺一段就是"事件收不到"：

```
服务端 userMgr.sendMsg / broacastInRoom(event, data)
   ↓  Socket.IO
Net.js            cc.vv.net.handlers[event] 的包装函数（自动 JSON.parse 字符串）
   ↓
GameNetMgr.js     cc.vv.net.addHandler(event, function(data){ ... self.dispatchEvent(event, data); })
   ↓
场景组件          this.node.on(event, function(data){ ... })      ← 改 UI 的地方
```

要点：

- `cc.vv.net.addHandler(event, fn)` 的包装层会对**非 `disconnect` 的字符串 data 自动
  `JSON.parse`**，所以处理器里拿到的一般已经是对象。重复注册同名事件会被忽略并打印日志。
- **`addHandler` 只注册一次**。注册时机通常在 `GameNetMgr.onLoad` 或组件 `onLoad`，
  而 `Net.js` 会把已注册的 handler 重放到新 socket 上（`for(var key in this.handlers)`），
  所以断线重连后不需要重新注册。
- 组件用 `this.node.on(event, fn)` 订阅 `GameNetMgr` 派发的事件。
  **同一个事件名在代码里出现两次是正常的**：一次 `addHandler`（注册），一次 `dispatchEvent`（派发）。
- 心跳：`Net.js` 定时 `send("game_ping")`，服务端回 `game_pong`，`Net.js` 直接 `sio.on('game_pong')`
  处理并计算延迟。这条路径**不走** `addHandler`，`protocol` 检查已覆盖。

改完后必须跑：

```bash
npm run check:protocol   # 事件名两端一致
npm run check:syntax     # 客户端脚本能解析
```

## 2. 常用入口

| 需求 | 位置 |
| --- | --- |
| 发一个 socket 消息 | `cc.vv.net.send(event, data)` |
| 发一个 HTTP 请求 | `cc.vv.http.sendRequest(path, data, callback)`（基地址在 `HTTP.js` 第 2 行，登录后切到大厅） |
| 对局状态读写 | `cc.vv.gameNetMgr`（`seats`、`turn`、`dingque`、`gamestate`…） |
| 弹窗/提示 | `Alert.js`、`NoticeTip.js`、`PopupMgr.js` |
| 座位表现 | `Seat.js`（手牌/弃牌/碰杠渲染）、`Folds.js`（牌河） |
| 倒计时 | `TimePointer.js` |
| 音效/语音 | `cc.vv.audioMgr`、`cc.vv.voiceMgr` |

玩法分支：`cc.vv.gameNetMgr.conf.type` 为 `"xlch"` 或 `"xzdd"`。
`MJGame.js`、`GameOver.js`、`GameNetMgr.js` 里有多处按它切换 UI 与逻辑，
新增玩法分支时必须同时考虑两种取值。

## 3. 场景跳转

`cc.director.loadScene(name)` 的调用点共 15 处：
`GameNetMgr.js`(187,223)、`UserMgr.js`(55,69)、`Hall.js`(196)、`GameResult.js`(89)、
`ReConnect.js`(34)、`LoadingLogic.js`(40)、`ReplayCtrl.js`(42)、`AppStart.js`(152,158)、
`Login.js`(51)、`History.js`(194)、`MJRoom.js`(197)、`Settings.js`(97)。
**`MJGame.js` 里没有 `loadScene`**，别在那里找。

主流程：

```
start → loading → login → createrole ─┐
                          ↓           │
                        hall ◄────────┘
                          ↓
                       mjgame ──(结束/退出)──► hall
```

新增跳转前先在这些文件里搜现有跳转，避免出现两个互相打断的 `loadScene`。

## 4. 绝对不能做的事

1. **不要手改 `.meta` 文件。** 每个资源旁的 `*.meta` 由 Creator 生成，保存 UUID 与导入设置。
   手改会让资源引用断裂。工作区里已有的 `.meta` 改动是编辑器重新导入产生的，不是代码变更——
   **提交时不要把无关的 `.meta` 改动一起带上**。
2. **不要手写 `.fire`。** 场景是序列化 JSON，结构由 Creator 维护。用编辑器改。
3. **不要改 `repo:client/assets/scripts/3rdparty/socket-io.js`。** 它是 vendored 库，
   `syntax` 与 `protocol` 检查都刻意跳过它。
4. **不要引入 `class` / 箭头函数 / `let` / `const` / 打包器。** 2.4.15 的构建链不转译，
   引擎与运行时都不保证支持。沿用 `cc.Class` + `var` + `function`。
5. **不要相信 `repo:client/creator.d.ts` 是文档。** 它是编辑器补全用的类型声明，
   体积 445KB，与真实引擎行为可能有出入；要确认 API 请查引擎源码或既有用法。

## 5. 运行时验证的边界

客户端**无法在本仓库内无头编译**：构建依赖图形化编辑器，`library/`、`temp/` 的产物也是按本机
路径生成的（不要提交它们，也不要把它们当作可复现证据）。

所以你能给出的客观证据只有 `npm run check:syntax` 与 `npm run check:protocol`。
其余必须在 Creator 编辑器里人工验证。交付说明里要写清：

- 改了哪些组件；
- 需要在编辑器里做什么操作（例如"重新导入 `assets/prefabs` 并重挂脚本"）；
- **哪些路径没有被验证**。

不要把"读起来对"表述成"已验证"。
