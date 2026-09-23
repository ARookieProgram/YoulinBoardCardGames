# AGENTS.md — 客户端（Cocos Creator 2.4.15）

本文件在根级 `AGENTS.md` 之上叠加，仅覆盖客户端相关内容。冲突时以本文件为准。

---

## 1. 工程形态

- **Cocos Creator 2.4.15**，`repo:client/project.json` 里 `"engine": "cocos2d-html5"`。
- 源码有两处：`repo:client/assets/`（脚本与场景）与 `repo:client/types/`（手写的共享类型声明）。
  其余目录都是**工具产物，不要手改**：

| 目录 | 性质 |
| --- | --- |
| `repo:client/library/` | Creator 导入资源的缓存（UUID → 文件） |
| `repo:client/temp/` | Creator 的临时编译产物（含 `quick-scripts/`） |
| `repo:client/local/` | 本机编辑器设置（已在 `.gitignore`） |
| `repo:client/build/` | 构建输出（已在 `.gitignore`） |

- `repo:client/tsconfig.json` 只服务 `tsc --noEmit` 与编辑器补全，**不是** Creator 的项目配置。
- `repo:client/types/` 是**手写的共享类型声明**（`cc.vv` 单例、域模型、引擎补丁），属于源码。

- `repo:client/creator.d.ts` 是引擎类型声明，供编辑器补全用；**它不是文档，改代码前不要依赖它推断 API**。
- `repo:client/assets/scripts/3rdparty/socket-io.js` 是 vendored 的 socket.io 客户端。
  `syntax` 与 `protocol` 两项检查都会跳过它，**不要修改它**。

## 2. 代码风格

与仓库整体一致：ES5 + `cc.Class`，`var` + `function`，分号风格沿用文件内既有写法；
但**源码是 TypeScript**（`assets/scripts/` 下一方脚本全是 `.ts`）。新增节点不要引入 `class`、
`@ccclass`、箭头函数、`let/const` 或打包器——2.4.15 的构建链不会替你转译，
`.ts` 由 Creator 自己编译，而且只允许**可擦除的类型标注**（不许 `enum` / `namespace` /
`import x = require()` / 构造函数参数属性）。

- 共享类型在 `repo:client/types/`：`cc-vv.d.ts` 是 `cc.vv` 上全部单例的接口，`domain.d.ts` 是
  网络推送载荷与对局域模型，`cc-class.d.ts` 给 `cc.Class` 的 `this` 补类型。
- `.js` 改成 `.ts` 时**必须把同名 `.meta` 一起改名并保留 `uuid`**——场景 `.fire` 靠 uuid 引用脚本组件。
- 逐条迁移规矩见 `repo:docs/ai-native/client-typescript-migration.md`。

`repo:client/jsconfig.json` 只服务于编辑器提示，不是项目配置。

---

## 3. 运行时骨架：`cc.vv` 单例

`AppStart` 启动时把各个管理器挂到全局 `cc.vv` 上，业务组件通过它互相访问。理解这层是读客户端代码的前提：

| 单例 | 文件 | 职责 |
| --- | --- | --- |
| `cc.vv.net` | `repo:client/assets/scripts/Net.ts` | Socket.IO 连接、心跳、事件注册（`addHandler`）与分发 |
| `cc.vv.http` | `repo:client/assets/scripts/HTTP.ts` | XMLHttpRequest 封装；**基地址硬编码在文件第 2 行** |
| `cc.vv.gameNetMgr` | `repo:client/assets/scripts/GameNetMgr.ts` | 对局状态机：座位、手牌、轮次、定缺、换三张、结算 |
| `cc.vv.userMgr` | `repo:client/assets/scripts/UserMgr.ts` | 登录/注册、用户资料、当前房间 |
| `cc.vv.mahjongmgr` | `repo:client/assets/scripts/MahjongMgr.ts` | 牌面图集（SpriteAtlas）与牌的显示。**注意全小写**，源码里就是 `cc.vv.mahjongmgr` |
| `cc.vv.replayMgr` | `repo:client/assets/scripts/ReplayMgr.ts` | 回放模式 |
| `cc.vv.voiceMgr` / `cc.vv.audioMgr` | `VoiceMgr.ts` / `AudioMgr.ts` | 语音消息与音效 |
| `cc.vv.global` | `repo:client/assets/scripts/Global.ts` | 少量全局状态（昵称、金币、房间号等） |

要点：

- `cc.vv.net.addHandler(event, fn)` **同名事件只注册一次**，重复注册会被忽略并打印日志——
  如果你的事件像没生效，先确认是不是被别处提前注册了。
- `cc.vv.gameNetMgr` 收到网络事件后会 `dispatchEvent(event, data)`，场景组件再用
  `this.node.on(event, fn)` 订阅。所以同一个事件名会出现两次：一次注册、一次派发。
- **游戏服的地址不是写死的**：`cc.vv.net.ip` 由 `GameNetMgr.ts` 在登录流程里从服务端下发的
  `data.ip + ":" + data.port` 赋值。只有账号服的地址（`HTTP.ts`）是硬编码 `http://127.0.0.1:9000`，
  部署到真机时必须改。

---

## 4. 组件职责（`assets/scripts/components/`，共 34 个）

| 分组 | 组件 | 说明 |
| --- | --- | --- |
| 启动/登录 | `AppStart.ts` | 入口；初始化各管理器、决定首个场景 |
| | `LoadingLogic.ts` | 加载页 → `login` |
| | `Login.ts`、`CreateRole.ts` | 账号登录、创建角色 |
| | `WaitingConnection.ts`、`ReConnect.ts` | 断线等待与重连 |
| 大厅 | `Hall.ts` | 大厅主界面、建房入口 |
| | `CreateRoom.ts`、`JoinGameInput.ts` | 创建房间（玩法/局数/番数等选项）、输入房号 |
| | `History.ts`、`MJRoom.ts` | 战绩列表、房间详情 |
| | `Settings.ts`、`Status.ts`、`NoticeTip.ts`、`Alert.ts`、`PopupMgr.ts` | 设置、状态栏、提示与弹窗管理 |
| 对局 | `MJGame.ts` | **对局主控**，约 900 行，绝大多数交互都在这里 |
| | `Seat.ts` | 单个座位（手牌/弃牌/碰杠的渲染与点击） |
| | `Folds.ts` | 牌河 |
| | `DingQue.ts`、`HuanSanZhang.ts` | 定缺、换三张 |
| | `PengGangs.ts` | 碰/杠/胡/过的操作按钮 |
| | `TimePointer.ts` | 出牌倒计时指针 |
| | `GameOver.ts`、`GameResult.ts` | 单局结束与总结算 |
| | `Chat.ts`、`Voice.ts` | 文字/快捷/表情/语音聊天 |
| | `ReplayCtrl.ts` | 回放控制 |
| 通用控件 | `RadioButton.ts`、`RadioGroupMgr.ts`、`CheckBox.ts`、`ImageLoader.ts`、`OnBack.ts`、`UserInfoShow.ts` | 复用 UI 控件 |

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

`cc.director.loadScene("<name>")` 的调用点（全仓库仅这些，共 15 处，行号按迁移后的 `.ts` 重新核对）：
`GameNetMgr.ts`(192,228)、`UserMgr.ts`(59,73)、`AppStart.ts`(172,178)、`Hall.ts`(234)、
`GameResult.ts`(103)、`ReConnect.ts`(35)、`LoadingLogic.ts`(41)、`ReplayCtrl.ts`(42)、
`Login.ts`(54)、`History.ts`(215)、`MJRoom.ts`(224)、`Settings.ts`(97)。
（`ReConnect.ts:28` 那处是注释掉的旧代码，不算调用点。）
**`MJGame.ts` 里没有 `loadScene`**——它只处理对局内交互。
**改流程前先在这些文件里确认现有跳转，不要只看场景名字。**

玩法分支：`conf.type` 为 `"xlch"` 或 `"xzdd"`，`MJGame.ts`、`GameOver.ts`、`GameNetMgr.ts`
里有多处按它选择 UI 与逻辑。注意 `GameOver.ts:78` **只有一个**结算面板节点 `game_over_xlch`，
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
# 必须：语法（80 个一方脚本中包含 client 的 47 个：46 个一方脚本 + Creator 生成的 assets/migration 助手；并检查有没有残留的一方 .js）
npm run check:syntax

# 必须：类型（strict，用 server/node_modules/typescript，客户端不额外引依赖）
server/node_modules/.bin/tsc --noEmit -p client/tsconfig.json

# 必须：若改了任何网络事件名或新增事件
npm run check:protocol

# 全绿才算改完
npm run verify
```

`.ts` 改名或新增后必须回 Creator 编辑器里重新导入（`library/`、`temp/` 是工具产物，不要提交）。

其余的运行时验证需要人工在 Creator 编辑器里跑，请在提交说明中写明：
改动了哪些组件、需要在编辑器中做哪些操作、以及**哪些路径你没能验证**。
不要把"看起来对"说成"已验证"。
