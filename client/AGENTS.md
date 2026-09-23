# AGENTS.md — 客户端（Cocos Creator 2.4.15）

本文件在根级 `AGENTS.md` 之上叠加，仅覆盖客户端相关内容。冲突时以本文件为准。

---

## 1. 工程形态

- **Cocos Creator 2.4.15**，`repo:client/project.json` 里 `"engine": "cocos2d-html5"`。
- 源码只有一处：`repo:client/assets/`。其余目录都是**工具产物，不要手改**：

| 目录 | 性质 |
| --- | --- |
| `repo:client/library/` | Creator 导入资源的缓存（UUID → 文件） |
| `repo:client/temp/` | Creator 的临时编译产物（含 `quick-scripts/`） |
| `repo:client/local/` | 本机编辑器设置（已在 `.gitignore`） |
| `repo:client/build/` | 构建输出（已在 `.gitignore`） |

- `repo:client/creator.d.ts` 是引擎类型声明，供编辑器补全用；**它不是文档，改代码前不要依赖它推断 API**。
- `repo:client/assets/scripts/3rdparty/socket-io.js` 是 vendored 的 socket.io 客户端。
  `syntax` 与 `protocol` 两项检查都会跳过它，**不要修改它**。

## 2. 代码风格

与仓库整体一致：ES5 + `cc.Class`，`var` + `function`，分号风格沿用文件内既有写法。
新增节点不要引入 `class`、箭头函数、`let/const` 或打包器——2.4.15 的构建链不会替你转译。

`repo:client/jsconfig.json` 只服务于编辑器提示，不是项目配置。

---

## 3. 运行时骨架：`cc.vv` 单例

`AppStart` 启动时把各个管理器挂到全局 `cc.vv` 上，业务组件通过它互相访问。理解这层是读客户端代码的前提：

| 单例 | 文件 | 职责 |
| --- | --- | --- |
| `cc.vv.net` | `repo:client/assets/scripts/Net.js` | Socket.IO 连接、心跳、事件注册（`addHandler`）与分发 |
| `cc.vv.http` | `repo:client/assets/scripts/HTTP.js` | XMLHttpRequest 封装；**基地址硬编码在文件第 2 行** |
| `cc.vv.gameNetMgr` | `repo:client/assets/scripts/GameNetMgr.js` | 对局状态机：座位、手牌、轮次、定缺、换三张、结算 |
| `cc.vv.userMgr` | `repo:client/assets/scripts/UserMgr.js` | 登录/注册、用户资料、当前房间 |
| `cc.vv.mahjongmgr` | `repo:client/assets/scripts/MahjongMgr.js` | 牌面图集（SpriteAtlas）与牌的显示。**注意全小写**，源码里就是 `cc.vv.mahjongmgr` |
| `cc.vv.replayMgr` | `repo:client/assets/scripts/ReplayMgr.js` | 回放模式 |
| `cc.vv.voiceMgr` / `cc.vv.audioMgr` | `VoiceMgr.js` / `AudioMgr.js` | 语音消息与音效 |
| `cc.vv.global` | `repo:client/assets/scripts/Global.js` | 少量全局状态（昵称、金币、房间号等） |

要点：

- `cc.vv.net.addHandler(event, fn)` **同名事件只注册一次**，重复注册会被忽略并打印日志——
  如果你的事件像没生效，先确认是不是被别处提前注册了。
- `cc.vv.gameNetMgr` 收到网络事件后会 `dispatchEvent(event, data)`，场景组件再用
  `this.node.on(event, fn)` 订阅。所以同一个事件名会出现两次：一次注册、一次派发。
- **游戏服的地址不是写死的**：`cc.vv.net.ip` 由 `GameNetMgr.js` 在登录流程里从服务端下发的
  `data.ip + ":" + data.port` 赋值。只有账号服的地址（`HTTP.js`）是硬编码 `http://127.0.0.1:9000`，
  部署到真机时必须改。

---

## 4. 组件职责（`assets/scripts/components/`，共 34 个）

| 分组 | 组件 | 说明 |
| --- | --- | --- |
| 启动/登录 | `AppStart.js` | 入口；初始化各管理器、决定首个场景 |
| | `LoadingLogic.js` | 加载页 → `login` |
| | `Login.js`、`CreateRole.js` | 账号登录、创建角色 |
| | `WaitingConnection.js`、`ReConnect.js` | 断线等待与重连 |
| 大厅 | `Hall.js` | 大厅主界面、建房入口 |
| | `CreateRoom.js`、`JoinGameInput.js` | 创建房间（玩法/局数/番数等选项）、输入房号 |
| | `History.js`、`MJRoom.js` | 战绩列表、房间详情 |
| | `Settings.js`、`Status.js`、`NoticeTip.js`、`Alert.js`、`PopupMgr.js` | 设置、状态栏、提示与弹窗管理 |
| 对局 | `MJGame.js` | **对局主控**，约 900 行，绝大多数交互都在这里 |
| | `Seat.js` | 单个座位（手牌/弃牌/碰杠的渲染与点击） |
| | `Folds.js` | 牌河 |
| | `DingQue.js`、`HuanSanZhang.js` | 定缺、换三张 |
| | `PengGangs.js` | 碰/杠/胡/过的操作按钮 |
| | `TimePointer.js` | 出牌倒计时指针 |
| | `GameOver.js`、`GameResult.js` | 单局结束与总结算 |
| | `Chat.js`、`Voice.js` | 文字/快捷/表情/语音聊天 |
| | `ReplayCtrl.js` | 回放控制 |
| 通用控件 | `RadioButton.js`、`RadioGroupMgr.js`、`CheckBox.js`、`ImageLoader.js`、`OnBack.js`、`UserInfoShow.js` | 复用 UI 控件 |

## 5. 场景与流程

场景文件在 `repo:client/assets/scenes/`（`.fire` 由 Creator 生成）。

```
start → loading → login → createrole ─┐
                            ↓         │
                          hall ◄──────┘
                            │
                            ▼
                         mjgame ──(结束/退出)──► hall
```

`cc.director.loadScene("<name>")` 的调用点（全仓库仅这些，共 15 处）：
`GameNetMgr.js`(187,223)、`UserMgr.js`(55,69)、`Hall.js`(196)、`GameResult.js`(89)、
`ReConnect.js`(34)、`LoadingLogic.js`(40)、`ReplayCtrl.js`(42)、`AppStart.js`(152,158)、
`Login.js`(51)、`History.js`(194)、`MJRoom.js`(197)、`Settings.js`(97)。
**`MJGame.js` 里没有 `loadScene`**——它只处理对局内交互。
**改流程前先在这些文件里确认现有跳转，不要只看场景名字。**

玩法分支：`conf.type` 为 `"xlch"` 或 `"xzdd"`，`MJGame.js`、`GameOver.js`、`GameNetMgr.js`
里有多处按它选择 UI 与逻辑。注意 `GameOver.js:35` **只有一个**结算面板节点 `game_over_xlch`，
按 `conf.type` 走不同分支，**不存在 `game_over_xzdd` 节点**，不要去找或新建它。

---

## 6. 你一定要遵守的约束

1. **不要手工编辑 `.meta` 文件，也不要手写 `.fire`。**
   二者的 UUID 与序列化结构由 Creator 生成；手改会导致资源引用断裂或场景打不开。
   已经出现在工作区的 `.meta` 改动是编辑器重新导入产生的，不是代码变更。
2. **不要改 `assets/scripts/3rdparty/` 下的 vendored 库。**
3. 新增场景组件后，资源导入与场景绑定必须在 Creator 编辑器里完成，并在提交说明里注明
   "需在编辑器中重新导入"。
4. 新增网络事件时，事件名必须与服务端逐字一致，并跑 `npm run check:protocol`。

---

## 7. 改完怎么验证

**客户端无法在本仓库内被无头编译**：Creator 2.4.15 的构建依赖图形化编辑器，且
`library/`、`temp/` 中的产物是按本机路径生成的。所以可用手段是：

```bash
# 必须：语法（80 个一方 .js/.ts 中包含客户端全部 47 个一方脚本）
npm run check:syntax

# 必须：若改了任何网络事件名或新增事件
npm run check:protocol
```

其余的运行时验证需要人工在 Creator 编辑器里跑，请在提交说明中写明：
改动了哪些组件、需要在编辑器中做哪些操作、以及**哪些路径你没能验证**。
不要把"看起来对"说成"已验证"。
