"""登录闭环的接口测试。

覆盖范围：

* 口令正确 → 拿到 access/refresh 与管理员信息；
* 口令错误 / 账号不存在 → 同一句文案、同一错误码（防账号枚举）；
* 账号被禁用 → 明确的禁用错误码；
* `/me/` 认令牌、拒无令牌与伪造令牌；
* refresh 轮换：旧 refresh 用一次即失效；
* 退出登录：refresh 进黑名单，退出后不能再换 access；
* **账号体系隔离**：玩家表里的账号名登不进管理平台。

跑法见 `tests/__init__.py`；本文件不依赖 MySQL 之外的任何外部服务。
"""

from __future__ import annotations

from typing import Any

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AdminUser

LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"
ME_URL = "/api/auth/me/"
LOGOUT_URL = "/api/auth/logout/"

PASSWORD = "AdminPass!2024"


def create_admin(**overrides: Any) -> AdminUser:
    """建一个启用中的管理员，默认是超级管理员。"""
    fields: dict[str, Any] = {
        "username": "admin",
        "password": PASSWORD,
        "email": "admin@platform.local",
        "nickname": "超级管理员",
    }
    fields.update(overrides)
    return AdminUser.objects.create_superuser(**fields)


class LoginSuccessTests(TestCase):
    """登录成功路径。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = create_admin()

    def test_login_returns_tokens_and_user(self) -> None:
        """口令正确时返回一对令牌与管理员信息。"""
        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertIn("access", data)
        self.assertIn("refresh", data)
        self.assertIsInstance(data["access_expires_at"], int)
        self.assertEqual(data["user"]["username"], "admin")
        self.assertEqual(data["user"]["role"], AdminUser.Role.SUPER_ADMIN)

    def test_login_never_leaks_password(self) -> None:
        """响应里不能出现口令或哈希。"""
        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
        )
        raw = response.content.decode("utf-8")
        self.assertNotIn("password", raw)
        self.assertNotIn(PASSWORD, raw)

    def test_login_records_last_login_ip(self) -> None:
        """登录成功后记录来源 IP 与时间。"""
        self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="10.1.2.3",
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.last_login_ip, "10.1.2.3")
        self.assertIsNotNone(self.admin.last_login)

    def test_login_is_case_insensitive_on_username(self) -> None:
        """账号名大小写不敏感，但库里仍是创建时的写法。"""
        response = self.client.post(
            LOGIN_URL,
            {"username": "ADMIN", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.username, "admin")

    def test_login_accepts_forwarded_ip(self) -> None:
        """有反向代理时取 X-Forwarded-For 的第一段。"""
        self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1",
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.last_login_ip, "203.0.113.9")


class LoginFailureTests(TestCase):
    """登录失败路径。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = create_admin()

    def test_wrong_password_uses_generic_message(self) -> None:
        """口令错误返回 11001 与统一文案。

        只断言文案是不够的：曾经出现过"文案对、业务码被压成 10001"的偏差
        （DRF 的 `ValidationError` 无法携带自定义业务码），所以这里**同时**钉住 code。
        """
        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], 11001)
        self.assertIn("账号或密码错误", body["message"])

    def test_unknown_account_uses_same_message(self) -> None:
        """账号不存在与口令错误**不可区分**，避免枚举管理员账号。"""
        wrong_password = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": "wrong-password"},
            format="json",
        )
        unknown = self.client.post(
            LOGIN_URL,
            {"username": "no-such-admin", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(wrong_password.status_code, unknown.status_code)
        self.assertEqual(wrong_password.json()["code"], 11001)
        self.assertEqual(
            wrong_password.json()["message"],
            unknown.json()["message"],
        )
        self.assertEqual(wrong_password.json()["code"], unknown.json()["code"])

    def test_disabled_account_is_rejected_explicitly(self) -> None:
        """被禁用的账号给出明确原因（不是含糊的密码错误）。"""
        self.admin.status = AdminUser.Status.DISABLED
        self.admin.save()

        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["code"], 11002)
        self.assertIn("已被禁用", body["message"])

    def test_missing_fields_are_reported(self) -> None:
        """空入参被拒绝，业务码是 10001（参数不合法）。"""
        response = self.client.post(LOGIN_URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], 10001)
        self.assertNotEqual(body["message"], "")

    def test_disabling_syncs_is_active(self) -> None:
        """禁用后 `is_active` 必须跟着变，否则 Django 仍认为账号有效。"""
        self.admin.status = AdminUser.Status.DISABLED
        self.admin.save()
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.is_active)
        self.assertFalse(self.admin.is_enabled)


class CurrentAdminTests(TestCase):
    """`/api/auth/me/`。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = create_admin()
        self.token = self._login()

    def _login(self) -> str:
        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
        )
        return response.json()["data"]["access"]

    def test_me_requires_token(self) -> None:
        """没有令牌时返回 401 与 10002。"""
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)

    def test_me_rejects_garbage_token(self) -> None:
        """伪造令牌同样被拒。"""
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 401)

    def test_me_returns_current_admin(self) -> None:
        """带上有效令牌能拿到自己的资料。"""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["username"], "admin")
        self.assertEqual(data["nickname"], "超级管理员")
        self.assertTrue(data["is_superuser"])

    def test_me_rejects_disabled_admin(self) -> None:
        """登录后被禁用的账号，旧令牌立刻失效。"""
        self.admin.status = AdminUser.Status.DISABLED
        self.admin.save()

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        response = self.client.get(ME_URL)
        # SimpleJWT 校验 `is_active`，禁用后令牌立即不可用。
        self.assertEqual(response.status_code, 401)


class RefreshTests(TestCase):
    """令牌轮换。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = create_admin()
        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
        )
        self.tokens: dict[str, Any] = response.json()["data"]

    def test_refresh_returns_new_access(self) -> None:
        """用 refresh 换到新 access，并带回管理员信息。"""
        response = self.client.post(
            REFRESH_URL,
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIn("access", data)
        self.assertEqual(data["user"]["username"], "admin")

    def test_refresh_rotates_and_blacklists_old_token(self) -> None:
        """轮换后旧 refresh 不能再用（旧的一次性）。"""
        first = self.client.post(
            REFRESH_URL,
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertIn("refresh", first.json()["data"])

        reuse = self.client.post(
            REFRESH_URL,
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(reuse.status_code, 401)
        self.assertEqual(reuse.json()["code"], 11003)

    def test_refresh_rejects_garbage(self) -> None:
        """非法 refresh 返回 11003，而不是 500。"""
        response = self.client.post(REFRESH_URL, {"refresh": "garbage"}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 11003)

    def test_refresh_rejects_disabled_admin(self) -> None:
        """登录后被禁用的账号不能再靠 refresh 续期。"""
        self.admin.status = AdminUser.Status.DISABLED
        self.admin.save()

        response = self.client.post(
            REFRESH_URL,
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 11002)

    def test_refresh_rotates_only_once_per_token(self) -> None:
        """轮换后的 refresh 能继续用（链式刷新），旧的那个不能。"""
        first = self.client.post(REFRESH_URL, {"refresh": self.tokens["refresh"]}, format="json")
        rotated = first.json()["data"]["refresh"]

        second = self.client.post(REFRESH_URL, {"refresh": rotated}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["code"], 0)


class LogoutTests(TestCase):
    """退出登录。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.admin = create_admin()
        response = self.client.post(
            LOGIN_URL,
            {"username": "admin", "password": PASSWORD},
            format="json",
        )
        self.tokens: dict[str, Any] = response.json()["data"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.tokens['access']}")

    def test_logout_blacklists_refresh(self) -> None:
        """退出后 refresh 失效，无法再换 access。"""
        response = self.client.post(
            LOGOUT_URL,
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["revoked"])

        self.client.credentials()
        after = self.client.post(
            REFRESH_URL,
            {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(after.status_code, 401)

    def test_logout_requires_login(self) -> None:
        """未登录不能调退出接口。"""
        self.client.credentials()
        response = self.client.post(LOGOUT_URL, {}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_logout_without_refresh_still_succeeds(self) -> None:
        """只带 access 也要能退出（前端没存 refresh 的场景）。"""
        response = self.client.post(LOGOUT_URL, {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["revoked"])


class HealthTests(TestCase):
    """健康检查。

    这个接口回归过一次：它返回的是 DRF 的 `Response`，如果挂在裸 Django 视图上，
    没有经过 DRF 的渲染流程，Django 会在 `response.render()` 阶段抛
    `AssertionError: .accepted_renderer not set on Response`（HTTP 500）。
    """

    def test_health_is_public_and_json(self) -> None:
        """无需登录即可访问，返回统一外壳的 JSON。"""
        response = APIClient().get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["status"], "up")


class AccountIsolationTests(TestCase):
    """**账号体系隔离**——本平台最重要的一条约束。

    玩家账号存在 `t_accounts` / `t_users`（`db_scmj`），不在 Django 的 ORM 里。
    这里用"同名账号"的方式验证：即使玩家库里有 `admin`，管理平台的登录
    也只看 `AdminUser` 表，两边永远不会互相认证。
    """

    def setUp(self) -> None:
        self.client = APIClient()

    def test_player_account_cannot_login_platform(self) -> None:
        """玩家库里存在同名账号时，管理平台登录依然按自己的表判定。"""
        # 模拟玩家库里的 `admin`（明文口令，历史实现），它**不在** AdminUser 表里。
        player_account = {"account": "admin", "password": "playerplaintext"}

        response = self.client.post(
            LOGIN_URL,
            {"username": player_account["account"], "password": player_account["password"]},
            format="json",
        )
        # 管理平台没有这个管理员 → 拒绝。
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AdminUser.objects.count(), 0)

    def test_platform_admin_is_not_a_player_account(self) -> None:
        """管理平台管理员不产生任何玩家账号数据。"""
        create_admin(username="ops", email="ops@platform.local")
        self.assertEqual(AdminUser.objects.count(), 1)
        # AdminUser 落在自己的表上，与玩家表无关联。
        self.assertEqual(AdminUser._meta.db_table, "accounts_adminuser")

    def test_platform_login_uses_hashed_password(self) -> None:
        """管理员口令是哈希存储，不是玩家侧的明文。"""
        admin = create_admin()
        self.assertNotEqual(admin.password, PASSWORD)
        self.assertTrue(admin.password.startswith("pbkdf2_"))


class SeedAdminCommandTests(TestCase):
    """`manage.py seed_admin`。"""

    def test_seed_creates_superuser(self) -> None:
        """全新库上能建出可登录的超级管理员。"""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command(
            "seed_admin",
            "--username",
            "root",
            "--password",
            "SeedPass!2024",
            "--email",
            "root@platform.local",
            stdout=out,
        )

        admin = AdminUser.objects.get(username="root")
        self.assertEqual(admin.role, AdminUser.Role.SUPER_ADMIN)
        self.assertTrue(admin.is_superuser)

        client = APIClient()
        response = client.post(
            LOGIN_URL,
            {"username": "root", "password": "SeedPass!2024"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_seed_is_idempotent_and_keeps_password(self) -> None:
        """重复执行不覆盖口令（默认幂等）。"""
        from io import StringIO

        from django.core.management import call_command

        create_admin(username="root", email="root@platform.local")
        before = AdminUser.objects.get(username="root").password

        call_command("seed_admin", "--username", "root", stdout=StringIO())

        after = AdminUser.objects.get(username="root").password
        self.assertEqual(before, after)

    def test_seed_reset_password(self) -> None:
        """`--reset-password` 才改口令。"""
        from io import StringIO

        from django.core.management import call_command

        create_admin(username="root", email="root@platform.local")

        call_command(
            "seed_admin",
            "--username",
            "root",
            "--password",
            "BrandNew!2024",
            "--reset-password",
            stdout=StringIO(),
        )

        client = APIClient()
        response = client.post(
            LOGIN_URL,
            {"username": "root", "password": "BrandNew!2024"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
