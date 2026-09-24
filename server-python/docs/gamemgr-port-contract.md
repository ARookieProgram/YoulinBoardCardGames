# gamemgr 移植契约（game_server/gamemgr_xlch.py · gamemgr_xzdd.py）

本文是 `server/game_server/gamemgr_xlch.ts` 与 `gamemgr_xzdd.ts` 移植到 Python 时必须遵守的
接口与保真规则。两份实现共享同一份契约，**只有各自的 TS 源文件不同**。

## 0. 铁律

1. **逐行翻译，不要重构、不要"顺手优化"、不要合并重复代码。**
   目标产物是"读起来能跟 TS 源码一行行对上"的 Python。
   两份 gamemgr 有 86% 的行是相同的，这个重复是**故意保留**的
   （见根 `AGENTS.md` §3.1：改玩法必须两份同步，合并成一份会让这条约定失效）。
2. **不要修改本模块以外的任何文件。** 缺工具函数就在本模块里写局部函数，并在汇报里说明。
3. 注释一律用中文。关键分支要保留原 TS 的注释含义（尤其是标着"历史 bug / 移植不修"的地方）。
4. 函数体里可以自由使用 `if/for/while`，但**不要**把 `var` 风格的多步流程塞进推导式——
   可读性和"能对上原文"优先于 Python 味。

## 1. 模块骨架

```python
"""血战到底玩法实现（`conf.type == "xlch"` 时由 `roommgr` 懒加载这一份）。"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from shared.domain import GameSeat, GameState, RoomInfo, TingPaiInfo
from utils import crypto, db
from utils.jscompat import (
    js_index_of, js_keys, js_parse_int, js_pop, js_random_index, js_str, now_ms, splice,
)
from game_server import mjutils, roommgr, usermgr

# ---- 模块级状态（与 TS 一一对应）----
_games: dict[str, GameState] = {}
_games_id_base = 0

ACTION_CHUPAI = 1
ACTION_MOPAI = 2
ACTION_PENG = 3
ACTION_GANG = 4
ACTION_HU = 5
ACTION_ZIMO = 6

_game_seats_of_users: dict[int, GameSeat] = {}

# ---- 内部函数（对应 TS 里的非导出 function）----
# get_mj_type / shuffle / mopai / deal / check_can_peng / check_can_dian_gang /
# check_can_an_gang / check_can_wan_gang / check_can_hu / clear_all_options /
# check_can_ting_pai / get_seat_index / get_game_by_user_id / has_operations /
# send_operations / move_to_next_user / do_user_mo_pai / is_same_type / is_qing_yi_se /
# is_men_qing / is_zhong_zhang / is_jiang_dui / is_tinged / compute_fan_score /
# need_cha_da_jiao / find_max_fan_ting_pai / find_un_tinged_players / get_num_of_gen /
# cha_jiao / calculate_result / do_game_over / record_user_action / record_game_action /
# store_single_history / store_history / construct_game_base_info / store_game /
# check_can_qiang_gang / do_gang / _update / _update_loop

# ---- 对外接口（roommgr.GameManagerProtocol 要求，名字必须一致）----
async def set_ready(user_id: int, callback: Any = None) -> None: ...
async def begin(room_id: str) -> None: ...
async def huan_san_zhang(user_id: int, p1: int, p2: int, p3: int) -> None: ...
async def ding_que(user_id: int, type: int) -> None: ...
async def chu_pai(user_id: int, pai: int) -> None: ...
async def peng(user_id: int) -> None: ...
def is_playing(user_id: int) -> bool: ...
async def gang(user_id: int, pai: int) -> None: ...
async def hu(user_id: int) -> None: ...
async def guo(user_id: int) -> None: ...
def has_began(room_id: str) -> bool: ...
async def do_dissolve(room_id: str) -> None: ...
def dissolve_request(room_id: str, user_id: int) -> RoomInfo | None: ...
def dissolve_agree(room_id: str, user_id: int, agree: bool) -> RoomInfo | None: ...

# ---- 定时器 ----
async def _update() -> None: ...          # 对应 TS 末尾的 function update()
async def _update_loop() -> None: ...
try:
    asyncio.get_running_loop().create_task(_update_loop())
except RuntimeError:
    pass   # 没有事件循环时（同步 import）不起定时器
```

**定时器只在模块被 import 时起一次**，这正是 `roommgr.load_game_manager` 必须懒加载的原因。

## 2. 可用的外部 API（都已存在，直接调用）

### roommgr（同步）

```python
roommgr.get_user_room(user_id) -> str | None
roommgr.get_user_seat(user_id) -> int | None
roommgr.get_room(room_id) -> RoomInfo | None
roommgr.set_ready(user_id, value: bool) -> None
roommgr.is_creator(room_id, user_id) -> bool
roommgr.destroy(room_id) -> Awaitable[None]          # 要 await
```
（注意 `roommgr.get_user_locations()` 也存在，但 gamemgr 用不到。）

### usermgr（**全部是协程，要 await**）

```python
await usermgr.send_msg(user_id, event, data=None)          # data 必传；无载荷传 None
await usermgr.broacast_in_room(event, data, sender, including_sender=False)
await usermgr.kick_all_in_room(room_id)
usermgr.is_online(user_id) -> bool
```

`send_msg(uid, event, None)` 在线上是 `42["event",null]`，与 TS 的
`sendMsg(uid, event, undefined)` 完全一致。事件名保持字符串字面量。

### db（**全部是协程，要 await**）

```python
await db.user_exists(...)                       # 不存在，用下面这些
await db.get_user_history(user_id)              -> list | None
await db.update_user_history(user_id, history)  -> bool
await db.create_game(room_uuid, index, base_info) -> int | None
await db.update_game_result(room_uuid, index, result) -> bool
await db.update_game_action_records(room_uuid, index, actions) -> bool
await db.update_num_of_turns(room_id, num_of_turns) -> bool
await db.update_next_button(room_id, next_button) -> bool
await db.cost_gems(user_id, cost) -> bool
await db.archive_games(room_uuid) -> bool
```
`utils/db.py` 里还有别的函数；**只允许用上面这些 + 该文件里确实存在的**，
不要自己拼 SQL。

### mjutils（同步，纯逻辑）

```python
mjutils.check_ting_pai(seat_data, begin, end) -> None   # 结果写进 seat_data.tingMap
mjutils.get_mj_type(pai) -> int | None
```

### crypto

```python
crypto.md5(content) -> str          # content 可以是任意类型，内部做 JS String() 转换
crypto.to_base64(content) -> str
crypto.from_base64(content) -> str
```

### jscompat（保真助手，见文件里的文档注释）

```python
js_keys(mapping) -> list        # JS for...in 的键顺序（整数键升序）——遍历 countMap/tingMap 必须用它
splice(arr, start, count=0)     # Array.prototype.splice（含负下标语义）
js_index_of(arr, value) -> int  # indexOf，找不到返回 -1
js_pop(arr)                     # pop()，空数组返回 None
js_random_index(n)              # Math.floor(Math.random() * n)
js_parse_int(value) -> float    # parseInt，失败返回 NaN
js_str(value) -> str            # String(value)
now_ms() -> int                 # Date.now()
```

## 3. 保真规则（逐条都是坑）

| TS / JS 写法 | Python 写法 | 原因 |
| --- | --- | --- |
| `x == null` / `x != null` | `x is None` / `x is not None` | JS 的 `== null` 同时覆盖 null 与 undefined |
| 其它 `==` / `!=`（含与 `undefined` 比） | 原样用 `==` / `!=`，**不要用 `is`** | `undefined != -1` 在 JS 为 true，Python 里 `None != -1` 也为 true；用 `is` 就错了 |
| `for(var k in countMap)` | `for k in js_keys(countMap)` | JS 整数键**升序**枚举，Python dict 是插入序；顺序会影响 `gangPai`、`findMaxFanTingPai` 的结果 |
| `arr.splice(i,1)` | `splice(arr, i, 1)` | `splice(-1,1)` 删的是最后一个元素，`del arr[-1]` 恰好等价但 `del arr[-2]` 之类容易写错；统一用助手 |
| `arr.indexOf(x)` | `js_index_of(arr, x)` | `list.index` 找不到会抛异常 |
| `arr.pop()` | `js_pop(arr)` | 空数组 JS 返回 undefined |
| `Math.floor(Math.random()*n)` | `js_random_index(n)` | `n == 0` 时 JS 得 0 |
| `setTimeout(fn, ms)` | `_delay(ms, async_fn)`（见下） | — |
| `parseInt(x)` | `js_parse_int(x)` | 失败返回 NaN 而不是抛异常；返回值是 float，需要整数时 `int(...)` |
| `Date.now()` | `now_ms()` | — |

`setTimeout` 的对应写法（原实现里只出现在 `chuPai` 的 500ms 与 `doGameOver` 的 1500ms）：

```python
def _schedule(delay_ms: int, fn) -> None:
    """对应 JS 的 setTimeout；fn 是无参协程函数。"""
    async def runner() -> None:
        await asyncio.sleep(delay_ms / 1000)
        await fn()
    asyncio.get_running_loop().create_task(runner())
```

调用点写 `_schedule(500, on_later)`，其中 `on_later` 是无参 `async def`，
闭包变量按原 TS 一致地捕获。

### 3.1 上线载荷必须是普通 dict

`JSON.stringify` 会**丢掉值为 `undefined` 的键、保留 `null`**。所以：

* 发到客户端的东西（`huInfo` 的元素、`game_over_push` 的 results、`game_sync_push` 的 seats…）
  一律用**普通 dict**，按需增删键，不要用 dataclass；
* `GameSeat.huInfo` / `GameSeat.actions` 在 Python 里就是 `list[dict]`。

例：`chaJiao` 里 TS 是

```js
ts.huInfo.push({ ishupai:true, action:"chadajiao", fan:cur.fan, pattern:cur.pattern,
                 pai:cur.pai, numofgen:getNumOfGen(ts) });
```

Python 就写

```python
ts.huInfo.append({
    "ishupai": True, "action": "chadajiao", "fan": cur.fan,
    "pattern": cur.pattern, "pai": cur.pai, "numofgen": get_num_of_gen(ts),
})
```

### 3.2 `game.lastFangGangSeat` 这个字段不存在

`hu()` 里有一段

```js
var lp = (game.lastFangGangSeat! - game.turn + 4) % 4;
var cur = (seatData.seatIndex - game.turn + 4) % 4;
if(cur > lp){ game.lastHuPaiSeat = seatData.seatIndex; }
```

`game.lastFangGangSeat` **全仓库没有任何地方写入**，运行时是 `undefined`，
`(undefined - n + 4) % 4` 是 `NaN`，`cur > NaN` 恒为 false。
Python 侧不要建这个字段，直接把这段写成"该分支恒不成立"：

```python
# 原实现读的是 game.lastFangGangSeat——一个从未被写入的字段，结果是 NaN，
# `cur > lp` 恒为 false。这里如实写出"不赋值"，不要凭空造一个字段。
```

注意 `GameSeat.lastFangGangSeat` 是**真实存在**的字段（`begin` 里初始化成 -1，`doGang` 里写），
不要混淆。

### 3.3 其它必须保留的历史行为

* `sendOperations` 里 `data.si = seatData.seatIndex` 写在 `sendMsg` **之后**，
  所以 `si` 从来没被发出去——保留这个死赋值并加注释；
* `checkCanQiangGang` 里 `game.qiangGangContext` 的赋值语句**结尾没有分号**（ASI），
  语义就是在那个分支里赋值，照抄语义即可；
* `doGameOver` 里 `db.cost_gems` 的返回值被忽略；
* `update_game_result` 在 `room_uuid == null || result` 时的"先回调一次"在 Python 版里
  已经折算成"SQL 一定执行"，不用管；
* `gangPai` / `actions` 的**顺序**要对得上，所以 `for...in` 必须用 `js_keys`。

## 4. 与 Node 版有意的差异（写进模块 docstring）

1. 需要 IO 的函数改成 `async def` + `await`（Node 版是同步函数 + 回调 + `setTimeout`）。
2. 少数地方原本会 `throw` 崩进程（例如 `doGameOver` 里 `roomMgr.getRoom()` 取空后继续用），
   Python 版照原样写，异常会冒泡到调用它的协程；由 socket 处理器记录日志。
   **不要加防御性的判空返回来"修"它**——那会改变行为。
3. 模块级状态用下划线前缀的模块变量（`_games` 等），不改成类。

## 5. 自检

写完必须跑：

```bash
cd server-python
.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from game_server import gamemgr_xlch; print('ok')"
.venv/bin/python -m compileall -q game_server/gamemgr_xlch.py
```

（把 `xlch` 换成 `xzdd`。）
若还有时间，给 `ching` / `peng` / `hu` 之类纯函数写一两条临时断言验证，但**不要**新建仓库文件。
