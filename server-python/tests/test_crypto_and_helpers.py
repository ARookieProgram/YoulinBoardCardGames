"""离线冒烟测试：摘要 / Base64 / 查询参数助手 / JS 语义助手。

与仓库根门禁 `tools/lib/smoke.mjs` 用的是**同一组已知向量**，
所以两侧跑出来的结论可以直接对照。
运行方式见 `server-python/AGENTS.md` §5：

    .venv/bin/python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from utils import crypto, http  # noqa: E402
from utils.jscompat import (  # noqa: E402
    js_index_of,
    js_keys,
    js_number,
    js_parse_int,
    js_random_index,
    js_str,
    splice,
)


class CryptoTest(unittest.TestCase):
    def test_md5_reference_digest(self) -> None:
        self.assertEqual(crypto.md5("hello"), "5d41402abc4b2a76b9719d911017c592")

    def test_md5_accepts_non_string_like_js_concat(self) -> None:
        # 进房签名是 `md5(roomid + token + time + KEY)`，拼接结果里 time 可能是数字。
        # md5() 内部做的是 JS 的 String() 转换：数字 123456 与 "123456" 摘要相同。
        self.assertEqual(crypto.md5(123456), crypto.md5("123456"))
        # JS 的 `null` 转字符串是 "null"，`None` 必须也变成 "null"。
        self.assertEqual(crypto.md5(None), crypto.md5("null"))

    def test_base64_round_trips_ascii(self) -> None:
        self.assertEqual(crypto.from_base64(crypto.to_base64("babykylin")), "babykylin")

    def test_base64_round_trips_chinese_player_names(self) -> None:
        # t_users.name 是非 ASCII 时也要能原样回来。
        name = "四川麻将玩家"
        self.assertEqual(crypto.from_base64(crypto.to_base64(name)), name)

    def test_base64_matches_reference_encoding(self) -> None:
        self.assertEqual(crypto.to_base64("hello"), "aGVsbG8=")
        # SQL 样例里的那些名字
        self.assertEqual(crypto.from_base64("5aSP5L6v6LWM5L6g"), "夏侯赌侠")


class JsCompatTest(unittest.TestCase):
    def test_js_str(self) -> None:
        self.assertEqual(js_str(None), "null")
        self.assertEqual(js_str(True), "true")
        self.assertEqual(js_str(False), "false")
        self.assertEqual(js_str(9), "9")
        self.assertEqual(js_str(9.0), "9")
        self.assertEqual(js_str(math.nan), "NaN")
        self.assertEqual(js_str("x"), "x")

    def test_js_parse_int(self) -> None:
        self.assertEqual(js_parse_int("42"), 42)
        self.assertEqual(js_parse_int("12abc"), 12)
        self.assertEqual(js_parse_int("-7"), -7)
        self.assertTrue(math.isnan(js_parse_int("abc")))
        self.assertTrue(math.isnan(js_parse_int("")))

    def test_js_number(self) -> None:
        self.assertEqual(js_number("21"), 21.0)
        self.assertEqual(js_number(""), 0.0)
        self.assertEqual(js_number(None), 0.0)
        self.assertTrue(math.isnan(js_number("abc")))

    def test_js_keys_is_ascending_numeric_order(self) -> None:
        # JS 对整数样式的键按数值升序枚举，与 Python 的插入序不同。
        mapping = {5: 1, 1: 1, 3: 1}
        self.assertEqual(js_keys(mapping), [1, 3, 5])

    def test_splice_handles_negative_index_like_js(self) -> None:
        arr = [1, 2, 3]
        splice(arr, -1, 1)
        # splice(-1,1) 删的是最后一个元素，不是"删不掉"
        self.assertEqual(arr, [1, 2])

    def test_splice_removes_middle(self) -> None:
        arr = [1, 2, 3]
        self.assertEqual(splice(arr, 1, 1), [2])
        self.assertEqual(arr, [1, 3])

    def test_js_index_of(self) -> None:
        self.assertEqual(js_index_of([4, 5, 6], 5), 1)
        self.assertEqual(js_index_of([4, 5, 6], 9), -1)

    def test_js_random_index_zero_is_zero(self) -> None:
        # 洗牌循环的最后一次 lastIndex == 0，JS 得到 0；randrange(0) 会抛异常。
        self.assertEqual(js_random_index(0), 0)


class _FakeRequest:
    """`http.query_string` / `query_int` 只用到 `.query`。"""

    def __init__(self, query: dict[str, str]) -> None:
        self.query = query


class QueryHelperTest(unittest.TestCase):
    def test_query_string(self) -> None:
        request = _FakeRequest({"s": "abc"})
        self.assertEqual(http.query_string(request, "s"), "abc")
        self.assertIsNone(http.query_string(request, "nope"))

    def test_query_int(self) -> None:
        request = _FakeRequest({"n": "42", "f": "3.9"})
        self.assertEqual(http.query_int(request, "n"), 42)
        self.assertEqual(http.query_int(request, "f"), 3)
        # 缺参数时是 NaN（对齐 parseInt），不是异常
        self.assertTrue(math.isnan(http.query_int(request, "nope")))

    def test_query_int_returns_int_not_float(self) -> None:
        # 落库的 base_info JSON 里 creator 必须是 9 而不是 9.0
        value = http.query_int(_FakeRequest({"userid": "9"}), "userid")
        self.assertIsInstance(value, int)
        self.assertEqual(value, 9)


class ResponseShapeTest(unittest.TestCase):
    def test_send_writes_errcode_and_errmsg_into_data(self) -> None:
        response = http.send(0, "ok", {"a": 1})
        self.assertEqual(response.body.decode("utf-8"), '{"a":1,"errcode":0,"errmsg":"ok"}')

    def test_send_defaults_to_empty_object(self) -> None:
        response = http.send(1, "boom")
        self.assertEqual(response.body.decode("utf-8"), '{"errcode":1,"errmsg":"boom"}')


if __name__ == "__main__":
    unittest.main()
