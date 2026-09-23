# 客户端结构图

Cocos Creator **2.4.15** 客户端。本文是一份"去哪儿找什么"的索引；
具体改动流程与禁区见 `repo:.dsh/skills/client-integration/SKILL.md`。

---

## 1. 目录边界

| 路径 | 性质 | 可否手改 |
| --- | --- | --- |
| `repo:client/assets/` | **唯一源码区** | ✅ |
| `repo:client/assets/scripts/3rdparty/` | vendored socket.io | ❌ |
| `repo:client/assets/**/*.meta` | Creator 生成的资源元数据 | ❌ |
| `repo:client/assets/**/*.fire` | Creator 场景文件 | ❌（用编辑器改） |
| `repo:client/library/` | 导入缓存 | ❌ |
| `repo:client/temp/` | 临时编译产物 | ❌ |
| `repo:client/local/`、`repo:client/build/` | 本机设置 / 构建输出（已 gitignore） | ❌ |
| `repo:client/creator.d.ts` | 引擎类型声明（445KB） | ❌（不是文档） |

---

## 2. 脚本分层

```
assets/scripts/
├─ Net.ts            网络层：socket.io 连接、心跳、addHandler 注册表
├─ HTTP.ts           XHR 封装；基地址硬编码在文件第 2 行
├─ GameNetMgr.ts     对局状态机 + 绝大多数网络事件的注册与派发（674 行）
├─ UserMgr.ts        登录/注册、用户资料、进房流程
├─ MahjongMgr.ts     牌面图集与显示
├─ ReplayMgr.ts      回放
├─ VoiceMgr.ts       语音消息
├─ AudioMgr.ts       音效
├─ Utils.ts          通用工具
├─ Global.ts         少量全局状态
├─ BGScaler.ts       背景适配
├─ AnysdkMgr.ts      第三方 SDK 接入
└─ components/       34 个场景组件（见 §4）
```

### `cc.vv` 单例

`AppStart` 在启动时把管理器挂到全局 `cc.vv`。业务组件一律通过它互访，**不要直接相互持有引用**。

| 单例 | 来源 |
| --- | --- |
| `cc.vv.net` | `Net.ts` |
| `cc.vv.http` | `HTTP.ts` |
| `cc.vv.gameNetMgr` | `GameNetMgr.ts` |
| `cc.vv.userMgr` | `UserMgr.ts` |
| `cc.vv.mahjongmgr` | `MahjongMgr.ts` |
| `cc.vv.replayMgr` | `ReplayMgr.ts` |
| `cc.vv.voiceMgr` / `cc.vv.audioMgr` | `VoiceMgr.ts` / `AudioMgr.ts` |
| `cc.vv.global` | `Global.ts` |

> **服务器地址有两个来源，别搞混**：账号服基地址硬编码在 `repo:client/assets/scripts/HTTP.ts`
> 第 2 行（`http://127.0.0.1:9000`）；游戏服地址由服务端下发，
> 在 `GameNetMgr.connectGameServer` 里赋给 `cc.vv.net.ip`。

---

## 3. 网络事件的流转

```
服务端推送
  → Net.ts 的包装函数（非 disconnect 的字符串自动 JSON.parse）
  → GameNetMgr.ts: cc.vv.net.addHandler(event, fn) → self.dispatchEvent(event, data)
  → 场景组件: this.node.on(event, fn)
```

- `addHandler` 同名只注册一次，重复注册会被忽略并打日志。
- 断线重连后**不需要重新注册**：`Net.ts` 会把 `handlers` 里的处理器重放到新 socket。
- `game_ping` / `game_pong` 心跳由 `Net.ts` 自己处理，不走 `addHandler`。

事件清单见 `repo:docs/ai-native/protocol.md`。

---

## 4. 组件职责（34 个）

| 分组 | 组件 | 职责 |
| --- | --- | --- |
| 启动/登录 | `AppStart.ts` | 入口；初始化单例、决定首个场景 |
| | `LoadingLogic.ts` | 加载页 → `login` |
| | `Login.ts` | 账号登录；含 `push_need_create_role` 处理器 |
| | `CreateRole.ts` | 创建角色 |
| | `WaitingConnection.ts` / `ReConnect.ts` | 断线等待与重连 |
| 大厅 | `Hall.ts` | 大厅主界面 |
| | `CreateRoom.ts` | 建房选项（玩法/局数/番数/底分…） |
| | `JoinGameInput.ts` | 输入房号进房 |
| | `History.ts` / `MJRoom.ts` | 战绩列表 / 房间详情与回放入口 |
| | `Settings.ts` / `Status.ts` | 设置 / 状态栏 |
| | `Alert.ts` / `NoticeTip.ts` / `PopupMgr.ts` | 弹窗、提示、弹窗栈管理 |
| 对局 | `MJGame.ts` | **对局主控**（886 行）：布局、交互、按 `conf.type` 切换表现 |
| | `Seat.ts` | 单个座位：手牌、弃牌、碰杠的渲染与点击 |
| | `Folds.ts` | 牌河 |
| | `DingQue.ts` | 定缺 |
| | `HuanSanZhang.ts` | 换三张 |
| | `PengGangs.ts` | 碰/杠/胡/过 操作区 |
| | `TimePointer.ts` | 出牌倒计时指针 |
| | `GameOver.ts` | 单局结束面板（**只有** `game_over_xlch` 一个节点，按 `conf.type` 走不同分支） |
| | `GameResult.ts` | 总结算 |
| | `Chat.ts` / `Voice.ts` | 文字/快捷/表情/语音 |
| | `ReplayCtrl.ts` | 回放控制条 |
| 通用控件 | `RadioButton.ts` / `RadioGroupMgr.ts` | 单选与分组 |
| | `CheckBox.ts` | 复选 |
| | `ImageLoader.ts` | 远程头像加载 |
| | `OnBack.ts` | 返回键处理 |
| | `UserInfoShow.ts` | 用户信息卡 |

---

## 5. 场景

`repo:client/assets/scenes/`：`start`、`loading`、`login`、`createrole`、`hall`、`mjgame`。

```
start → loading → login → createrole ─┐
                          ↓           │
                        hall ◄────────┘
                          ↓
                       mjgame ──(结束/退出)──► hall
```

`cc.director.loadScene` 的调用点（共 15 处，全量）：`GameNetMgr.ts`(187,223)、`UserMgr.ts`(55,69)、
`Hall.ts`(196)、`GameResult.ts`(89)、`ReConnect.ts`(34)、`LoadingLogic.ts`(40)、`ReplayCtrl.ts`(42)、
`AppStart.ts`(152,158)、`Login.ts`(51)、`History.ts`(194)、`MJRoom.ts`(197)、`Settings.ts`(97)。
**`MJGame.ts` 里没有 `loadScene`。** 改流程前先在 `client/assets/scripts` 全目录搜一遍现有跳转。

---

## 6. 资源

`repo:client/assets/` 下的美术与音频：

| 路径 | 内容 |
| --- | --- |
| `anims/` | 表情/动作动画（`.anim`） |
| `prefabs/` | 预制体 |
| `scenes/` | 场景 |
| `resources/textures/` | 牌面、头像、UI 图集 |
| `resources/sounds/` | 音效与语音 |
| `resources/ver/` | 版本相关资源 |

新增资源必须在 Creator 编辑器里导入（生成 `.meta`），并按 §1 的边界处理这些产物。

---

## 7. 客户端可用的验证手段

```bash
npm run check:syntax     # 客户端全部一方脚本的语法
npm run check:protocol   # 改了事件名时必跑
```

除此之外**必须在 Creator 编辑器里人工验证**——本仓库无法无头编译客户端。
交付说明要写明改了哪些组件、需要在编辑器中执行哪些操作、以及哪些路径未验证。
