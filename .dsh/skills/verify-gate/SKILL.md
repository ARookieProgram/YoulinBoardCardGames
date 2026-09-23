---
name: verify-gate
description: How to run, read, and extend this repository's dependency-free verification gate (npm run verify). Use when finishing any change, when the gate fails, or when adding a new check or smoke assertion.
---

# 验证门禁的使用与扩展

本仓库的"完成"定义是 **`npm run verify` 全绿**。这是唯一不依赖真实运行时、不依赖
`npm install` 的客观证据，所有改动都必须过它。

## 什么时候用

- 改完任何代码，准备交付前 —— 必跑。
- 门禁报红 —— 用它定位。
- 想新增一条"我改对了"的证据 —— 按下面 §4 扩展。

## 1. 跑哪些命令

```bash
npm run verify                      # 五项全跑（默认）
npm run verify -- --verbose         # 打印每个被检查的文件 / 每条断言
npm run verify -- --json            # 机器可读结果，便于程序解析
npm run verify -- --only=protocol   # 只跑一项；多项用逗号分隔
npm run verify:list                 # 列出检查项名称
npm run test:tools                  # 只跑检查器自测
```

退出码：`0` 全绿，`1` 有失败。

## 2. 五项检查分别在证什么

| 名称 | 断言 | 失败意味着 |
| --- | --- | --- |
| `syntax` | 74 个一方 `.js` 能被 `vm.Script` 编译（**编译但不执行**） | 有语法错误，运行时必崩 |
| `harness` | `AGENTS.md`×3 与 `.dsh/skills/*/SKILL.md` 存在、frontmatter 合法、`repo:` 路径存在 | Harness 会**静默**忽略这些知识 |
| `protocol` | Socket.IO 事件词汇表两端逐字对齐 | 客户端收不到、或永远等不到某事件 |
| `smoke` | 麻将听牌判定与 MD5/Base64 工具的行为断言 | 纯逻辑被改坏 |
| `selftest` | 检查器自己的解析/比对逻辑 | 门禁本身坏了（会假绿） |

**`syntax` 刻意不执行文件**：`server` 里的 `fibers` 原生模块在当前 Node 上无法加载，
若执行就会在 `require` 阶段炸掉。用 `vm.Script` 只编译不运行，正好绕开这一点。
你新增检查时也要守住这条：**门禁必须能在没有 MySQL、没有 fibers 的环境里跑完**。

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
说明 `repo:server/game_server/mjutils.js` 或 `repo:server/utils/crypto.js` 的行为变了。
先确认这是**有意**的行为变更；是，则更新断言并说明原因；不是，则修代码。

## 4. 怎么扩展门禁

### 加一条行为断言（最常用）

编辑 `repo:tools/lib/smoke.mjs`，在 `runSmoke()` 里用 `assert(name, condition, detail)`：

```js
const seat = buildSeat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13]);
mjutils.checkTingPai(seat, 0, 27);
assert("...", Object.keys(seat.tingMap).join(",") === "13", JSON.stringify(seat.tingMap));
```

**只加能离线判定的断言**：纯函数、字符串/数值变换、数据结构。凡是需要 DB、socket、fibers
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
- ❌ **在门禁里跑 `server/tests/*.js`**。它们是 2016 年的手工脚本，会连数据库、只打印不断言。
- ❌ **声称"已验证"但没有跑门禁**。没验证就写"未运行时验证"并说明依赖了什么静态证据。
