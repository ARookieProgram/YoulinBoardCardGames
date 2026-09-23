---
name: verify-gate
description: How to run, read, and extend this repository's dependency-free verification gate (npm run verify). Use when finishing any change, when the gate fails, or when adding a new check or smoke assertion.
---

# 验证门禁的使用与扩展

本仓库的"完成"定义是 **`npm run verify` 全绿**。这是唯一不依赖真实运行时的客观证据，
所有改动都必须过它。门禁自身零依赖，不装任何包也能跑完（服务端第三方依赖另由
`repo:server/yarn.lock` 管理，门禁按目录名跳过 `node_modules`）；唯一的例外是 `types` 检查，
它需要 `server/node_modules/typescript`，没装时该项自己报 **skipped** 而不是伪装成通过。

## 什么时候用

- 改完任何代码，准备交付前 —— 必跑。
- 门禁报红 —— 用它定位。
- 想新增一条"我改对了"的证据 —— 按下面 §4 扩展。

## 1. 跑哪些命令

```bash
npm run verify                      # 六项全跑（默认）
npm run verify -- --verbose         # 打印每个被检查的文件 / 每条断言
npm run verify -- --json            # 机器可读结果，便于程序解析
npm run verify -- --only=protocol   # 只跑一项；多项用逗号分隔
npm run verify:list                 # 列出检查项名称
npm run test:tools                  # 只跑检查器自测
```

退出码：`0` 全绿，`1` 有失败。

## 2. 六项检查分别在证什么

顺序固定为 `syntax` → `types` → `harness` → `protocol` → `smoke` → `selftest`：

| 名称 | 断言 | 失败意味着 |
| --- | --- | --- |
| `syntax` | 共 80 个一方 `.js` / `.ts`：`.js` 用 `vm.Script` 编译、`.ts` 用 Node 内置 `module.stripTypeScriptTypes` 擦类型解析（**都只编译不执行**），并顺带强制 `.ts` 只用可擦除语法 | 有语法错误，运行时必崩；或用了 `enum` / `namespace` / `import x = require()` / 构造函数参数属性 |
| `types` | 两半：① **no-any 审计**（零依赖，永远执行）扫 `server/` 与 `client/` 下所有一方 `.ts`，注释先抹掉但保留行号，`: any` / `as any` / `<any>` / `@ts-ignore` / `@ts-expect-error` 一律失败；同一遍扫描在 `client/` 里还查两件事：残留的 `cc.Class(`、以及「有 `export default class X` 就必须有 `module.exports = X;`」（Creator 的 `require("X")` 取 `module.exports`，漏了就报 "X is not a constructor"）；② 装了 `server/node_modules/typescript` 时再跑两棵树的 `tsc --noEmit -p tsconfig.json`（`strict: true`） | 服务端/客户端有类型错误，用了类型逃生舱，客户端写回 `cc.Class`，或类文件漏了 `module.exports`。缺编译器时 ② 显示 **skipped**（并说明原因）而 ① 仍然执行，不是通过 |
| `harness` | `AGENTS.md`×3 与 `.dsh/skills/*/SKILL.md` 存在、frontmatter 合法、`repo:` 路径存在 | Harness 会**静默**忽略这些知识 |
| `protocol` | Socket.IO 事件词汇表两端逐字对齐 | 客户端收不到、或永远等不到某事件 |
| `smoke` | 麻将听牌判定、花色边界、MD5/Base64，加上 `String.prototype.format` 的三种形态与 `http.queryString` / `queryInt` 契约，共 19 条断言 | 纯逻辑被改坏 |
| `selftest` | 检查器自己的解析/比对逻辑（含 `.ts` 语法检查与 `collectScripts` 收集 `.ts`、跳过 `.d.ts`），共 21 个用例 | 门禁本身坏了（会假绿） |

**`syntax` 刻意不执行文件**：服务端的 `db.ts` 需要一个真实 MySQL 连接，执行就会在
`require`/建池阶段出问题。`vm.Script` / `stripTypeScriptTypes` 只解析不运行，正好绕开这一点。
`.ts` 那一半依赖 Node 的 `module.stripTypeScriptTypes`（需要 **Node ≥ 22.13**）：更老的 Node 上
这些文件会被明确标成 **`⊘ skipped` 而不是 ok**，摘要里也会写出跳过了多少个。

**`types` 是唯一需要安装步骤的检查**——而且只有它的一半需要：`tsc --noEmit` 要
`server/node_modules/typescript`（`cd server && yarn install` 之后才有），**no-any 审计是纯文本
扫描，没有编译器也照跑**。其余五项在**没有 MySQL、没有 `server/node_modules`** 的环境里也能跑完。
你新增检查时也要守住这条：要么零依赖，要么像 `types` 那样把"没条件看"的那半老实报成 skipped。

实现分别在 `repo:tools/lib/syntax.mjs`、`repo:tools/lib/harness.mjs`、
`repo:tools/lib/protocol.mjs`、`repo:tools/lib/smoke.mjs`，编排在 `repo:tools/verify.mjs`。

## 3. 常见失败怎么处理

**`protocol`: "server pushes 'x' but no client handler registers it"**
服务端在某处推送了 `x`，客户端没有任何 `addHandler`。先在客户端补注册；如果确实是要废弃的事件，
删掉服务端推送。**不要**为了让门禁变绿而把事件加进忽略列表——忽略列表只用于已确认的死代码。

**`protocol`: "client handles 'x' but no server push sends it"**
客户端在等一个永远不会来的事件。要么服务端补推送，要么删掉客户端处理器。
已有的例外只有 `push_need_create_role`（见 `repo:tools/lib/protocol.mjs` 的 `KNOWN_UNSENT`）。

**`harness`: "frontmatter name does not match directory"**
`.dsh/skills/foo/SKILL.md` 里的 `name:` 必须是 `foo`。不匹配 = Harness 忽略整个技能。

**`harness`: "references 'path', which does not exist"**
技能正文里 `` `repo:某路径` `` 指向了不存在的文件。改了文件位置就要同步更新引用。

**`smoke` 失败**
说明 `repo:server/game_server/mjutils.ts` 或 `repo:server/utils/crypto.ts` 的行为变了。
先确认这是**有意**的行为变更；是，则更新断言并说明原因；不是，则修代码。
`smoke` 加载模块时**优先直接 require `.ts` 源码**（Node 原生跑 TS；更老的 Node 退回
`dist/<模块>.js` 产物），所以它既不需要编译也不需要 `yarn install`。

## 4. 怎么扩展门禁

### 加一条行为断言（最常用）

编辑 `repo:tools/lib/smoke.mjs`，在 `runSmoke()` 里用 `assert(name, condition, detail)`：

```js
const seat = buildSeat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13]);
mjutils.checkTingPai(seat, 0, 27);
assert("...", Object.keys(seat.tingMap).join(",") === "13", JSON.stringify(seat.tingMap));
```

**只加能离线判定的断言**：纯函数、字符串/数值变换、数据结构。凡是需要 DB、socket、真实进程
的，写到这里只会让门禁变脆。

### 加一项检查

在 `repo:tools/verify.mjs` 里写一个返回
`{ name, title, ok, summary, failures }` 的 async 函数，然后加进 `CHECKS` 数组。
检查里**必须**把异常交回编排层（它会记成失败而不是崩溃），不要自己 `process.exit`。

### 改检查器逻辑

必须同时在 `repo:tools/selftest.test.mjs` 里加/改用例。`selftest` 就是防止"检查器改坏了还报绿"。
夹具要覆盖畸形输入，例如 `parseFrontmatter` 对未闭合 frontmatter 的行为。

## 5. 反模式

- ❌ **为了让门禁变绿而放宽检查**。门禁的价值在于它敢报红。
- ❌ **把失败项塞进忽略列表**。忽略列表要有注释解释为什么是死代码。
- ❌ **在门禁里跑 `server/tests/*.ts`**。它们是 2016 年的手工脚本，会连数据库、只打印不断言。
- ❌ **声称"已验证"但没有跑门禁**。没验证就写"未运行时验证"并说明依赖了什么静态证据。
