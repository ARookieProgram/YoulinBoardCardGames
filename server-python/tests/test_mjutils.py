"""听牌判定（`game_server/mjutils.py`）的已知向量。

用例与仓库根门禁 `tools/lib/smoke.mjs` **逐条对应**：同样的手牌、同样的期望结果。
两侧同时跑绿，才能说明 Python 版与 Node 版的听牌判定行为一致。

牌 id 约定：0-8 筒、9-17 条、18-26 万。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from game_server import mjutils  # noqa: E402


def build_seat(holds: list[int]) -> object:
    """造一个 `check_ting_pai` 需要的座位形状（对应 smoke.mjs 的 `buildSeat`）。"""
    count_map: dict[int, int] = {}
    for tile in holds:
        count_map[tile] = count_map.get(tile, 0) + 1

    class _Seat:
        pass

    seat = _Seat()
    seat.holds = list(holds)
    seat.countMap = count_map
    seat.tingMap = {}
    return seat


class CheckTingPaiTest(unittest.TestCase):
    def test_detects_pair_wait(self) -> None:
        # 四副面子已成，单张 5条(13) 必须凑成将
        seat = build_seat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13])
        mjutils.check_ting_pai(seat, 0, 27)
        self.assertEqual(sorted(seat.tingMap.keys()), [13])

    def test_detects_wait_behind_four_pungs(self) -> None:
        seat = build_seat([18, 18, 18, 19, 19, 19, 20, 20, 20, 21, 21, 21, 13])
        mjutils.check_ting_pai(seat, 0, 27)
        self.assertEqual(sorted(seat.tingMap.keys()), [13])

    def test_decomposes_two_identical_runs_plus_pair(self) -> None:
        # 18-19-20 两遍 + 21-22-23 两遍，24 作将；考的是顺子回溯
        seat = build_seat([18, 18, 19, 19, 20, 20, 21, 21, 22, 22, 23, 23, 24])
        mjutils.check_ting_pai(seat, 0, 27)
        self.assertEqual(sorted(seat.tingMap.keys()), [18, 21, 24])

    def test_reports_no_wait_for_a_disconnected_hand(self) -> None:
        seat = build_seat([0, 3, 6, 9, 12, 15, 18, 21, 24, 1, 5, 10, 14])
        mjutils.check_ting_pai(seat, 0, 27)
        self.assertEqual(list(seat.tingMap.keys()), [])

    def test_does_not_implement_seven_pairs(self) -> None:
        # 钉住的限制：这个引擎**没有**七对判定。六对 + 单张 1万 听不到牌。
        seat = build_seat([0, 0, 3, 3, 6, 6, 9, 9, 12, 12, 15, 15, 18])
        mjutils.check_ting_pai(seat, 0, 27)
        self.assertEqual(list(seat.tingMap.keys()), [])

    def test_hu_tile_gets_normal_pattern_with_zero_fan(self) -> None:
        # mjutils 只判"能不能和"，番型与番数由 gamemgr 的 checkCanTingPai 决定
        seat = build_seat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13])
        mjutils.check_ting_pai(seat, 0, 27)
        self.assertEqual(seat.tingMap[13].pattern, "normal")
        self.assertEqual(seat.tingMap[13].fan, 0)

    def test_range_limits_are_respected(self) -> None:
        # 只检查 [begin, end) 的牌：这副牌唯一能和的 13（5条）落在 9..17 之外
        seat = build_seat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13])
        mjutils.check_ting_pai(seat, 18, 27)
        self.assertEqual(list(seat.tingMap.keys()), [])

    def test_range_includes_the_waiting_tile(self) -> None:
        # 把 13 圈进范围就能查到（与上一条互为对照）
        seat = build_seat([18, 19, 20, 21, 22, 23, 24, 25, 26, 9, 9, 9, 13])
        mjutils.check_ting_pai(seat, 9, 18)
        self.assertEqual(list(seat.tingMap.keys()), [13])


class GetMjTypeTest(unittest.TestCase):
    def test_dots(self) -> None:
        self.assertEqual(mjutils.get_mj_type(0), 0)
        self.assertEqual(mjutils.get_mj_type(8), 0)

    def test_bamboo(self) -> None:
        self.assertEqual(mjutils.get_mj_type(9), 1)
        self.assertEqual(mjutils.get_mj_type(17), 1)

    def test_characters(self) -> None:
        self.assertEqual(mjutils.get_mj_type(18), 2)
        self.assertEqual(mjutils.get_mj_type(26), 2)

    def test_out_of_range_is_none(self) -> None:
        self.assertIsNone(mjutils.get_mj_type(27))
        self.assertIsNone(mjutils.get_mj_type(-1))


if __name__ == "__main__":
    unittest.main()
