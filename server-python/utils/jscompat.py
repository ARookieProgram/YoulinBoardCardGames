"""JavaScript 语义的兼容助手。

这份移植的目标是**行为一致**，不是"用 Python 重写一遍玩法"。原实现里有若干
JavaScript 特有的语义，直接照搬成 Python 会悄悄改掉行为，所以集中在这里实现一次，
调用点只调用这些函数，不各自造轮子：

1. `js_str()`       —— `String(x)`，尤其是 `null -> "null"`、`NaN -> "NaN"`。
                       进房签名是字符串拼接，拼错了就是全员登录失败。
2. `js_parse_int()` —— `Number.parseInt(x, 10)`，失败返回 NaN 而不是抛异常。
3. `js_number()`    —— `Number(x)`，`"" -> 0`、`"abc" -> NaN`。
4. `js_keys()`      —— `for...in` 遍历对象键的顺序。**与 Python 的字典顺序不同**：
                       JavaScript 对"整数样式的键"一律按**数值升序**枚举，
                       而 Python dict 按插入顺序。两者顺序不同会让
                       `gangPai` / `findMaxFanTingPai` 的结果顺序变化，必须显式排序。
5. `splice()`       —— `Array.prototype.splice`，含**负下标**语义
                       （`splice(-1, 1)` 删的是最后一个元素，不是"删不掉"）。
6. `js_random_index()` —— `Math.floor(Math.random() * n)`，`n == 0` 时为 0。
"""

from __future__ import annotations

import math
import random
import re
from typing import Any, TypeVar

T = TypeVar("T")

#: JavaScript 的 `undefined`。`js_str(JS_UNDEFINED)` 得到 `"undefined"`。
#: 需要区分"没传"与"传了 null"的极少数地方会用到它。
JS_UNDEFINED = object()


def js_str(value: Any) -> str:
    """`String(value)` 的语义。

    * `None`（JS 的 `null`）-> `"null"`
    * `JS_UNDEFINED`（JS 的 `undefined`）-> `"undefined"`
    * `True` / `False` -> `"true"` / `"false"`（Python 的 `str(True)` 是 `"True"`，**不一样**）
    * 整数 -> 十进制；`nan` -> `"NaN"`
    * 浮点数 -> 去掉无意义的 `.0`（`1.0 -> "1"`），与 JS 的 Number 转字符串一致
    """
    if value is None:
        return "null"
    if value is JS_UNDEFINED:
        return "undefined"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer():
            return str(int(value))
        return repr(value)
    return str(value)


_LEADING_INT = re.compile(r"^[+-]?\d+")


def js_parse_int(value: Any) -> float:
    """`Number.parseInt(value, 10)` 的语义；无法解析时返回 `nan`。

    JS 会先 `String(value)` 再取前缀数字：`parseInt("12abc") == 12`、
    `parseInt("abc")` 是 `NaN`、`parseInt("")` 也是 `NaN`。
    """
    text = js_str(value).lstrip()
    match = _LEADING_INT.match(text)
    if match is None:
        return math.nan
    return float(int(match.group(0), 10))


def js_number(value: Any) -> float:
    """`Number(value)` 的语义。

    只覆盖本仓库真正用到的形态：数字原样返回、`None -> 0`、布尔转 0/1、
    空串 -> 0、数字字符串 -> 对应数值、其它字符串 -> `NaN`。
    `undefined`（`JS_UNDEFINED`）-> `NaN`。
    """
    if value is JS_UNDEFINED:
        return math.nan
    if value is None:
        return 0.0
    if value is True:
        return 1.0
    if value is False:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return math.nan


def js_keys(mapping: dict[Any, Any]) -> list[Any]:
    """按 JavaScript `for...in` 的顺序返回对象的键。

    JS 的对象把"整数样式的键"（`0`、`1`、`42`）排在前面并**按数值升序**枚举，
    其余键才按插入顺序。本仓库里需要这个顺序的只有 `countMap` / `tingMap`，
    它们的键全是牌 id（整数），所以直接升序排序即可。
    """
    try:
        return sorted(mapping)
    except TypeError:
        # 键类型混杂时退回插入顺序（本仓库不会走到这里）
        return list(mapping)


def splice(arr: list[T], start: int, delete_count: int = 0) -> list[T]:
    """`Array.prototype.splice(start, deleteCount)` 的等价实现（只取"删除"语义）。

    返回被删除的元素列表。负下标按 JS 规则换算：`splice(-1, 1)` 删除最后一个元素，
    下标越界时按 0 或 `len(arr)` 处理。**不要**用 `del arr[i]` 直接替换，
    `i == -1` 时两者行为完全不同。
    """
    length = len(arr)
    if start < 0:
        start = max(length + start, 0)
    elif start > length:
        start = length
    if delete_count < 0:
        delete_count = 0
    end = min(start + delete_count, length)
    removed = arr[start:end]
    del arr[start:end]
    return removed


def js_random_index(last_index: int) -> int:
    """`Math.floor(Math.random() * last_index)`。

    `last_index == 0` 时 JS 得到 0（洗牌循环的最后一次就是这种情形），
    Python 的 `random.randrange(0)` 会抛异常，因此不能直接替换。
    """
    return math.floor(random.random() * last_index)


def js_index_of(arr: list[Any], value: Any) -> int:
    """`Array.prototype.indexOf`：找不到返回 -1（Python 的 `list.index` 会抛异常）。"""
    try:
        return arr.index(value)
    except ValueError:
        return -1


def now_ms() -> int:
    """`Date.now()`：毫秒时间戳（整数）。"""
    import time as _time

    return int(_time.time() * 1000)


def js_pop(arr: list[T]) -> T:
    """`Array.prototype.pop()`；空数组在 JS 里返回 `undefined`，这里返回 `None`。

    调用点都在"手上必然有牌"的分支里，返回 `None` 只是为了让越界不再抛异常，
    与原实现读 `undefined` 后立即参与运算的行为一致（都会算出无意义的值）。
    """
    if not arr:
        return None  # type: ignore[return-value]
    return arr.pop()
