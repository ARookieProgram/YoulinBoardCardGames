# 客户端 TypeScript 迁移手册（`client/`）

本文件是 `repo:client/` 客户端源码的统一约定，配套的类型基础在 `repo:client/types/`。
**硬要求与服务端迁移一致：严格类型、尽量不用 `any`、运行时行为绝对不变。**

客户端经历过两次"行为不变"的迁移，本文件按迁移后的写法写：

| 阶段 | 从 | 到 | 一句话 |
| --- | --- | --- | --- |
| ① 语言迁移 | ES5 `.js` | TypeScript `.ts` | 逐字搬迁 + 补类型标注；`foo.js`/`foo.js.meta` 同步改名 |
| ② 类声明迁移 | `cc.Class({...})` | ES6 `class` + `@ccclass` / `@property` | 只换类声明写法，property 元数据逐项不变 |

> 服务端迁移的对应规范见 `repo:docs/ai-native/typescript-migration.md`；客户端这一侧的差异
> （Creator 的脚本模块机制、`cc._decorator`、`.meta`）集中写在这里。

---

## 1. Creator 2.4.15 到底怎么编译项目脚本

**没有构建步骤**：`.ts` 由 Creator 自己编译，`client/tsconfig.json` 既服务 `tsc --noEmit`，
也决定 Creator 自己那次编译的选项。编译产物在 `client/temp/quick-scripts/`（gitignore，
不要提交），那里能看到每个脚本被包进一个模块壳：

```js
cc._RF.push(module, '6edb3jjx+FBepS1mk1xKDF2', 'Hall');
...
cc._RF.pop();
```

**实际转译器是 TypeScript，不是 Babel**——`temp/quick-scripts/dst/assets/scripts/*.js` 里是
`tsc` 的产物：装饰器编译成 `var __decorate = ...` 辅助函数，`class` / `let` 原样保留
（对应 `tsconfig.json` 的 `target: es6`），`export default class X` 编译成
`Object.defineProperty(exports, "__esModule", …)` + `exports.default = X`。
编辑器里另有一份 quick-compile 的 Babel 配置
（`app.asar.unpacked/editor/share/quick-compile/plugins/babel.js`：`preset-env` +
legacy 装饰器 + `class-properties` + `preset-typescript` + `babel-plugin-add-module-exports`），
**两条管线的模块互操作并不一致**，所以导出必须按下面第 3 条写成管线无关的形式。

由此得到三条可以直接依赖的事实：

1. `class`、装饰器、`let` / `const`、箭头函数都能用，**不需要**为客户端引打包器；
2. `@property` 写在类字段上时，初值来自**字段初始化器**（Babel 走 `desc.initializer` 分支，
   `tsc` 走 `extractActualDefaultValues` 分支，两条路取到的默认值一致）；
3. **`require("Foo")` 返回的是 `module.exports`，不是 `exports.default`**——所以每个类文件都要
   显式 `module.exports = Foo;`（见 §2 第 3 条）。这一点踩过坑：`export default` 在 `tsc` 下
   只会写 `exports.default`，`new (require("UserMgr"))()` 会直接抛
   `UserMgr is not a constructor`；老写法之所以没事，是靠 `cc._RF.pop()` 在「模块没有可枚举导出」
   时把 `cc.Class` 的类设成 `module.exports`（引擎
   `cocos2d/core/platform/requiring-frame.js`），换成 `export default` 后这条自动导出不再触发。

### 1.1 `@ccclass` 与老的 `cc.Class` 是同一套机制

引擎 `cocos2d/core/platform/CCClassDecorator.js` 里，`@ccclass` 内部调用的就是
`cc.Class(proto)`（带 `__ES6__: true`），随后 `define()` 照旧：

- 类名取 `cc._RF.peek().script`（= **脚本名**），所以 `node.addComponent("OnBack")`、
  `getComponent("ImageLoader")` 这类按名字查找照常工作；
- 用模块的 `frame.uuid` 调 `js._setClassId(uuid, cls)`，所以 `.fire` / `.prefab` 里按脚本
  uuid 引用组件的部分照常工作；
- `@property` 的结果写进 `__ccclassCache__`，由 `genProperty` 生成与老 `properties`
  完全相同的属性元数据（`type` / `default` / `serializable` …）。

**推论：`@ccclass` 不要写类名。** 传名字会触发引擎告警（`cc.errorID(3616)`），而且项目组件的
注册名本来就该由脚本名决定。

---

## 2. 逐条规矩

1. **结构只换写法，不顺手重构**。`class` 之外的一切保持原样：
   - 方法体里继续用 `var` / `function` / 回调（与服务端迁移同一风格），
     **不要**把 `var` 改成 `let`/`const`、不要把回调改成箭头函数；
   - 不"顺手修 bug"、不改日志、不改函数名/事件名/字符串字面量、不调换语句顺序、不改拼写错误
     （`startHearbeat`、`setFitSreenMode`、`dissoveData`、`cc.vv.mahjongmgr` 全小写等都要保留）；
   - 保留原有中文注释；新增注释也用中文。注释里已经不适用的部分（例如"这里用一次断言把类型
     标成实例类型"，改成 `@property` 后不再需要）要顺手改成与新写法一致的说明。

2. **`properties` 每一项对应一个 `@property` 字段，名称 / 默认值 / 类型三者都不能变**。
   默认值写在**字段初始化器**里（不要写进描述符的 `default`）：

   | 老写法（`cc.Class` 的 `properties` 里） | 新写法（类字段） |
   | --- | --- |
   | `foo: cc.Node` | `@property(cc.Node) foo: cc.Node \| null = null;` |
   | `foo: cc.SpriteAtlas as unknown as cc.SpriteAtlas` | `@property({type: cc.SpriteAtlas}) foo: cc.SpriteAtlas = null as unknown as cc.SpriteAtlas;` |
   | `foo: { default: X, type: cc.Prefab }` | `@property({type: cc.Prefab}) foo: T = X;` |
   | `foo: { default: [] as cc.Label[], type: [cc.Label] }` | `@property({type: [cc.Label]}) foo: cc.Label[] = [];` |
   | `foo: 0` / `false` / `''` | `@property foo: number = 0;`（`boolean` / `string` 同理） |
   | `foo: null as T \| null` | `@property foo: T \| null = null;` |

   老写法里的**简写**（值就是类型构造器）会被引擎规范化：
   `getFullFormOfProperty(cc.Node)` → `{_short: true, default: null, type: cc.Node}`
   （见引擎 `preprocess-class.js`）。所以 `@property(cc.Node)` 配 `= null` 与老代码逐项等价。
   **不要**把老 `properties` 里没有的字段补成 `@property`——那会凭空多出序列化元数据，
   场景一保存就会把新字段写进 `.fire`。

3. **模块导出契约：每个类文件末尾必须有 `module.exports = <类名>;`**。
   Creator 的 `require("X")` 返回的是 **`module.exports`**（`__quick_compile__.js` 里
   `require` 的最后一行就是 `return requestModule.module.exports`），而 `export default class X`
   经 `tsc`（`module: commonjs`）只编译成 `exports.default = X`——于是
   `new (require("UserMgr"))()` 会抛 `UserMgr is not a constructor`：

   ```ts
   @ccclass
   export default class UserMgr extends cc.Component { /* ... */ }

   // Creator 的 require(name) 取的是 module.exports；老写法靠 cc._RF.pop() 自动导出 cc.Class 的类，
   // export default 只会写成 exports.default，所以这里显式把类赋给 module.exports。
   module.exports = UserMgr;
   ```

   `module` 由模块壳 `__define(exports, require, module)` 传进来，声明在
   `types/globals.d.ts`。`types` 门禁会检查「有 `export default class X` 就必须有
   `module.exports = X;`」，缺了直接失败（`tsc` 与语法检查都看不出这个问题）。
   `HTTP.ts` 是唯一没有类的模块（纯 CommonJS `exports.x` 写法），不适用这条。

4. **动态字段用 `declare`**。老代码直接 `this.conf = ...` 而不在 `properties` 里的字段，
   迁移时曾用 `conf: undefined as GameConf | null | undefined` 这种 options 字段骗过类型检查；
   现在写：

   ```ts
   // 运行时动态字段（不是 Creator 的序列化属性），declare 只声明类型、不产生运行时代码。
   declare conf: GameConf | null | undefined;
   ```

   `declare` 字段被 `preset-typescript`（`allowDeclareFields: true`）整体删除，与"字段不存在"
   完全一致——**不要**给它补初始值，那会改行为。

5. **带断言的函数字段**。个别方法的签名与共享接口不一致（例如
   `getSpriteFrameByMJID` 会隐式返回 `undefined`，接口声明的是 `cc.SpriteFrame`），
   老写法用 `(function (...) {...}) as (...) => cc.SpriteFrame` 收口。类方法挂不了 `as`，
   所以这类方法写成**类字段**：

   ```ts
   // 调用方式与运行期行为不变（函数挂在实例上），只是把断言保留下来。
   getSpriteFrameByMJID = (function (this: MahjongMgr, pre: string, mjid: Pai) {
       ...
   }) as (pre: string, mjid: Pai) => cc.SpriteFrame;
   ```

6. **生命周期 `update` 写成 `update(dt: number = 0)`**。`creator.d.ts` 把
   `cc.Component.update` 误声明成无参方法，可选形参才能通过重写检查；引擎每帧调用时总会传 dt。
   同理由的还有 `lateUpdate`，本项目暂时没用到。

7. **不引入 `any`**。门禁会机械扫描 `: any`、`as any`、`<any>`、`@ts-ignore`、`@ts-expect-error`。
   按优先级选择：
   1. 精确类型（首选）；
   2. `unknown` + 收窄；
   3. 结构类型（`Record<string, unknown>`、联合类型）；
   4. 跨动态边界（网络载荷、`require` 的返回值、Creator 序列化字段）用一次**带注释的断言**，
      例如 `var push = data as GameSeatPush;`；
   5. 老代码本来就没判空的地方，用非空断言 `!`（如 `this.seats![i]`）而不是加 `if` 判断——
      `!` 是可擦除语法，不产生运行时代码，行为不变。

8. **网络边界**：`cc.vv.net.addHandler(event, function (data) {...})` 的 `data` 是 `unknown`
   （`Net.ts` 已对字符串载荷做过 `JSON.parse`）。回调第一句把它断言成
   `repo:client/types/domain.d.ts` 里的推送类型，例如
   ```ts
   cc.vv.net.addHandler("user_state_push", function (data) {
       var push = data as UserStatePush;
       ...
   });
   ```
   裸载荷（数字、数组、字符串）也一样：`self.numOfGames = data as number;`。
   `Net.ts` 里 `sio.on('<event>', ...)` 的写法**不要改成 `sio!.on(`**：`protocol` 检查器按
   正则收集客户端事件名，多了个 `!` 就会漏掉 `game_pong`。

9. **共享类型集中在 `client/types/`，改动要有理由**：
   - `creator.d.ts` 里漏掉/写错的引擎成员，补进 `cc-augment.d.ts`（一律用 `interface` / `var` /
     `function`，因为同一成员可能被多段声明合并，而 `let` / `class` 重复声明会直接报重复标识符）；
     `cc._decorator`（`ccclass` / `property`）的声明也在那里——`creator.d.ts` 完全没有它；
   - 本项目运行期**动态挂在节点上的自定义字段**（例如牌节点上的 `mjId`）也补在 `cc-augment.d.ts`，
     并在注释里写明"不是 Creator 的序列化属性"；
   - `cc.vv` 上单例的成员改 `cc-vv.d.ts`，网络载荷与对局结构改 `domain.d.ts`；
   - 只在本文件用到的结构，直接在该 `.ts` 里声明局部 `interface`，不要往共享文件里塞。
   补声明时优先用**断言收口调用点**而不是放宽共享类型：共享类型一旦放宽，所有调用点都会失去检查。

10. **改文件名（含 `.js` → `.ts`）时必须同步改 `.meta` 并保留 `uuid`**：
   ```bash
   mv assets/scripts/Foo.js assets/scripts/Foo.ts        # 先写好 Foo.ts 再删也行
   mv assets/scripts/Foo.js.meta assets/scripts/Foo.ts.meta
   ```
   改名用普通 `mv`（不要 `git mv`，避免并行作业抢 git index 锁）；
   **绝不手工编辑 `.meta` 的内容**——场景 `.fire` 用 uuid 引用脚本组件，uuid 变了场景就断了。

---

## 3. 怎么验证

```bash
# 必须：语法（80 个一方脚本：client 47 + server 33；.ts 走 Node 内置类型擦除，顺带强制可擦除语法）
npm run check:syntax

# 必须：类型（strict，用 server/node_modules/typescript，客户端不额外引依赖）
server/node_modules/.bin/tsc --noEmit -p client/tsconfig.json

# 必须：若改了任何网络事件名或新增事件
npm run check:protocol

# 全绿才算改完（含上面三项，另有 harness / smoke / selftest）
npm run verify
```

`tsc` 是这次类声明迁移最重要的离线保障：属性名写错、默认值类型不匹配、`@property` 少写类型
都会在这里报出来。`npm run verify` 的 `types` 项还会在 `client/` 一方源码里查残留的
`cc.Class(`——写回去就是门禁失败，不需要靠人眼盯。
**property 元数据等价**另有一道人工核对手段——把老文件的 `properties`
逐项与新文件的 `@property` 对照（名称、默认值、类型），确认一一对应、没有多也没有少。

**关于运行时验证**：客户端无法在本仓库里无头编译或运行。语法与类型能离线验证，
但「Creator 里能正常打开场景、牌局能正常跑」只能人工在编辑器里确认，
交付说明里要写清楚**哪些路径没有验证**，不要把"看起来对"说成"已验证"。

---

## 4. 类型放在哪、往哪找

| 需要的类型 | 位置 |
| --- | --- |
| `cc.vv.*` 各单例的成员 | `types/cc-vv.d.ts` |
| 网络推送/HTTP 响应/座位/配置/战绩 | `types/domain.d.ts` |
| `cc._decorator`、`cc.Node` 等引擎侧补丁 | `types/cc-augment.d.ts` |
| `require`、`window.io`、socket.io | `types/globals.d.ts` |
| 只在本文件用到的结构 | 直接在该 `.ts` 里 `interface Xxx {...}`（模块内可见，不外泄） |
