# 客户端 TypeScript 迁移手册（`client/`）

本文件是 `repo:client/` 从 2016 年 ES5 + `cc.Class` 迁移到 TypeScript 时定下的统一约定，
配套的类型基础在 `repo:client/types/`。**硬要求与服务端迁移一致：严格类型、尽量不用 `any`、
运行时行为绝对不变。**

> 服务端迁移的对应规范见 `repo:docs/ai-native/typescript-migration.md`；客户端这一侧的差异
> （`cc.Class`、`cc.vv`、Creator 的脚本模块机制）集中写在这里。

---

## 1. 迁移后长什么样

```
client/
├─ tsconfig.json          仅服务 `tsc --noEmit` 与编辑器补全（Creator 自己另有一套编译流程）
├─ types/                 手写的全局声明（纯类型，编译后什么都没有）
│  ├─ globals.d.ts        require / window.io / socket.io 客户端最小声明
│  ├─ cc-class.d.ts       cc.Class 的泛型重载（properties 摊平 + ThisType）
│  ├─ cc-vv.d.ts          cc.vv 上全部单例的接口
│  ├─ cc-augment.d.ts     引擎漏声明与本项目动态字段（cc.Node.emit 等）
│  └─ domain.d.ts         网络载荷与对局域模型
└─ assets/scripts/
   ├─ *.ts                管理器（原来就是 .js，逐个改名）
   └─ components/*.ts     34 个场景组件
```

**没有构建步骤**：Creator 2.4.15 自己编译 `.ts`（走它内置的 TypeScript + Babel），
`client/tsconfig.json` 只是给 `tsc --noEmit` 和 IDE 用的。所以 `.d.ts` 怎么声明都不影响运行时。

---

## 2. 逐条规矩

1. **一个文件一个文件地换**：`foo.js` → `foo.ts`，先按老内容逐字搬过来，再补类型；
   搬完**删掉** `foo.js`，并把 `foo.js.meta` 改名为 `foo.ts.meta`。
   **meta 里的 `uuid` 必须原样保留**——场景 `.fire` 用 uuid 引用脚本组件，uuid 变了场景就断了。
   改名用普通 `mv`（不要 `git mv`，避免并行作业抢 git index 锁）：
   ```bash
   mv assets/scripts/Foo.js assets/scripts/Foo.ts        # 先写好 Foo.ts 再删也行
   mv assets/scripts/Foo.js.meta assets/scripts/Foo.ts.meta
   ```
   **绝不手工编辑 `.meta` 的内容**，只改名。

2. **行为绝对不变**。这是类型迁移，不是重构：
   - 保留 `cc.Class({...})`、`var`、`function`、回调写法；**不要**改成 `class` / `@ccclass` /
     `let` / `const` / 箭头函数。Creator 2.4 的构建链与场景绑定都按老写法工作。
   - 不"顺手修 bug"、不改日志、不改函数名/事件名/字符串字面量、不调换语句顺序、不改拼写错误
     （`startHearbeat`、`setFitSreenMode`、`dissoveData`、`cc.vv.mahjongmgr` 全小写等都要保留）。
   - 保留原有中文注释；新增注释也用中文。
   - 不要为了好写类型而**补初始值**：老代码靠"字段不存在"表达状态，补值会改行为。

3. **每个文件末尾加一行 `export { };`**。这不是可选项：
   - 没有 `import`/`export` 的文件在 TS 眼里是**全局脚本**，46 个文件顶层会互相撞名；
   - 加了它文件变成模块，顶层 `var`/`function` 各自独立。
   Creator 的模块加载器只在「模块没有任何**可枚举**导出」时才把 `cc.Class` 的类设为
   `module.exports`（见引擎 `_RF.pop()`），而 `export { }` 只产生一个不可枚举的 `__esModule`，
   所以 `require("Foo")` 依旧返回那个类——这一点不要改成 `export default`。

4. **不引入 `any`**。门禁会机械扫描 `: any`、`as any`、`<any>`、`@ts-ignore`、`@ts-expect-error`。
   按优先级选择：
   1. 精确类型（首选）；
   2. `unknown` + 收窄；
   3. 结构类型（`Record<string, unknown>`、联合类型）；
   4. 跨动态边界（网络载荷、`require` 的返回值、Creator 序列化字段）用一次**带注释的断言**，
      例如 `var push = data as GameSeatPush;`；
   5. 老代码本来就没判空的地方，用非空断言 `!`（如 `this.seats![i]`）而不是加 `if` 判断——
      `!` 是可擦除语法，不产生运行时代码，行为不变。

5. **`cc.Class` 的 `this` 怎么来的**（`types/cc-class.d.ts`）：
   - `properties` 里的成员会被自动摊平到 `this` 上；
   - 简写属性要标注类型：`foo: null as cc.Node | null`；
   - 完整写法 `foo: { default: null as cc.Sprite | null, type: cc.Sprite }` 会让 `this.foo` 取到
     `cc.Sprite | null`；
   - 带 `statics` 的类（如 `Net.js`）里，静态方法里的 `this` 其实是类本身，
     在该方法上手写 `this: XXXStatics` 显式声明；
   - **动态挂载、不在 `properties` 里的字段**（老代码直接 `this.conf = ...`）：
     在 options 里写一行 `conf: undefined as GameConf | null | undefined,` 并在注释里说明
     "运行时动态字段，没有补初始值"。prototype 上的值仍是 `undefined`，与"字段不存在"等价。

6. **网络边界**：`cc.vv.net.addHandler(event, function (data) {...})` 的 `data` 是 `unknown`
   （`Net.js` 已对字符串载荷做过 `JSON.parse`）。回调第一句把它断言成
   `repo:client/types/domain.d.ts` 里的推送类型，例如
   ```ts
   cc.vv.net.addHandler("user_state_push", function (data) {
       var push = data as UserStatePush;
       ...
   });
   ```
   裸载荷（数字、数组、字符串）也一样：`self.numOfGames = data as number;`。

7. **共享类型集中在 `client/types/`，改动要有理由**：
   - `creator.d.ts` 里漏掉/写错的引擎成员，补进 `cc-augment.d.ts`（一律用 `interface` / `var` /
     `function`，因为同一成员可能被多段声明合并，而 `let` / `class` 重复声明会直接报重复标识符）；
   - 本项目运行期**动态挂在节点上的自定义字段**（例如牌节点上的 `mjId`）也补在 `cc-augment.d.ts`，
     并在注释里写明"不是 Creator 的序列化属性"；
   - `cc.vv` 上单例的成员改 `cc-vv.d.ts`，网络载荷与对局结构改 `domain.d.ts`；
   - 只在本文件用到的结构，直接在该 `.ts` 里声明局部 `interface`，不要往共享文件里塞。
   补声明时优先用**断言收口调用点**而不是放宽共享类型：共享类型一旦放宽，所有调用点都会失去检查。

---

## 3. 怎么验证

```bash
# 类型（只检查已经改成 .ts 的文件；.js 文件此时还不参与）
server/node_modules/.bin/tsc --noEmit -p client/tsconfig.json

# 语法（.ts 走 Node 内置类型擦除，顺带强制"只用可擦除语法"）
npm run check:syntax

# 网络事件名一致性（改到事件名时必须跑）
npm run check:protocol
```

`npm run verify` 的六项门禁是最终判据；其中 `types` 项在客户端迁移完成后会同时审计
`client/` 的 no-any 并跑一次 `tsc --noEmit`。

**关于运行时验证**：客户端无法在本仓库里无头编译或运行。语法与类型能离线验证，
但「Creator 里能正常打开场景、牌局能正常跑」只能人工在编辑器里确认，
交付说明里要写清楚**哪些路径没有验证**，不要把"看起来对"说成"已验证"。

---

## 4. 类型放在哪、往哪找

| 需要的类型 | 位置 |
| --- | --- |
| `cc.vv.*` 各单例的成员 | `types/cc-vv.d.ts` |
| 网络推送/HTTP 响应/座位/配置/战绩 | `types/domain.d.ts` |
| `cc.Class`、`cc.Node` 等引擎侧补丁 | `types/cc-class.d.ts`、`types/cc-augment.d.ts` |
| `require`、`window.io`、socket.io | `types/globals.d.ts` |
| 只在本文件用到的结构 | 直接在该 `.ts` 里 `interface Xxx {...}`（模块内可见，不外泄） |
