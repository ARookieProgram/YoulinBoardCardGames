"""封禁校验（`utils/bancheck.py`）的离线测试。

对应 Node 侧的 `tools/lib/smoke.mjs` 里那条签名断言——两侧跑绿才能说明
"游戏服问平台要封禁状态"这件事在两套实现里是同一个契约。

覆盖三件事：

1. **签名**：与平台侧、Node 侧共用的参考向量逐字一致（拼接顺序改一位就红）；
2. **fail-open**：超时 / 平台报错 / 未启用都只能放行，绝不抛异常；
3. **缓存与冷却**：成功结果按 TTL 复用、失败后有冷却窗口（避免平台挂掉时
   每次登录都白等一个超时）。

不发真实 HTTP：所有用例都把 `_request` 换成假的。
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shared.config import BanCheckConfig  # noqa: E402
from utils import bancheck  # noqa: E402

#: 与 configs_*.py 的开发默认值一致，也是参考向量的密钥。
DEV_KEY = "scmj-ban-check-dev-key"


def make_config(**overrides: object) -> BanCheckConfig:
    """一份可用的测试配置。"""
    config: BanCheckConfig = {
        "ENABLE": True,
        "HOST": "127.0.0.1",
        "PORT": 8000,
        "PRI_KEY": DEV_KEY,
        "TIMEOUT_MS": 1000,
        "CACHE_TTL_MS": 30000,
    }
    config.update(overrides)  # type: ignore[typeddict-item]
    return config


def banned_status(**overrides: object) -> bancheck.BanStatus:
    """一个"被封"的结果。"""
    fields: dict[str, object] = {
        "known": True,
        "banned": True,
        "reason": "使用外挂",
        "expires_at": None,
        "player_id": 9,
    }
    fields.update(overrides)
    return bancheck.BanStatus(**fields)  # type: ignore[arg-type]


class BanCheckTestBase(unittest.TestCase):
    """每个用例前后都清掉模块级状态（配置与缓存都是全局的）。"""

    def setUp(self) -> None:
        bancheck.reset()
        bancheck.init(make_config())

    def tearDown(self) -> None:
        bancheck.reset()


class SignTests(unittest.TestCase):
    """签名口径：与 platform_server 和 Node 实现必须完全一致。"""

    def test_reference_vectors(self) -> None:
        """三个参考向量由 Node 的 crypto 算出（密钥取配置里的开发默认值）。"""
        self.assertEqual(
            bancheck.build_sign(account="guest_123456", player_id=None, key=DEV_KEY),
            "72977b2a422916d846f1f8b9bb10528d",
        )
        self.assertEqual(
            bancheck.build_sign(account="", player_id=9, key=DEV_KEY),
            "e16efd54aaddb8fb2aada5912ca306cd",
        )
        self.assertEqual(
            bancheck.build_sign(account="guest_123456", player_id=9, key=DEV_KEY),
            "d4cb51c910c644dc4b29a94a62dded4b",
        )

    def test_field_labels_prevent_swapped_params(self) -> None:
        """带字段名拼接，所以"账号值"和"ID 值"互换不会撞出同一个签名。"""
        swapped = bancheck.build_sign(account="9", player_id=None, key=DEV_KEY)
        normal = bancheck.build_sign(account="", player_id=9, key=DEV_KEY)
        self.assertNotEqual(swapped, normal)


class BanMessageTests(unittest.TestCase):
    """给玩家看的文案（大厅服与游戏服共用，措辞必须一致）。"""

    def test_permanent(self) -> None:
        message = bancheck.ban_message(banned_status(reason="恶意挂机"))
        self.assertIn("账号已被封禁", message)
        self.assertIn("恶意挂机", message)
        self.assertIn("永久封禁", message)

    def test_temporary(self) -> None:
        message = bancheck.ban_message(banned_status(expires_at="2026-01-01 00:00:00"))
        self.assertIn("自动解封时间：2026-01-01 00:00:00", message)
        self.assertNotIn("永久封禁", message)

    def test_without_reason(self) -> None:
        message = bancheck.ban_message(banned_status(reason=""))
        self.assertIn("账号已被封禁", message)
        self.assertNotIn("原因：", message)


class FailOpenTests(BanCheckTestBase):
    """fail-open：问不到平台时一律放行。"""

    def test_disabled_config_never_calls_platform(self) -> None:
        """ENABLE=False 时连请求都不发。"""
        bancheck.init(make_config(ENABLE=False))
        with patch.object(bancheck, "_request", new=AsyncMock()) as request:
            status = asyncio.run(bancheck.check_account("guest_alpha"))
        self.assertFalse(status.known)
        self.assertFalse(status.banned)
        request.assert_not_awaited()

    def test_platform_error_allows_login(self) -> None:
        """平台报错（连不上 / 超时 / 返回非 0）→ 放行 + 不抛异常。"""
        with patch.object(bancheck, "_request", new=AsyncMock(side_effect=RuntimeError("boom"))):
            status = asyncio.run(bancheck.check_account("guest_alpha"))
        self.assertFalse(status.known)
        self.assertFalse(status.banned)

    def test_empty_identity_is_unknown(self) -> None:
        """空账号 / 非法 ID 直接按"不知道"处理，不发请求。"""
        with patch.object(bancheck, "_request", new=AsyncMock()) as request:
            self.assertFalse(asyncio.run(bancheck.check_account("")).known)
            self.assertFalse(asyncio.run(bancheck.check_account(None)).known)
            self.assertFalse(asyncio.run(bancheck.check_user_id(0)).known)
            self.assertFalse(asyncio.run(bancheck.check_user_id(None)).known)
        request.assert_not_awaited()

    def test_failure_enters_cooldown(self) -> None:
        """失败后进入冷却窗口：窗口内不再打平台（否则每次登录都白等一个超时）。"""
        with patch.object(bancheck, "_request", new=AsyncMock(side_effect=RuntimeError("boom"))) as request:
            asyncio.run(bancheck.check_account("guest_alpha"))
            asyncio.run(bancheck.check_account("guest_beta"))
        self.assertEqual(request.await_count, 1)

    def test_missing_init_raises(self) -> None:
        """忘了 `init()` 是代码 bug，直接抛错而不是静默放行。"""
        bancheck.reset()
        with self.assertRaises(RuntimeError):
            asyncio.run(bancheck.check_account("guest_alpha"))


class CacheTests(BanCheckTestBase):
    """成功结果按 TTL 缓存（正负都缓存）。"""

    def test_banned_result_is_cached(self) -> None:
        """TTL 内重复查同一个账号只打一次平台。"""
        with patch.object(bancheck, "_request", new=AsyncMock(return_value=banned_status())) as request:
            first = asyncio.run(bancheck.check_account("guest_alpha"))
            second = asyncio.run(bancheck.check_account("guest_alpha"))
        self.assertTrue(first.banned)
        self.assertTrue(second.banned)
        self.assertEqual(request.await_count, 1)

    def test_not_banned_result_is_cached(self) -> None:
        """没封的结果同样缓存（否则每次登录都要多打一次平台）。"""
        clean = bancheck.BanStatus(known=True, banned=False, player_id=7)
        with patch.object(bancheck, "_request", new=AsyncMock(return_value=clean)) as request:
            asyncio.run(bancheck.check_account("guest_alpha"))
            asyncio.run(bancheck.check_account("guest_alpha"))
        self.assertEqual(request.await_count, 1)

    def test_cache_is_keyed_by_identity(self) -> None:
        """账号与 ID 是两个 key，不会互相串味。"""
        with patch.object(bancheck, "_request", new=AsyncMock(return_value=banned_status())) as request:
            asyncio.run(bancheck.check_account("guest_alpha"))
            asyncio.run(bancheck.check_user_id(9))
        self.assertEqual(request.await_count, 2)

    def test_expired_cache_is_refetched(self) -> None:
        """TTL 设为 0 时下一次必定重新问平台（只影响缓存命中）。"""
        bancheck.init(make_config(CACHE_TTL_MS=0))
        with patch.object(bancheck, "_request", new=AsyncMock(return_value=banned_status())) as request:
            asyncio.run(bancheck.check_account("guest_alpha"))
            asyncio.run(bancheck.check_account("guest_alpha"))
        self.assertEqual(request.await_count, 2)


class RequestTests(BanCheckTestBase):
    """发出去的请求长什么样（参数与签名）。"""

    def test_account_request_carries_account_and_sign(self) -> None:
        """按账号查：带 account 与按它算出来的 sign。"""
        with patch.object(bancheck, "_request", new=AsyncMock(return_value=banned_status())) as request:
            asyncio.run(bancheck.check_account("guest_alpha"))
        _, params = request.await_args.args
        self.assertEqual(params["account"], "guest_alpha")
        self.assertEqual(
            params["sign"],
            bancheck.build_sign(account="guest_alpha", player_id=None, key=DEV_KEY),
        )
        self.assertNotIn("player_id", params)

    def test_user_id_request_carries_player_id_and_sign(self) -> None:
        """按 ID 查：带 player_id 与按它算出来的 sign（游戏服走这条）。"""
        with patch.object(bancheck, "_request", new=AsyncMock(return_value=banned_status())) as request:
            asyncio.run(bancheck.check_user_id(9))
        _, params = request.await_args.args
        self.assertEqual(params["player_id"], 9)
        self.assertEqual(
            params["sign"],
            bancheck.build_sign(account="", player_id=9, key=DEV_KEY),
        )
        self.assertNotIn("account", params)

    def test_path_is_the_platform_internal_endpoint(self) -> None:
        """路径必须与 platform_server 的路由一致。"""
        self.assertEqual(bancheck.BAN_CHECK_PATH, "/api/internal/players/ban-check/")


class ParseTests(unittest.TestCase):
    """平台返回体的解析。"""

    def test_full_payload(self) -> None:
        status = bancheck._parse(
            {
                "account": "guest_alpha",
                "player_id": 9,
                "known": True,
                "banned": True,
                "reason": "使用外挂",
                "expires_at": "2026-01-01 00:00:00",
            }
        )
        self.assertTrue(status.known)
        self.assertTrue(status.banned)
        self.assertEqual(status.reason, "使用外挂")
        self.assertEqual(status.expires_at, "2026-01-01 00:00:00")
        self.assertEqual(status.player_id, 9)

    def test_unknown_player(self) -> None:
        """查不到账号时 known=false、player_id=null。"""
        status = bancheck._parse({"known": False, "player_id": None, "banned": False})
        self.assertFalse(status.known)
        self.assertFalse(status.banned)
        self.assertIsNone(status.player_id)

    def test_non_object_payload_raises(self) -> None:
        """返回体不是对象时抛错，由上层 fail-open 兜住。"""
        with self.assertRaises(RuntimeError):
            bancheck._parse("nope")


if __name__ == "__main__":
    unittest.main()
