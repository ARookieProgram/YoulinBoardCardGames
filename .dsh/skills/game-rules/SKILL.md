---
name: game-rules
description: How the Sichuan mahjong rules engine works in this codebase - tile encoding, ting/win detection, fan scoring, and the two parallel game managers that must be kept in sync. Use when changing gameplay, scoring, ting/hu logic, or the action flow.
---

# 麻将玩法引擎

四川麻将（血战到底 / 血战到底·换三张）。玩法逻辑分布在**两份必须同步的实现**里，
理解这一点比理解任何单个函数都重要。

## 什么时候用

- 改听牌/胡牌判定、番型、倍数、结算。
- 改定缺、换三张、碰杠、过胡等流程。
- 排查"某种牌型不算胡/算错番"。

## 1. 两处实现，一份逻辑

| 文件 | 玩法 | 选择条件 |
| --- | --- | --- |
| `repo:server/game_server/gamemgr_xlch.ts` | 血战到底 | `conf.type == "xlch"` |
| `repo:server/game_server/gamemgr_xzdd.ts` | 另一种玩法 | 其他所有值 |

由 `repo:server/game_server/roommgr.ts` 按落库的 `conf.type` 加载（两处调用点：读库恢复房间、
新建房间，都走同一个 `loadGameManager(type)` 懒加载助手）。两份文件各约 2500 行
（`gamemgr_xlch.ts` 2488 / `gamemgr_xzdd.ts` 2510），**约 86% 的行逐行相同**，差异集中在番型判定与流程分支。

> **动手前的固定动作**：改动先在 `xlch` 里写完，再 `diff` 到 `xzdd`，逐处确认是否同样适用。
> 只适用于一种玩法的，在提交说明里写明"仅 xlch/xzdd，因为……"。
> 用 `diff <(sed 's/[[:space:]]//g' gamemgr_xlch.ts) <(sed 's/[[:space:]]//g' gamemgr_xzdd.ts)`
> 可以快速看到两份的真实分歧。

## 2. 牌的编码

牌用 **0–26 的整数**表示，顺序是 筒 → 条 → 万：

| 区间 | 花色 | 例 |
| --- | --- | --- |
| `0–8` | 筒 | `0` = 1筒 … `8` = 9筒 |
| `9–17` | 条 | `9` = 1条 … `17` = 9条 |
| `18–26` | 万 | `18` = 1万 … `26` = 9万 |

花色判定：`getMJType(pai)` 返回 `0/1/2`。**注意这个函数有三份拷贝**——
`repo:server/game_server/mjutils.ts` 导出一份，两份 `gamemgr_*` 各有一个本地同名函数。
改花色边界必须三处一起改。

座位数据结构（`seatData`）的关键字段：

| 字段 | 含义 |
| --- | --- |
| `holds` | 手牌数组（牌 id） |
| `countMap` | 牌 id → 张数，听牌判定的核心索引 |
| `pengs` / `angangs` / `diangangs` / `wangangs` | 碰、暗杠、点杠、弯杠 |
| `folds` | 牌河 |
| `tingMap` | 牌 id → `{pattern, fan}`，听牌结果 |
| `que` | 定缺的花色 |
| `hued` | 是否已胡 |
| `huanpais` / `huanpaimethod` | 换三张的牌与方法 |

## 3. 听牌/胡牌判定

纯算术实现，位于 `repo:server/game_server/mjutils.ts`（304 行，无 IO 依赖）：

- `checkTingPai(seatData, begin, end)` —— 对 `[begin, end)` 区间的每张牌试加入 `holds`，
  能胡则写进 `seatData.tingMap`，然后**撤销**这张牌。调用方按花色分三次调用：
  `(0,9)` 筒、`(9,18)` 条、`(18,27)` 万。
- 内部 `checkCanHu(seatData)` 枚举将牌（`countMap` 中张数 ≥ 2 的牌），扣掉一对后对剩余牌跑
  `checkSingle`，验证是否满足 3N 规则（刻子 / 顺子）。**它没有导出**，只被 `checkTingPai` 使用。

**这个引擎不认七对（七小对）**——`checkCanHu` 没有"全偶数即胡"的分支。
实测：6 对 + 1 张单牌（等第 7 对）返回空 `tingMap`。
所以 `npm run check:smoke` 里的断言覆盖的是**单钓将、四刻子后的将牌、散牌不报听**，
不含七对；若哪天要支持七对，那是一条**新特性**，不是修 bug。

因为 `checkTingPai` 会原地修改再回滚 `countMap` 与 `holds`，**调用方传入的 `seatData` 必须是
真正的对局座位对象或结构完全一致的替身**（`{holds, countMap, tingMap}` 三件套）。
`repo:tools/lib/smoke.mjs` 的 `buildSeat()` 就是一个最小替身。

可离线验证，所以**改这里必须跑**：

```bash
npm run check:smoke
```

## 4. 动作与流程常量

```js
var ACTION_CHUPAI = 1;   // 出牌
var ACTION_MOPAI  = 2;   // 摸牌
var ACTION_PENG   = 3;   // 碰
var ACTION_GANG   = 4;   // 杠
var ACTION_HU     = 5;   // 胡（点炮）
var ACTION_ZIMO   = 6;   // 自摸
```

两份 `gamemgr_*` 的常量完全一致，且动作记录会写进 `t_games` 供回放使用——
**改动常量值会破坏历史回放数据**，只能追加新常量。

房间配置里的玩法开关（落库 `conf`，见 `repo:server/AGENTS.md` §4）：
`baseScore`（底分）、`zimo`、`jiangdui`、`hsz`（换三张）、`dianganghua`、`menqing`、
`tiandihu`、`maxFan`、`maxGames`。

## 5. 客户端对应物

客户端**不做规则计算**，只做展示与本地交互态。相关文件：

- `repo:client/assets/scripts/GameNetMgr.ts` —— 对局状态机（手牌、轮次、定缺、结算快照）。
- `repo:client/assets/scripts/components/MJGame.ts` —— 对局主控 UI（886 行）。
- `repo:client/assets/scripts/components/DingQue.ts`、`HuanSanZhang.ts`、`PengGangs.ts`、
  `Seat.ts` —— 定缺、换三张、碰杠胡按钮、座位渲染。

因此**改规则只动服务端**；只有当新增状态需要展示时才动客户端，并且要同步新增推送事件
（见 `repo:.dsh/skills/server-architecture/SKILL.md` 与 `repo:docs/ai-native/protocol.md`）。

## 6. 改动检查清单

1. 两份 `gamemgr_*` 是否都已处理？（或已说明为何只改一份）
2. 花色边界改动是否三处 `getMJType` 都同步？
3. `ACTION_*` 是否只追加、未改值？
4. `npm run verify` 是否全绿？（尤其 `check:smoke`）
5. 是否影响了历史回放（`t_games.action_records`）的兼容性？
