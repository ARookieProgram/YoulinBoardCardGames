# 玩法规格（四川麻将 · 血战到底）

本文说明本实现中**玩法逻辑的落点与编码约定**。业务规则细节（每种番型的定义）以
`repo:server/game_server/gamemgr_xlch.ts` 内的实现为准——本文不复制番型表，只讲清楚
"逻辑在哪、数据长什么样、改哪里会连带改什么"。

---

## 1. 两套并行实现

| 实现 | `conf.type` | 文件 | 行数 |
| --- | --- | --- | --- |
| 血战到底 | `"xlch"` | `repo:server/game_server/gamemgr_xlch.ts` | 2488 |
| 另一玩法 | 其他值（客户端用 `"xzdd"`） | `repo:server/game_server/gamemgr_xzdd.ts` | 2510 |

选择点在 `repo:server/game_server/roommgr.ts`：两处调用点都走同一个懒加载助手
`loadGameManager(type)`（`:61`）。**变量不同名**：`:216` 新建房间读入参 `roomConf.type`；
`:83` 从数据库恢复房间读已落库的 `conf.type`。
**漏改第二处会导致服务器重启后房间行为漂移。**

两份文件约 **86%** 的行逐行相同（`difflib` ratio 0.864），定位真实分歧：

```bash
cd server/game_server
diff <(sed 's/[[:space:]]//g' gamemgr_xlch.ts) <(sed 's/[[:space:]]//g' gamemgr_xzdd.ts)
```

---

## 2. 牌的编码

牌是 **0–26 的整数**，顺序 筒 → 条 → 万：

| 值 | 花色 | 牌 |
| --- | --- | --- |
| `0–8` | 筒 | 1筒 – 9筒 |
| `9–17` | 条 | 1条 – 9条 |
| `18–26` | 万 | 1万 – 9万 |

`getMJType(pai)` 返回花色编号 `0/1/2`。**该函数存在三份拷贝**：

1. `repo:server/game_server/mjutils.ts` —— 导出为 `export function getMJType`
2. `repo:server/game_server/gamemgr_xlch.ts` —— 本地 `function getMJType(id)`
3. `repo:server/game_server/gamemgr_xzdd.ts` —— 本地 `function getMJType(id)`

> 2026-09 修复记录：`mjutils.ts` 里的导出曾误写为读取未定义变量 `id`（形参名是 `pai`），
> 调用即抛 `ReferenceError`。由于没有任何调用方，这个缺陷长期未被发现；
> 现已修正，并由 `npm run check:smoke` 的 `getMJType` 三条断言（筒/条/万边界）守住。
> **改动花色边界时三处都要改。**

---

## 3. 座位数据 `seatData`

| 字段 | 含义 |
| --- | --- |
| `holds` | 手牌（牌 id 数组） |
| `countMap` | 牌 id → 张数（听牌判定的核心索引） |
| `tingMap` | 牌 id → `{pattern, fan}`（听牌结果） |
| `pengs` | 碰 |
| `angangs` / `diangangs` / `wangangs` | 暗杠 / 点杠 / 弯杠 |
| `folds` | 牌河 |
| `que` | 定缺的花色 |
| `hued` | 是否已胡（血战到底中一人可继续打，故需此标记） |
| `huanpais` / `huanpaimethod` | 换三张的牌与方法 |

---

## 4. 听牌 / 胡牌判定

实现在 `repo:server/game_server/mjutils.ts`（304 行，**纯算术、无 IO**，因此可离线测试）。

```
checkTingPai(seatData, begin, end)     ← 唯一导出的入口
  └─ 对 [begin, end) 每张牌：加入 → checkCanHu → 写入 tingMap → 撤销
       └─ checkCanHu(seatData)         ← 内部函数，未导出
            └─ 枚举将牌（countMap ≥ 2），扣一对 → checkSingle 验证 3N 规则
```

约定与陷阱：

- **调用方传入 13 张手牌**（等第 14 张）。分三次按花色调用：`(0,9)`、`(9,18)`、`(18,27)`。
- `checkTingPai` 会**原地修改再回滚** `countMap` 与 `holds`，因此 `seatData` 必须是结构完整的对象
  （最小替身：`{holds, countMap, tingMap}`，见 `repo:tools/lib/smoke.mjs` 的 `buildSeat`）。
- **七对（七小对）本引擎不认。** `checkCanHu` 只枚举将牌再验证 3N（刻子/顺子），
  没有"全偶数即胡"的分支。实测 6 对 + 1 张单牌（等第 7 对）返回空 `tingMap`。
  要支持七对是一条**新特性**，不是修 bug。
- `checkCanHu` 命中时**没有显式 `return false` 的兜底分支**（隐式返回 `undefined`），
  调用方一律按真假值判断，不要改成严格比较。

离线证据：

```bash
npm run check:smoke
```

现有 19 条断言覆盖：单钓将、四刻子后的将牌、两个相同顺子 + 将牌的组合、散牌不报听、
**七对不被识别（把当前限制钉住）**、`getMJType` 花色边界、`md5`、Base64 往返（含中文昵称），
以及 `String.prototype.format` 的三种形态与 `http.queryString` / `queryInt` 的返回契约。
改判定逻辑必须同步更新断言。

---

## 5. 动作记录与回放兼容

```js
var ACTION_CHUPAI = 1;   // 出牌
var ACTION_MOPAI  = 2;   // 摸牌
var ACTION_PENG   = 3;   // 碰
var ACTION_GANG   = 4;   // 杠
var ACTION_HU     = 5;   // 胡（点炮）
var ACTION_ZIMO   = 6;   // 自摸
```

动作序列写入 `t_games.action_records`（`varchar(2048)`），回放时按这些常量解释。

> **两个兼容性红线**：① 常量值只能追加，不能修改或复用；② 单局动作序列不能超过 2048 字节，
> 超长会被静默截断，导致回放不完整。

---

## 6. 房间配置

配置分两层，对局逻辑只认落库那一层：

| 层 | 字段 |
| --- | --- |
| 入参 `roomConf`（`CreateRoom.js` 提交） | `type`、`difen`、`zimo`、`jiangdui`、`huansanzhang`、`zuidafanshu`、`jushuxuanze`、`dianganghua`、`menqing`、`tiandihu` |
| 落库 `conf`（`t_rooms.base_info`） | `type`、`baseScore`、`zimo`、`jiangdui`、`hsz`、`dianganghua`、`menqing`、`tiandihu`、`maxFan`、`maxGames`、`creator` |

映射：`difen → DI_FEN[1,2,5]`、`zuidafanshu → MAX_FAN[3,4,5]`、`jushuxuanze → JU_SHU[4,8]`、
`huansanzhang → hsz`。`createRoom` 会校验入参非空，缺项直接 `callback(1, null)` 建房失败。

---

## 7. 相关文档与技能

- 服务端架构与协议：`repo:.dsh/skills/server-architecture/SKILL.md`
- 玩法改动流程：`repo:.dsh/skills/game-rules/SKILL.md`
- 客户端侧的表现层：`repo:docs/ai-native/client-map.md`
- 事件清单：`repo:docs/ai-native/protocol.md`
