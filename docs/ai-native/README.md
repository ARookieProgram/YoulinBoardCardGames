# AI Native 开发工程导览

本目录与 `.dsh/` 一起构成本仓库的 **AI Native 开发工程**：让任何 AI 会话在进入仓库时
不必重新摸索架构，并且**用可执行的证据而不是口头声明来判断改动是否完成**。

面向 AI 的操作契约在根级 `AGENTS.md`；本文是给人看的全景说明。

---

## 1. 为什么这样搭

这个仓库有两类先天的"知识流失"风险，都不是靠多写注释能解决的：

| 风险 | 具体表现 | 本工程的应对 |
| --- | --- | --- |
| **架构只存在于人脑** | 三个进程、六个监听端口、两条签名链路、两份并行玩法实现，散落在 35 个服务端源码文件（`.ts`）里 | `AGENTS.md` 分层契约 + 5 个技能包 + 本目录五份参考文档 |
| **无法验证 = 无法交付** | 服务端完整链路需要真实 MySQL（`fibers` 的启动障碍已清除，见根 `AGENTS.md` §3.3），客户端需要图形化编辑器构建，2016 年的 `tests/*.ts` 只会打印不断言 | `npm run verify`：零依赖、可离线跑的六项门禁（`types` 缺编译器时自报 skipped） |

**核心设计原则：把"能自动判断的对错"全部自动化，把"只能人工确认的"显式标注出来。**
不假装能验证不能验证的东西（见 §5）。

**技术栈现状**：服务端是 Node.js + **TypeScript（`strict: true`）** + Express + Socket.IO +
MySQL（`mysql2`），由 `tsc` 编译到 `server/dist/` 后运行；客户端是 Cocos Creator 2.4.15 的
**TypeScript**（组件用 ES6 `class` + `cc._decorator` 的 `@ccclass` / `@property`，
由 Creator 自带的 Babel 管线编译）。两边都经历过**行为不变的迁移**：
服务端是 ES5 JS → TypeScript，客户端先 `.js` → `.ts`、再 `cc.Class` → `class`。
所以源码里同样保留 `var` / `function` / 回调，只有模块语法换成了 `import` / `export`
（由 `tsc --module CommonJS` 编译回 `require`）——为什么这么定、逐条规矩是什么，见
`repo:docs/ai-native/typescript-migration.md` 与 `repo:docs/ai-native/client-typescript-migration.md`。

---

## 2. 四层知识载体

```
第 0 层  项目根标记            .git
第 1 层  每次必读的短契约      AGENTS.md（根）、client/AGENTS.md、server/AGENTS.md
第 2 层  按需加载的长知识      .dsh/skills/<name>/SKILL.md   ×5
第 3 层  人类可读的参考文档    docs/ai-native/*.md           ×5
```

为什么这样分层：

- **第 1 层必须短**，因为它占用每一次会话的上下文。它只放红线（改哪里会连带改什么）和
  验证命令，不放教程。
- **第 2 层按需加载**，由技能的 `description` 触发。比如改番型时才加载 `game-rules`，
  不写玩法代码的会话完全不付这个成本。
- **第 3 层给人看**，可以写长、写全，也可以被技能引用。

| 载体 | 文件 | 内容 |
| --- | --- | --- |
| 根契约 | `repo:AGENTS.md` | 仓库全貌、三条硬约束、门禁用法、Harness 契约 |
| 客户端契约 | `repo:client/AGENTS.md` | 工程边界（哪些不能手改）、`cc.vv` 单例、组件表、场景流程 |
| 服务端契约 | `repo:server/AGENTS.md` | 三进程职责、登录链路、两份玩法实现、数据访问层、推送规范 |
| 技能索引 | `repo:docs/ai-native/skills-guide.md` | 技能加载规则、新增技能模板与写作原则 |
| 协议全景 | `repo:docs/ai-native/protocol.md` | 39 个推送事件 + 20 个客户端事件 + HTTP 接口索引（§1 表格与源码的一致性由门禁强制） |
| 玩法规格 | `repo:docs/ai-native/game-rules.md` | 牌编码、听牌算法、**七对未实现**、动作常量与回放兼容红线、房间配置两层结构 |
| TS 迁移规范（服务端） | `repo:docs/ai-native/typescript-migration.md` | 服务端为什么编译到 `dist/`、逐条转换规则、共享类型清单、刻意的严格性取舍 |
| TS 迁移规范（客户端） | `repo:docs/ai-native/client-typescript-migration.md` | 客户端为什么没有构建步骤、Creator 的 Babel 管线能吃什么语法、`cc.Class` → `@ccclass`/`@property` 的逐项对应、`cc.vv` / 域模型声明在哪、改名时 `.meta` 的 uuid 为什么不能丢 |
| 客户端结构 | `repo:docs/ai-native/client-map.md` | 目录边界、脚本分层、组件职责、场景图 |

### 技能清单

| 技能 | 触发场景 |
| --- | --- |
| `verify-gate` | 跑/读/扩展门禁，门禁报红 |
| `server-architecture` | 改服务端、加接口、加推送事件 |
| `game-rules` | 改听牌/胡牌/番型/流程 |
| `client-integration` | 改客户端组件、加事件处理器、改场景 |
| `data-layer` | 改持久化、加 `db.ts` 函数、改 schema |

技能实现细节见 `repo:docs/ai-native/skills-guide.md`。

---

## 3. 验证门禁

```bash
npm run verify            # 六项全跑（交付前必须全绿）
npm run verify -- --verbose
npm run verify -- --json
npm run verify:list
```

| 检查 | 断言 | 实现 |
| --- | --- | --- |
| `syntax` | 80 个一方脚本（client 47 / server 33）都能被解析：`.ts` 用 `module.stripTypeScriptTypes` 擦类型解析（只允许可擦除语法），`.js` 用 `vm.Script` **编译但不执行**；另外校验 client 的脚本 `.meta` 与场景组件绑定是否还成立 | `repo:tools/lib/syntax.mjs`、`repo:tools/lib/assets.mjs` |
| `types` | 两半：① 零依赖的 **no-any 审计**扫所有一方 `.ts`（`: any` / `as any` / `<any>` / `@ts-ignore` / `@ts-expect-error` 一律失败），并在 `client/` 里查残留的 `cc.Class(` 与「有 `export default class X` 就必须有 `module.exports = X;`」；② `tsc --noEmit` 严格类型检查（`strict: true`）。缺 `server/node_modules/typescript` 时 ② 报 skipped，① 仍执行 | `repo:tools/verify.mjs` |
| `harness` | 3 份 `AGENTS.md` + 5 个技能存在、frontmatter 合法、`repo:` 引用存在 | `repo:tools/lib/harness.mjs` |
| `protocol` | 三向对齐：服务端推送 ↔ 客户端处理器 ↔ `protocol.md` §1 表格（39 推送 / 44 处理器） | `repo:tools/lib/protocol.mjs` |
| `smoke` | 听牌/胡牌判定的 5 类牌型 + 花色边界 + MD5 + Base64（含中文昵称）+ `String.prototype.format` + `http.queryString`/`queryInt`，共 19 条断言 | `repo:tools/lib/smoke.mjs` |
| `selftest` | 检查器自身的 21 个用例（含畸形输入、`.ts` 语法检查、`.d.ts` 跳过） | `repo:tools/selftest.test.mjs` |

**"只解析不执行"仍然是关键设计**：门禁必须零依赖、离线可跑，所以 `.js` 用 `vm.Script`
只编译不执行，`.ts` 用 Node 内置 `module.stripTypeScriptTypes` 只擦类型不运行（因此还顺带强制
"只允许可擦除语法"），既拿到语法错误的全部价值，又不需要原生依赖或数据库。`.ts` 那一半需要
**Node ≥ 22.13**，更老的 Node 上这些文件在摘要里被明确标成 `skipped` 而不是通过。
服务端本身现在可以真实启动（见根 `AGENTS.md` §3.3），但**门禁不替你做运行时验证**——
那一步请按 `repo:server/AGENTS.md` §8 手动跑。`selftest` 则保证门禁自己不会"假绿"。

---

## 4. 这套工程在本仓库实际抓到了什么

搭建过程中，**门禁报红**暴露了两个真实缺陷（都是长期存在、人工评审没发现的）：

1. **`mjutils.getMJType` 读取未定义变量**（形参是 `pai`，函数体写 `id`）——调用即抛
   `ReferenceError`，`smoke` 的 3 条断言直接失败。因无调用方而长期潜伏。已修正。
2. **`push_need_create_role` 是死代码**——客户端注册了处理器，服务端从不推送，
   `protocol` 的 `unsent` 直接报出。已记录为协议债务
   （`repo:docs/ai-native/protocol.md` §4），未擅自删除，因为会影响登录分支。

还有一条**文档与源码脱节**也是独立审计发现的，并已转成永久检查：
`protocol.md` §1 的事件表当时没有任何机制校验，可以悄悄过期却显得权威。
现在 `check:protocol` 会三向比对，表格漏写或写了不存在的事件都会报红
（已用「删一行 + 加一行假事件」验证过它确实会失败）。

另有一个缺陷是**主动补断言时发现的**，而不是门禁报红（这点必须说清）：

3. **`crypto.toBase64/fromBase64` 使用已弃用的 `new Buffer()`**——它只打印 `DEP0005` 弃用告警，
   Base64 往返本身仍然正确，所以**门禁当时是绿的**。是在为这条路径补中文昵称往返断言时
   顺带发现的。已改为 `Buffer.from()` 并留下断言。

还有一个是**独立审计**发现的：**七对（七小对）在本引擎里根本没实现**，
而最初的冒烟断言却把一手"四顺子 + 将牌"误标成了"七对"。现已改正断言标签，
并新增一条断言把"不认七对"这个现状钉住（详见 `repo:docs/ai-native/game-rules.md` §4）。

另外，门禁在搭建期也抓到了**我自己**引入的缺陷：在根 `package.json` 里加
`"type": "module"` 会让整个 CommonJS 服务端按 ESM 解析（`exports is not defined`），
`syntax` 立刻报红——这条检查确实在起作用。

---

## 5. 明确的边界：哪些东西没有被验证

诚实标注边界比夸大覆盖更重要。**以下内容没有自动化验证**：

| 项目 | 原因 |
| --- | --- |
| 服务端运行时行为 | 门禁不启动进程；`db.ts` 的 DB 路径需要真实 MySQL（进程本身已可在 mac + Node 24 启动） |
| SQL 的执行结果 | 无数据库实例。门禁只解析 `.js` / `.ts` 语法并做类型检查，不校验 SQL |
| 客户端构建与运行 | Creator 2.4.15 依赖图形化编辑器；`library/`、`temp/` 是本机产物 |
| HTTP 接口路径的增删 | 门禁只覆盖 Socket.IO 事件名，不覆盖 Express 路由 |
| `.fire` / `.meta` / 美术资源 | 由编辑器维护，人工在编辑器内验证 |
| 番型算分的业务正确性 | 只听牌/胡牌判定有断言；具体番值需要产品确认，无法凭代码自证 |

对应的纪律写在三份 `AGENTS.md` 里：**需要真实运行时才能确认的改动，
交付说明必须写明"未运行时验证"并列出依赖的静态证据。**

---

## 6. 日常用法

**AI 会话**：直接开始干活。根 `AGENTS.md` 会自动出现；操作 `client/` 或 `server/` 时对应契约叠加；
相关技能按描述加载。交付前跑 `npm run verify`。

**人**：
1. 先读根 `AGENTS.md`（约 5 分钟），拿到全貌与红线。
2. 想深入某块时读对应技能或本目录文档。
3. 提交前 `npm run verify`。

**给这个工程加东西**：

| 想加什么 | 加在哪 |
| --- | --- |
| 每条会话都必须知道的红线 | 根 `AGENTS.md` |
| 某目录特有的约定 | 该目录的 `AGENTS.md` |
| 某类任务的完整流程 | 新技能（模板见 `skills-guide.md`） |
| 可离线判断的行为约束 | `repo:tools/lib/smoke.mjs` 加断言 |
| 新的自动检查 | `repo:tools/verify.mjs` 的 `CHECKS` + `selftest` 补用例 |
| 长篇幅的背景知识 | 本目录新增 `.md` |

---

## 7. 目录索引

```
AGENTS.md                      ← 根级 AI 契约
client/AGENTS.md               ← 客户端契约
server/AGENTS.md               ← 服务端契约
package.json                   ← 门禁入口（npm run verify）
.dsh/skills/                   ← 5 个项目技能
├─ verify-gate/SKILL.md
├─ server-architecture/SKILL.md
├─ game-rules/SKILL.md
├─ client-integration/SKILL.md
└─ data-layer/SKILL.md
docs/ai-native/                ← 本目录
├─ README.md                   ← 你正在读的这份
├─ skills-guide.md             ← 技能加载规则与新增模板
├─ protocol.md                 ← Socket.IO 协议全景
├─ game-rules.md               ← 玩法规格与兼容红线
├─ typescript-migration.md     ← 服务端 TS 迁移规范
├─ client-typescript-migration.md ← 客户端 TS 迁移规范
└─ client-map.md               ← 客户端结构图
tools/                         ← 门禁实现（零依赖）
├─ verify.mjs                  ← 编排
├─ selftest.test.mjs           ← 检查器自测
└─ lib/{syntax,assets,harness,protocol,smoke}.mjs
```
