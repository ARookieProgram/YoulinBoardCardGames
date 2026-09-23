# 服务端 TypeScript 迁移规范

本文是 `repo:server/` 从 2016 年 ES5 CommonJS JavaScript 迁移到 TypeScript 时定下的**统一约定**，
也是后续维护者理解这套代码为什么长这样的入口。迁移的硬要求：**严格类型、尽量不用 `any`、行为不变**。

> 面向人的背景：为什么是"编译到 dist"而不是"Node 直接跑 .ts"，见 §7。

---

## 1. 目录与构建

```
server/
├─ tsconfig.json          编译器配置（strict 全开）
├─ types/                 跨模块共享的**类型模块**（纯类型，编译后是空模块）
│  ├─ config.ts           配置文件结构（configs_mac.ts / configs_win.ts 的契约）
│  ├─ domain.ts           游戏域模型：RoomInfo / RoomSeat / GameState / GameSeat / GameManager
│  ├─ protocol.ts         Socket.IO 事件名与载荷、GameSocket
│  ├─ db_rows.ts          数据库行结构（sql/db_babykylin.sql 的 TS 视图）
│  ├─ globals.d.ts        String.prototype.format 的补丁声明
│  └─ socket.io.d.ts      socket.io 1.7 的最小类型声明（1.x 不带类型）
├─ utils/                 db / http / crypto / startup / config
├─ <进程>/                 account_server / hall_server / game_server
├─ dist/                  **编译产物**，不提交（server/.gitignore 已忽略）
└─ tests/                 2016 年的手工脚本（已随迁移改成 `.ts`），**不是测试套件**
```

```bash
cd server
yarn install --frozen-lockfile   # 依赖（含 typescript / @types）
yarn build                       # tsc -> dist/
yarn typecheck                   # tsc --noEmit，只看类型
yarn account | yarn hall | yarn game   # 前台调试单个进程
```

跑起来的命令与迁移前只差一个 `dist/` 前缀：

```bash
node dist/game_server/app.js ../configs_mac.js
```

`../configs_mac.js` 的语义**没有变**：`require` 相对**入口模块目录**解析，编译后入口在
`dist/game_server/`，因此它指向 `dist/configs_mac.js`（由 `configs_mac.ts` 编译而来）。
`start_all_mac.sh` 的 `--config` 与之保持一致。

---

## 2. 转换规则（逐条照做）

1. **一个文件一个文件地换**：`foo.js` → `foo.ts`，内容逐字迁移后再补类型；确认无误后**删掉**
   `foo.js`（不要留同名 .js，否则读代码的人不知道该看哪份）。
2. **行为绝对不变**。这次是类型迁移，不是重构：
   - 保留 `var` 与 `function` 声明，**不要把 `var` 改成 `let`/`const`、也不要把回调改成箭头函数**。
     老代码里有 `for (var i …) { setTimeout(function(){ … i … }) }` 这类闭包，
     `var`→`let` 会直接把行为改掉。新引入的局部变量也沿用 `var`，与文件其余部分一致。
   - 不"顺手修 bug"、不改日志、不改函数名、不改事件名与字符串字面量、不调换语句顺序。
     发现可疑之处写进交付说明，不要动。
   - 保留原有中文注释；新增注释也用中文。
3. **模块语法**：用 ESM 写法（`import * as db from "../utils/db"` / `export function foo(...)`），
   由 `tsc`（`module: CommonJS`）编译成 `require`。不要写 `import x = require("…")`、
   `export =`、`enum`、`namespace`、构造函数参数属性——这些都是**不可擦除语法**，
   会让门禁的 `.ts` 语法检查（`module.stripTypeScriptTypes`）直接报错。只 import 类型时用
   `import type { … } from "…"`。
4. **不引入 `any`**。按优先级选择：
   1. 精确类型（首选）；
   2. `unknown` + 收窄（`typeof` / `in` / `instanceof`）；
   3. `object`、`Record<string, unknown>` 这类"宽但不是 any"的结构类型；
   4. 确实跨越动态边界时，用一次**带注释的断言**集中在边界处，例如
      `const x = {} as SeatData;`、`require(path) as ServerConfigs`。禁止 `as any`、
      `@ts-ignore`、`@ts-expect-error`。
5. **动态对象**照第 4 条第 4 点处理，且**不要为了好写类型而给对象补字段**：
   老代码靠"字段不存在"表达状态（例如 `roomInfo.dr != null`），补初始值会改行为。
6. 第三方库只能从既有的四个**运行时依赖**里用：`express`、`mysql2`、`socket.io`、`log4js`（未使用）。
   **不要 `yarn add` 任何新包**；缺类型就手写最小声明（参考 `types/socket.io.d.ts`）。
   迁移另外带来 3 个 **devDependencies**：`typescript`、`@types/node`、`@types/express`——
   它们只服务 `yarn build` / `yarn typecheck` / 门禁的 `types` 检查，不进运行时。
   运行时依赖与开发依赖在 `server/package.json` 里是分开声明的，别把 `@types/*` 写进 `dependencies`。

---

## 3. 已经就绪的共享类型与工具

### `types/domain.ts`
`RoomInfo`、`RoomSeat`、`RoomConf`、`RoomCreateConf`、`GameState`、`GameSeat`、`TingMap`、
`CountMap`、`HuInfoItem`、`UserActionRecord`、`QiangGangContext`、`DissolveRequest`、
`GamePhase`、`RoomType`、`GameManager`。
两份玩法实现（`gamemgr_xlch.ts` / `gamemgr_xzdd.ts`）共用这一套；`GameManager` 是它们共同满足的契约，
`roommgr` 通过它调用玩法实现。

### `types/protocol.ts`
`ServerPushEvent`（39 个推送事件名）、`ClientToServerEvents`（客户端事件签名）、
`GameSocket`（socket.io 连接 + `userId` / `gameMgr`）、`SocketPayload`。

### `types/db_rows.ts`
`AccountRow`、`UserRow`、`UserBriefRow`、`UserBaseInfoRow`、`RoomRow`、`RoomAddrRow`、
`GameRow`、`MessageRow`。`utils/db.ts` 会把这些类型再导出一次，调用方从 `db` 或
`types/db_rows` 引入都行。

### `utils/http.ts`
```ts
type QueryParams = Record<string, string | number | boolean | null | undefined>;
type HttpResult  = { ok: true; data: JsonObject } | { ok: false; error: Error };
type HttpCallback = (result: HttpResult) => void;      // get / get2 的新回调形态
type RawCallback  = (contentType: string | undefined | null, body: JsonObject | string | null) => void;

get(host, port, path, data, callback, safe?)            // 结果回调改为单一 result 对象
get2(url, data, callback, safe?)
getRaw(url, data, safe, encoding, callback)
post(host, port, path, data, callback)
send(res, errcode, errmsg, data?)                       // 大厅服/游戏服统一 JSON 出口
queryString(req, name): string | undefined              // 取 query 字符串
queryInt(req, name): number                             // 取 query 整数，缺参数为 NaN
```
**注意 `get`/`get2` 的回调形状变了**（原来是 `callback(ret, data)`）：
```ts
http.get(host, port, path, params, function (result) {
  if (!result.ok) { /* 网络失败 */ return; }
  var data = result.data;   // JsonObject：字段是 unknown，取用时收窄
});
```

### `utils/crypto.ts`
`md5(content)`、`toBase64(content)`、`fromBase64(content)`（签名与行为逐字不变）。

### `utils/config.ts`
`loadConfigs(process.argv[2], __dirname): ServerConfigs`——三个入口用它读配置文件。

---

## 4. HTTP 处理器写法（大厅服 / 游戏服 / 账号服）

```ts
import express from "express";
import type { Request, Response, NextFunction } from "express";
import * as http from "../utils/http";

var app = express();

app.get("/login", function (req: Request, res: Response) {
  var account = http.queryString(req, "account");
  var sign = http.queryString(req, "sign");
  if (account == null || sign == null) {
    http.send(res, 1, "invalid parameters");
    return;
  }
  ...
});
```
`res.header(...)` / `res.send(...)` 直接用 `@types/express` 的类型。
账号服仍然用**它自己的本地 `send(res, ret)`**（历史约定，不要为"统一"而大改）。

---

## 5. 推送与玩法

- 对局内推送：`userMgr.sendMsg(userId, event, data)` / `userMgr.broacastInRoom(...)`（拼写就是
  `broacast`）；连接阶段可以 `socket.emit(event, payload)`。
- 事件名必须与客户端一致，且**保留字符串字面量**：`npm run check:protocol` 用正则扫源码，
  写成变量或常量会让门禁看不见这次推送。
- `roommgr` 里对 gamemgr 的加载**必须保持懒加载**：两个 gamemgr 文件末尾都
  `setInterval(update, 1000)`，同时 require 会跑起两个定时器。写法：
  ```ts
  function loadGameManager(type: string): GameManager { … require(…) as GameManager }
  ```
  并在每个 gamemgr 文件末尾用一次编译期自检，确认导出满足 `GameManager`。

---

## 6. 改完怎么验证

```bash
cd server
./node_modules/.bin/tsc --noEmit          # 类型（只看类型，不产出 dist/；错了会逐行打印）
node --check <你改的文件>.ts               # 单文件语法（不依赖任何包，需要 Node >= 22.13）
yarn build                                # 产出 dist/
```

全部文件迁移完成后，仓库根目录的门禁是最终判据（六项，顺序固定）：

```bash
npm run verify          # syntax / types / harness / protocol / smoke / selftest
npm run verify -- --verbose
```

其中 `types` 这一项是**两半**，正好对应本文的两条硬要求：

- **no-any 审计**（零依赖，永远执行）：扫 `server/` 下所有一方 `.ts`，把注释先抹掉、行号保留，
  命中 `: any`、`as any`、`<any>`、`@ts-ignore`、`@ts-expect-error` 即失败——
  把"尽量不用 `any`、不许用逃生舱"变成机械约束，而不是靠评审自觉；
- **`tsc --noEmit -p tsconfig.json`**（`strict: true`）：需要 `server/node_modules/typescript`
  （`yarn install` 提供）。没装时这半报 **skipped** 并写明原因，审计那一半照跑。

`syntax` 项对 `.ts` 用的是 Node 内置的 `module.stripTypeScriptTypes`，它擦类型的方式与编译器一致，
并且**拒绝不可擦除语法**（`enum` / `namespace` / `import x = require()` / 构造函数参数属性）——
所以 §2 第 3 条不是口头约定，写错会直接报红。

---

## 7. 为什么编译到 `dist/` 而不是让 Node 直接跑 `.ts`

- **保持 CommonJS 语义**：`tsc --module CommonJS` 产出与老代码同样的 `require`/`exports`，
  循环依赖、懒加载、`String.prototype` 补丁的加载顺序都不变。
- **不抬高 Node 版本门槛**：Node 的 `.ts` 支持是逐步到位的——`module.stripTypeScriptTypes`
  要 **≥ 22.13**，直接 `require()` / 运行 `.ts` 要 **≥ 22.18**。让进程入口直接跑 `.ts` 会把
  `server` 的最低 Node 版本从根 `package.json` 声明的 18 一把抬到 22 以上。
  另外原生 type stripping 只接受**可擦除语法**（`enum`、`namespace`、`import x = require()`、
  构造函数参数属性都不行），作为"唯一的运行方式"会让这些普通 TS 写法变成运行时错误；
  这里把它当**门禁约束**用（见 §2 第 3 条）就刚好。
  （`repo:tools/lib/smoke.mjs` 确实会优先 `require` `.ts` 源码——那是门禁为省掉构建步骤走的便利
  路径，且有 `dist/` 产物兜底；三个进程入口依然跑编译产物。）
- 代价是多一个构建步骤，以及 `dist/` 这个不提交的产物目录——换来的是"行为不变"这条底线。

**刻意的取舍**（不是漏配，配置里也写了注释）：`noUncheckedIndexedAccess`、`noImplicitReturns`、
`noUnusedLocals` 没有开。前两项会让 `countMap[pai]`、`seats[i]` 这类几百处访问都需要补默认值，
在"牌局逻辑一处都不能改"的前提下风险远大于收益；等有一次专门的重构再谈。
