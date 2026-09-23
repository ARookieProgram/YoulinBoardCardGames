# AGENTS.md — 幼麟四川麻将（babykylin_scmj）

本文件是 DeepSeek Harness 在本仓库的**根级工作契约**。任何 AI 会话进入本仓库都会自动加载它；
`client/AGENTS.md`、`server/AGENTS.md` 会在你操作对应目录时叠加加载。

> 面向人类的完整导览见 `repo:docs/ai-native/README.md`。

---

## 1. 这是什么

一套可运行的开源四川麻将（血战到底 / 血战到底·换三张）完整实现，由两部分组成：

| 部分 | 技术栈 | 说明 |
| --- | --- | --- |
| `repo:client/` | Cocos Creator **2.4.15**（`cocos2d-html5`） | 客户端。`assets/scripts/` 下是手写的 ES5 风格 JS；`.fire` 场景由 Creator 编辑器产出 |
| `repo:server/` | Node.js + Express + Socket.IO + MySQL（`mysql` 驱动） | 服务端。三个独立进程：账号服 / 大厅服 / 游戏服 |

**代码风格是 2016 年的 ES5 + CommonJS**：`var`、`function`、回调，没有构建步骤、没有 TypeScript、
没有转译器。请沿用现有风格，不要引入 `const`/`let`/箭头函数/`async` 混搭，也不要为客户端引入打包器。

**代码注释一律用中文**——这是本仓库的既有约定，新增注释请沿用。

---

## 2. 系统架构

```
client (Cocos Creator)
   │
   │  HTTP  ──────────────►  账号服 account_server   :9000   注册 / 登录 / 游客
   │  HTTP  ──────────────►  账号服 dealer_api       :12581  渠道/代理侧查询（同进程，见下）
   │  HTTP  ──────────────►  大厅服 hall_server      :9001   登录 / 建房 / 查询战绩
   │  Socket.IO ──────────►  游戏服 game_server      :10000  对局内全部实时协议
   │  HTTP  ──────────────►  游戏服 http_service     :9003   大厅服内部调用（建房/进房），需签名
   │
   └────────────►  MySQL  db_scmj（`repo:server/sql/db_babykylin.sql`）
```

「账号服」是一个进程两个 HTTP 服务：`account_server.js`（:9000）与 `dealer_api.js`（:12581），
由 `repo:server/account_server/app.js` 同时拉起。

三个进程都通过命令行参数接收配置文件：`node app.js ../configs_mac.js`。
配置是**函数式导出**（`exports.account_server = function(){...}`），因此新增配置项要同时改
`repo:server/configs_mac.js` 与 `repo:server/configs_win.js`。

### 端口与进程

| 进程 | 入口 | 端口 |
| --- | --- | --- |
| 账号服 | `repo:server/account_server/app.js` | 9000（客户端）、12581（代理 API） |
| 大厅服 | `repo:server/hall_server/app.js` | 9001（客户端）、9002（游戏服上报） |
| 游戏服 | `repo:server/game_server/app.js` | 10000（客户端 Socket.IO）、9003（HTTP） |

---

## 3. 改动前必读的三条硬约束

### 3.1 玩法规则有两份并行实现，必须同步修改

`repo:server/game_server/gamemgr_xlch.js`（血战到底，2289 行）与
`repo:server/game_server/gamemgr_xzdd.js`（另一种玩法，2298 行）是**两个独立文件**，
约 86% 的行逐行相同。房间按 `conf.type` 二选一，注意两处选择点的变量不同名：

```js
// roommgr.js:147  新建房间，读入参
if(roomConf.type == "xlch"){ roomInfo.gameMgr = require("./gamemgr_xlch"); }
// roommgr.js:34   从数据库恢复房间，读已落库的 conf
if(roomInfo.conf.type == "xlch"){ roomInfo.gameMgr = require("./gamemgr_xlch"); }
```

**改了其中一份而没改另一份，就是线上不一致。** 每次修改都要明确回答：另一份是否同样适用？
如果确实只属于一种玩法，在提交说明里写清楚原因。

### 3.2 Socket.IO 事件名是客户端与服务端之间唯一的契约

服务端推送事件名与客户端 `cc.vv.net.addHandler('<event>', fn)` 注册名必须逐字一致，中间没有任何
工具链校验。`npm run check:protocol` 会双向比对这两份词汇表；**新增或重命名任何事件名后必须跑它**。

协议全景见 `repo:docs/ai-native/protocol.md`。

### 3.3 服务端在当代 Node 上无法直接启动

- `repo:server/utils/http.js` 与 `repo:server/account_server/account_server.js` 依赖原生模块
  `fibers`，仓库内预编译产物与当前 Node/OS 不匹配，`require` 即抛错。
- `repo:server/utils/db.js` 需要真实 MySQL 实例。

因此在当前环境里**不要试图用 `node app.js` 验证改动**。可验证的部分已经沉淀为 `npm run verify`；
需要真实运行时请在提交说明中写明"未运行时验证"并说明理由。

---

## 4. 验证门禁：`npm run verify`

这是本仓库唯一的"完成"判据。依赖为零，无需 `npm install`。

```bash
npm run verify                 # 跑全部五项检查（提交前必须全绿）
npm run verify -- --verbose    # 打印每个被检查的文件 / 断言
npm run verify -- --json       # 机器可读结果
npm run verify:list            # 列出检查项名称
npm run check:syntax           # 只跑语法
npm run check:protocol         # 只跑协议一致性
npm run check:smoke            # 只跑行为冒烟
npm run check:harness          # 只校验本工程自身（AGENTS.md 与 skills）
npm run test:tools             # 校验检查器自身
```

五项检查分别回答：

| 检查 | 回答的问题 |
| --- | --- |
| `syntax` | 74 个一方 `.js` 是否都能被解析（`vm.Script` 编译，不执行） |
| `harness` | 本文档与 `.dsh/skills/` 是否能被 Harness 真正发现、格式是否合法 |
| `protocol` | Socket.IO 事件词汇表是否两端对齐 |
| `smoke` | 听牌/胡牌判定、花色分类、MD5 与 Base64（**不含算番**，番值无离线判据） |
| `selftest` | 检查器自身的解析逻辑是否被改动破坏 |

**新增可离线验证的纯逻辑时，请顺手往 `repo:tools/lib/smoke.mjs` 加断言。**
宁可多一条断言，也不要让"我改对了"停留在口头。

---

## 5. 具体做法

- **改玩法逻辑**：先读 `repo:docs/ai-native/game-rules.md`；两份 `gamemgr_*` 同步；跑 `npm run verify`。
- **加协议事件**：服务端用 `userMgr.sendMsg` / `userMgr.broacastInRoom`，客户端用
  `cc.vv.net.addHandler`，两侧同名；跑 `npm run check:protocol`。
- **改数据库**：SQL 权威定义在 `repo:server/sql/db_babykylin.sql`；`repo:server/utils/db.js` 是唯一
  访问层，不要在业务代码里直接拼 SQL。
- **改客户端组件**：`repo:docs/ai-native/client-map.md` 有组件职责表；`assets/**/*.meta` 由 Creator
  维护，不要手工编辑。

---

## 6. 本仓库的 Harness 契约

本工程按 DeepSeek Harness 的约定组织项目知识，遵守以下规则即可被自动加载：

| 载体 | 位置 | 加载时机 |
| --- | --- | --- |
| 指令文件 | 本文件、`repo:client/AGENTS.md`、`repo:server/AGENTS.md` | 项目根到工作目录逐层叠加；**另外，访问某目录下的文件时，该目录的指令文件也会被补加载** |
| 私有覆盖 | `AGENTS.local.md`（同目录） | 叠加在同一目录的 `AGENTS.md` 之上，**不提交**（已 gitignore） |
| 项目技能 | `repo:.dsh/skills/<name>/SKILL.md` | 由 `description` 匹配任务后按需加载 |

- 项目根由 `.git` 标记，因此**必须**在 `repo:.dsh/skills/`（而非子目录）下放技能。
- `SKILL.md` 的 YAML frontmatter 必须含非空的 `name` 与 `description`；**`name` 必须等于目录名**，
  否则 Harness 会静默忽略该技能。
- 技能正文里用反引号包裹、以 `repo:` 开头的路径会被 `npm run check:harness` 校验存在性。

可用的项目技能与新增技能的方法见 `repo:docs/ai-native/skills-guide.md`。

---

## 7. 交付习惯

- 提交信息用中文或英文均可，但要说清**改了哪个进程/哪份玩法实现**。
- 改动要小而自洽；不要把"顺手重构"混进功能改动。
- 任何"暂时绕过"都要留下注释说明原因与适用边界。
- 环境相关的临时文件（`nohup.out`、日志）不要提交。
