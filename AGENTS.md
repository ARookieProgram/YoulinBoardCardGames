# AGENTS.md — 幼麟四川麻将（babykylin_scmj）

本文件是 DeepSeek Harness 在本仓库的**根级工作契约**。任何 AI 会话进入本仓库都会自动加载它；
`client/AGENTS.md`、`server/AGENTS.md` 会在你操作对应目录时叠加加载。

> 面向人类的完整导览见 `repo:docs/ai-native/README.md`。

---

## 1. 这是什么

一套可运行的开源四川麻将（血战到底 / 血战到底·换三张）完整实现，由两部分组成：

| 部分 | 技术栈 | 说明 |
| --- | --- | --- |
| `repo:client/` | Cocos Creator **2.4.15**（`cocos2d-html5`） | 客户端。`assets/scripts/` 下是手写的 ES5 风格 **TypeScript**（`cc.Class` / `var` / `function`，由 Creator 自己编译）；`.fire` 场景由 Creator 编辑器产出 |
| `repo:server/` | Node.js + **TypeScript（`strict: true`，`tsc` 编译到 `server/dist/`）** + Express + Socket.IO + MySQL（`mysql2` 驱动） | 服务端。源码是 `.ts`，跑的是编译产物；三个独立进程：账号服 / 大厅服 / 游戏服 |

**客户端源码也是 TypeScript，但写法刻意保持 2016 年的 ES5 + CommonJS**：`var`、`function`、
回调、`cc.Class`，没有构建步骤、没有打包器，`.ts` 由 Creator 2.4.15 自己编译。
只允许**可擦除的类型标注**，不要引入 `class` / `@ccclass` / `let` / `const` / 箭头函数 / `async`，
也不要为客户端引入打包器。逐条规矩（`cc.Class` 的 `this` 怎么来、网络边界怎么断言、`.meta` 怎么改名）
见 `repo:docs/ai-native/client-typescript-migration.md`。

**服务端已经迁移到 TypeScript，但风格刻意没变**：`server/` 下一方源码全是 `.ts`
（`server/tests/*.ts` 也是），`strict: true`，用 `tsc` 编译到 `server/dist/` 后再运行。
这次是**行为不变的纯类型迁移**，所以服务端里同样保留 `var` / `function` / 回调写法——
**不要把 `var` 改成 `let`/`const`，也不要把回调改成箭头函数**；模块语法换成 `import` / `export`，
由 `tsc --module CommonJS` 编译回 `require`。逐条规矩（可擦除语法、不许 `any`、动态边界怎么断言）
见 `repo:docs/ai-native/typescript-migration.md` §2。

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

「账号服」是一个进程两个 HTTP 服务：`account_server.ts`（:9000）与 `dealer_api.ts`（:12581），
由 `repo:server/account_server/app.ts` 同时拉起。

三个进程都通过命令行参数接收配置文件：`node dist/game_server/app.js ../configs_mac.js`
（跑之前先 `cd server && yarn install --frozen-lockfile && yarn build`，入口是 **编译产物**）。
配置是**函数式导出**（`export function account_server(){...}`），因此新增配置项要同时改
`repo:server/configs_mac.ts` 与 `repo:server/configs_win.ts`。
`--config ../configs_mac.js` 的相对语义没变：`require` 相对入口模块目录解析，编译后入口在
`dist/<进程>/`，所以它指向 `dist/configs_mac.js`（由 `configs_mac.ts` 编译而来）。

### 端口与进程

| 进程 | 入口 | 端口 |
| --- | --- | --- |
| 账号服 | `repo:server/account_server/app.ts` | 9000（客户端）、12581（代理 API） |
| 大厅服 | `repo:server/hall_server/app.ts` | 9001（客户端）、9002（游戏服上报） |
| 游戏服 | `repo:server/game_server/app.ts` | 10000（客户端 Socket.IO）、9003（HTTP） |

---

## 3. 改动前必读的三条硬约束

### 3.1 玩法规则有两份并行实现，必须同步修改

`repo:server/game_server/gamemgr_xlch.ts`（血战到底，2488 行）与
`repo:server/game_server/gamemgr_xzdd.ts`（另一种玩法，2510 行）是**两个独立文件**，
约 86% 的行逐行相同。房间按 `conf.type` 二选一，两处**调用点**都走同一个懒加载助手
`loadGameManager(type)`，但传入的变量不同名：

```ts
// roommgr.ts:61  懒加载助手（必须懒加载：两个 gamemgr 末尾都有 setInterval(update,1000)）
function loadGameManager(type: string): GameManager {
	return require(type == "xlch" ? "./gamemgr_xlch" : "./gamemgr_xzdd") as GameManager;
}
// roommgr.ts:216  新建房间，读入参
gameMgr:loadGameManager(roomConf.type)
// roommgr.ts:83   从数据库恢复房间，读已落库的 conf
gameMgr:loadGameManager(conf.type)
```

**改了其中一份而没改另一份，就是线上不一致。** 每次修改都要明确回答：另一份是否同样适用？
如果确实只属于一种玩法，在提交说明里写清楚原因。

### 3.2 Socket.IO 事件名是客户端与服务端之间唯一的契约

服务端推送事件名与客户端 `cc.vv.net.addHandler('<event>', fn)` 注册名必须逐字一致，中间没有任何
工具链校验。`npm run check:protocol` 会双向比对这两份词汇表；**新增或重命名任何事件名后必须跑它**。

协议全景见 `repo:docs/ai-native/protocol.md`。

### 3.3 服务端已经能在本机启动，但 DB 相关改动仍需真实 MySQL

历史上三个进程都在 `require` 阶段就崩：`repo:server/utils/http.ts` 依赖原生模块 `fibers`
（只支持到 node 8 左右，在 Node 12+ / Apple Silicon 上根本编译不出来）。**这一点已修复**：

- `fibers` 依赖被整体移除，`utils/http.ts` 里基于 fiber 的同步 HTTP（`getSync`）改回回调风格
  （`getRaw`），账号服 `/image` 是唯一调用方，已同步改写。
- `repo:server/utils/db.ts` 的驱动从 `mysql` 换成 `mysql2`：旧驱动只支持
  `mysql_native_password`，连不上 MySQL 8 默认的 `caching_sha2_password`（brew 装的
  MySQL 8.4 会直接报 `ER_NOT_SUPPORTED_AUTH_MODE`）。

所以现在可以（也应该）用真实启动来验证改动（先编译出 `dist/`）：

```bash
cd server && yarn install --frozen-lockfile && yarn build
node dist/game_server/app.js ../configs_mac.js   # 或 yarn game
```

三个进程各自的启动横幅由 `repo:server/utils/startup.ts` 统一打印：**所有端点真正 listening
之后才打印"启动成功"**，端口被占用时打印明确原因并以非 0 退出；传入 `db` 时横幅还会附带一次
数据库连通性自检，不会把连不上库的进程说成"一切正常"。

仍然需要真实 MySQL 的是 DB 相关路径（注册/登录/建房）。`npm run verify` 不依赖 MySQL，
所以**离线改动的完成判据始终是 `npm run verify`**；只有真实运行时才能确认的改动，
按 `repo:server/AGENTS.md` §8 写明验证方式。

---

## 4. 验证门禁：`npm run verify`

这是本仓库唯一的"完成"判据。门禁自身依赖为零，无需 `npm install`；唯一例外是 `types` 检查的
**`tsc` 那一半**——它要 `server/node_modules/typescript`（`cd server && yarn install` 才有），
没装时这半显示 **skipped** 并说明原因，但同一检查里的 **no-any 审计照跑**（纯文本扫描，
零依赖），其余五项也照跑（`client/` 与 `server/` 共用这一个编译器，客户端不额外引依赖，
见 `repo:server/AGENTS.md` §1.1）。

```bash
npm run verify                 # 跑全部六项检查（提交前必须全绿）
npm run verify -- --verbose    # 打印每个被检查的文件 / 断言
npm run verify -- --json       # 机器可读结果
npm run verify:list            # 列出检查项名称
npm run verify -- --only=types # 只跑类型检查（六项都可这样单跑）
npm run check:syntax           # 只跑语法
npm run check:protocol         # 只跑协议一致性
npm run check:smoke            # 只跑行为冒烟
npm run check:harness          # 只校验本工程自身（AGENTS.md 与 skills）
npm run test:tools             # 校验检查器自身
```

六项检查（顺序固定为 `syntax` → `types` → `harness` → `protocol` → `smoke` → `selftest`）
分别回答：

| 检查 | 回答的问题 |
| --- | --- |
| `syntax` | 80 个一方脚本是否都能被解析（client 47 / server 33）：`.ts` 统一用 Node 内置 `module.stripTypeScriptTypes` 擦类型解析（**只解析不执行**，且顺带强制只用可擦除语法），`.js` 用 `vm.Script` 编译。客户端的 47 = `assets/scripts/` 下 46 个一方脚本 + Creator 自动生成的 `assets/migration/` 助手。另外 `server/` 与 `client/assets/scripts/` 下都不允许残留一方 `.js`（vendored 的 `3rdparty/` 与自动生成的 `assets/migration/` 除外） |
| `types` | `server/` 与 `client/` 是否守住类型契约：① 无依赖的 **no-any 审计**扫一遍所有一方 `.ts`（注释先抹掉、保留行号），`: any` / `as any` / `<any>` / `@ts-ignore` / `@ts-expect-error` 一律算失败；② 装了 `server/node_modules/typescript` 时再分别跑两棵树的 `tsc --noEmit`（strict，客户端用 `client/tsconfig.json`）。缺编译器时 ② 报 skipped，① 仍然执行 |
| `harness` | 本文档与 `.dsh/skills/` 是否能被 Harness 真正发现、格式是否合法 |
| `protocol` | Socket.IO 事件词汇表是否两端对齐 |
| `smoke` | 听牌/胡牌判定、花色分类、MD5 与 Base64（**不含算番**，番值无离线判据） |
| `selftest` | 检查器自身的解析逻辑是否被改动破坏 |

`smoke` 加载服务端模块时**优先直接 require `.ts` 源码**（Node 原生跑 TS；更老的 Node 退回
`dist/` 产物），所以它不需要先 `yarn build`。

**新增可离线验证的纯逻辑时，请顺手往 `repo:tools/lib/smoke.mjs` 加断言。**
宁可多一条断言，也不要让"我改对了"停留在口头。

---

## 5. 具体做法

- **改玩法逻辑**：先读 `repo:docs/ai-native/game-rules.md`；两份 `gamemgr_*` 同步；跑 `npm run verify`。
- **加协议事件**：服务端用 `userMgr.sendMsg` / `userMgr.broacastInRoom`，客户端用
  `cc.vv.net.addHandler`，两侧同名；跑 `npm run check:protocol`。
- **改数据库**：SQL 权威定义在 `repo:server/sql/db_babykylin.sql`；`repo:server/utils/db.ts` 是唯一
  访问层，不要在业务代码里直接拼 SQL。
- **改服务端类型**：共享类型在 `repo:server/types/`（`config.ts` / `domain.ts` / `protocol.ts` /
  `db_rows.ts` / `globals.d.ts` / `socket.io.d.ts`），改完跑 `npm run verify -- --only=types`。
- **改客户端组件**：`repo:docs/ai-native/client-map.md` 有组件职责表；`assets/**/*.meta` 由 Creator
  维护，不要手工编辑内容（新增脚本时把同名 `.meta` 一起改名并保留 `uuid`，否则场景引用会断）。
- **改客户端类型**：共享声明在 `repo:client/types/`（`cc-vv.d.ts` / `domain.d.ts` / `cc-class.d.ts` /
  `cc-augment.d.ts` / `globals.d.ts`），改完跑 `npm run verify -- --only=types`；迁移与断言规矩见
  `repo:docs/ai-native/client-typescript-migration.md`。

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
