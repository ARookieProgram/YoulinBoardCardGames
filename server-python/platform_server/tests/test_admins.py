"""管理员账号管理（`/api/admins/`）的接口测试。

覆盖范围：

* **权限**：未登录 `10002`；运营 / 普通管理员 `10003`；超级管理员可用；
  `me/password/` 对任何登录管理员开放；
* **列表**：形状与分页、关键字（账号 / 昵称 / 邮箱）、角色与状态过滤、
  排序、**按 `effective_role` 口径过滤 `is_superuser` 的历史行**、非法参数 `10001`；
* **概览**：总数 / 启用 / 停用 / 超级管理员数；
* **新建**：成功（角色与 `is_superuser` 同步）、账号名与邮箱判重（`15002` / `15003`，
  且**大小写不敏感**）、弱口令 `10001`、非法账号名 `10001`、口令是 PBKDF2 哈希；
* **改资料**：字段落库、邮箱判重排除自己、空入参 `10001`、账号名不可改；
* **角色**：升为超级管理员后 `is_superuser` / `is_staff` 跟上；降级最后一个超级管理员 `15005`；
  降级自己 `15004`；
* **状态**：停用后**登不进来**（登录 `11002`、旧令牌 401、refresh 403）、重新启用可恢复、
  停用自己 `15004`、停用最后一个超级管理员 `15005`；
* **口令**：超级管理员重置他人口令（新口令可登录、旧口令失效、refresh 被吊销）；
  本人改口令（原口令错误 `15006`、新口令不能与原口令相同 `10001`、改完 self 的 refresh 失效）；
* **删除**：成功、删自己 `15004`、删除后封禁流水仍可读（`operator_name` 快照）、
  不存在 `15001`；
* **隔离**：本模块只碰 `accounts_adminuser`，不会去读玩家库。

跑法见 `tests/__init__.py`；本文件不依赖 MySQL 之外的任何外部服务。
"""

from __future__ import annotations

from typing import Any

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import AdminUser
from apps.players.models import PlayerBan

LIST_URL = "/api/admins/"
OVERVIEW_URL = "/api/admins/overview/"
MY_PASSWORD_URL = "/api/admins/me/password/"

PASSWORD = "AdminPass!2024"
#: 满足 Django 四个校验器的口令（长度 ≥ 8、非常见、非纯数字、与账号不像）。
NEW_PASSWORD = "Fj7#quadZebra"


def detail_url(admin_id: int) -> str:
    """`/api/admins/<id>/`。"""
    return f"/api/admins/{admin_id}/"


def status_url(admin_id: int) -> str:
    """`/api/admins/<id>/status/`。"""
    return f"/api/admins/{admin_id}/status/"


def password_url(admin_id: int) -> str:
    """`/api/admins/<id>/password/`。"""
    return f"/api/admins/{admin_id}/password/"


def create_super(**overrides: Any) -> AdminUser:
    """建一个超级管理员。"""
    fields: dict[str, Any] = {
        "username": "root",
        "password": PASSWORD,
        "email": "root@platform.local",
        "nickname": "超级管理员",
    }
    fields.update(overrides)
    return AdminUser.objects.create_superuser(**fields)


def create_operator(**overrides: Any) -> AdminUser:
    """建一个运营账号。"""
    fields: dict[str, Any] = {
        "username": "ops",
        "password": PASSWORD,
        "email": "ops@platform.local",
        "nickname": "运营",
        "role": AdminUser.Role.OPERATOR,
    }
    fields.update(overrides)
    return AdminUser.objects.create_user(**fields)


def create_admin_role(**overrides: Any) -> AdminUser:
    """建一个"管理员"角色的账号。"""
    fields: dict[str, Any] = {
        "username": "manager",
        "password": PASSWORD,
        "email": "manager@platform.local",
        "nickname": "管理员",
        "role": AdminUser.Role.ADMIN,
    }
    fields.update(overrides)
    return AdminUser.objects.create_user(**fields)


def login(client: APIClient, username: str, password: str) -> dict[str, Any]:
    """走真实登录接口，返回整个 `data`（含 access / refresh）。"""
    response = client.post(
        "/api/auth/login/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()["data"]
    return data


class AdminPermissionTests(TestCase):
    """权限边界：这块是"权限的源头"，除改自己口令外只对超级管理员开放。"""

    def setUp(self) -> None:
        self.super_admin = create_super()
        self.operator = create_operator()
        self.manager = create_admin_role()

    def test_requires_login(self) -> None:
        """未登录访问列表 → 401 + 10002。"""
        response = APIClient().get(LIST_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)

    def test_operator_is_forbidden(self) -> None:
        """运营不能看管理员列表 → 403 + 10003。"""
        client = APIClient()
        client.force_authenticate(user=self.operator)
        response = client.get(LIST_URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_admin_role_is_forbidden(self) -> None:
        """普通管理员也不行——只有超级管理员能管账号。"""
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.get(LIST_URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_operator_cannot_create(self) -> None:
        """无权限的写操作同样被拦下，不是只有读被拦。"""
        client = APIClient()
        client.force_authenticate(user=self.manager)
        response = client.post(
            LIST_URL,
            {
                "username": "sneaky",
                "email": "sneaky@platform.local",
                "password": NEW_PASSWORD,
                "role": AdminUser.Role.SUPER_ADMIN,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)
        self.assertFalse(AdminUser.objects.filter(username="sneaky").exists())

    def test_super_admin_can_list(self) -> None:
        """超级管理员能拿到列表。"""
        client = APIClient()
        client.force_authenticate(user=self.super_admin)
        response = client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)

    def test_disabled_super_admin_is_rejected(self) -> None:
        """被停用的超级管理员即使拿着旧令牌也不能再管账号。"""
        self.super_admin.status = AdminUser.Status.DISABLED
        self.super_admin.save()

        client = APIClient()
        client.force_authenticate(user=self.super_admin)
        response = client.get(LIST_URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)

    def test_my_password_is_open_to_every_role(self) -> None:
        """`me/password/` 是唯一不要求超级管理员的端点（运营也要能改自己的口令）。"""
        client = APIClient()
        client.force_authenticate(user=self.operator)
        response = client.post(
            MY_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)

    def test_no_password_is_ever_returned(self) -> None:
        """列表响应里不能出现口令或哈希。"""
        client = APIClient()
        client.force_authenticate(user=self.super_admin)
        raw = client.get(LIST_URL).content.decode("utf-8")
        self.assertNotIn("password", raw)
        self.assertNotIn(PASSWORD, raw)


class AdminListTests(TestCase):
    """列表：搜索 / 过滤 / 排序 / 分页。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        self.operator = create_operator()
        self.manager = create_admin_role(username="alice", email="alice@platform.local", nickname="爱丽丝")
        self.client.force_authenticate(user=self.super_admin)

    def _items(self, **params: Any) -> list[dict[str, Any]]:
        """查列表并取出 items。"""
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200, response.content)
        items: list[dict[str, Any]] = response.json()["data"]["items"]
        return items

    def test_payload_shape(self) -> None:
        """分页形状固定为 items/total/page/page_size/pages。"""
        data = self.client.get(LIST_URL, {"page": 1, "page_size": 2}).json()["data"]
        self.assertEqual(
            sorted(data.keys()),
            ["items", "page", "page_size", "pages", "total"],
        )
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 2)
        self.assertEqual(data["pages"], 2)
        self.assertEqual(len(data["items"]), 2)

    def test_row_fields(self) -> None:
        """每一行给出页面需要的字段，且没有口令。"""
        row = self._items(ordering="username")[0]
        for field in (
            "id",
            "username",
            "nickname",
            "display_name",
            "email",
            "role",
            "role_display",
            "effective_role",
            "status",
            "status_display",
            "remark",
            "is_superuser",
            "last_login",
            "last_login_ip",
            "created_at",
            "updated_at",
        ):
            self.assertIn(field, row, f"列表行缺少字段 {field}")

    def test_keyword_matches_username_nickname_email(self) -> None:
        """关键字同时匹配账号 / 昵称 / 邮箱。"""
        self.assertEqual([row["username"] for row in self._items(keyword="ali")], ["alice"])
        self.assertEqual([row["username"] for row in self._items(keyword="爱丽")], ["alice"])
        self.assertEqual(
            [row["username"] for row in self._items(keyword="alice@platform")],
            ["alice"],
        )

    def test_keyword_is_case_insensitive(self) -> None:
        """关键字大小写不敏感。"""
        self.assertEqual([row["username"] for row in self._items(keyword="ALICE")], ["alice"])

    def test_role_filter(self) -> None:
        """按角色过滤。"""
        self.assertEqual([row["username"] for row in self._items(role="operator")], ["ops"])
        self.assertEqual([row["username"] for row in self._items(role="admin")], ["alice"])
        self.assertEqual([row["username"] for row in self._items(role="super_admin")], ["root"])

    def test_role_filter_uses_effective_role(self) -> None:
        """`is_superuser=True` 但 `role` 还是 operator 的历史行也按超级管理员算。

        权限判断读的是 `effective_role`；如果过滤只看 `role`，
        页面上"超级管理员"这一档就会漏掉这种人。
        """
        legacy = create_operator(username="legacy", email="legacy@platform.local")
        legacy.is_superuser = True
        legacy.is_staff = True
        legacy.save()

        usernames = {row["username"] for row in self._items(role="super_admin")}
        self.assertIn("legacy", usernames)
        # 反向：按 operator 过滤时不能再把他算进来。
        self.assertNotIn("legacy", {row["username"] for row in self._items(role="operator")})

    def test_status_filter(self) -> None:
        """按状态过滤。"""
        self.operator.status = AdminUser.Status.DISABLED
        self.operator.save()

        self.assertEqual([row["username"] for row in self._items(status="disabled")], ["ops"])
        active = {row["username"] for row in self._items(status="active")}
        self.assertEqual(active, {"root", "alice"})

    def test_ordering_by_username(self) -> None:
        """`ordering=username` 生效。"""
        self.assertEqual(
            [row["username"] for row in self._items(ordering="username")],
            ["alice", "ops", "root"],
        )

    def test_default_ordering_is_newest_first(self) -> None:
        """默认按创建时间倒序：最后建的排最前。"""
        newest = create_operator(username="newest", email="newest@platform.local")
        self.assertEqual(self._items()[0]["id"], newest.pk)

    def test_pagination_offset(self) -> None:
        """翻页返回不同的两批数据。"""
        first = {row["id"] for row in self._items(page=1, page_size=2)}
        second = {row["id"] for row in self._items(page=2, page_size=2)}
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 1)
        self.assertFalse(first & second)

    def test_invalid_ordering_is_rejected(self) -> None:
        """排序键只允许白名单里的值（防注入 + 防乱序）。"""
        response = self.client.get(LIST_URL, {"ordering": "password"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_invalid_role_filter_is_rejected(self) -> None:
        """角色过滤取值要合法。"""
        response = self.client.get(LIST_URL, {"role": "root"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_invalid_page_size_is_rejected(self) -> None:
        """`page_size` 超上限要被拒（防止一次拉全表）。"""
        for page_size in ("0", "201", "abc"):
            response = self.client.get(LIST_URL, {"page_size": page_size})
            self.assertEqual(response.status_code, 400, page_size)
            self.assertEqual(response.json()["code"], 10001, page_size)


class AdminOverviewTests(TestCase):
    """概览数字。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        create_operator()
        disabled = create_operator(username="frozen", email="frozen@platform.local")
        disabled.status = AdminUser.Status.DISABLED
        disabled.save()
        self.client.force_authenticate(user=self.super_admin)

    def test_overview_counts(self) -> None:
        """总数 / 启用 / 停用 / 超级管理员数。"""
        data = self.client.get(OVERVIEW_URL).json()["data"]
        self.assertEqual(data["total_admins"], 3)
        self.assertEqual(data["active_admins"], 2)
        self.assertEqual(data["disabled_admins"], 1)
        self.assertEqual(data["super_admins"], 1)

    def test_overview_requires_super_admin(self) -> None:
        """概览同样只对超级管理员开放。"""
        client = APIClient()
        client.force_authenticate(user=create_operator(username="other", email="other@platform.local"))
        response = client.get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 10003)


class AdminCreateTests(TestCase):
    """新建管理员。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        self.client.force_authenticate(user=self.super_admin)

    def _create(self, **payload: Any) -> Any:
        """发一次新建请求。"""
        body: dict[str, Any] = {
            "username": "newbie",
            "nickname": "新人",
            "email": "newbie@platform.local",
            "password": NEW_PASSWORD,
            "role": AdminUser.Role.OPERATOR,
            "remark": "新来的",
        }
        body.update(payload)
        return self.client.post(LIST_URL, body, format="json")

    def test_create_returns_201_and_payload(self) -> None:
        """新建成功返回 201 与管理员信息。"""
        response = self._create()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["username"], "newbie")
        self.assertEqual(body["data"]["role"], AdminUser.Role.OPERATOR)
        self.assertEqual(body["data"]["status"], AdminUser.Status.ACTIVE)
        self.assertFalse(body["data"]["is_superuser"])

    def test_create_persists_hashed_password(self) -> None:
        """口令以 PBKDF2 哈希落库，明文不出现。"""
        self._create()
        admin = AdminUser.objects.get(username="newbie")
        self.assertNotEqual(admin.password, NEW_PASSWORD)
        self.assertTrue(admin.password.startswith("pbkdf2_"))
        self.assertTrue(admin.check_password(NEW_PASSWORD))

    def test_created_account_can_login(self) -> None:
        """新建的账号立刻能登录（这是"开号"这件事的验收口径）。"""
        self._create(username="fresh", email="fresh@platform.local")
        tokens = login(APIClient(), "fresh", NEW_PASSWORD)
        self.assertEqual(tokens["user"]["username"], "fresh")

    def test_create_super_admin_syncs_is_superuser(self) -> None:
        """角色是超级管理员时，`is_superuser` / `is_staff` 必须一起为真。"""
        response = self._create(role=AdminUser.Role.SUPER_ADMIN)
        self.assertEqual(response.status_code, 201)
        admin = AdminUser.objects.get(username="newbie")
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertEqual(admin.effective_role, AdminUser.Role.SUPER_ADMIN)

    def test_create_normal_role_is_not_staff(self) -> None:
        """普通角色不给 `is_staff`（Django admin 站点只留给超级管理员）。"""
        self._create(role=AdminUser.Role.ADMIN)
        admin = AdminUser.objects.get(username="newbie")
        self.assertFalse(admin.is_superuser)
        self.assertFalse(admin.is_staff)
        self.assertEqual(admin.effective_role, AdminUser.Role.ADMIN)

    def test_create_defaults_role_to_operator(self) -> None:
        """不传角色时默认是运营。"""
        response = self.client.post(
            LIST_URL,
            {
                "username": "plain",
                "email": "plain@platform.local",
                "password": NEW_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AdminUser.objects.get(username="plain").role, AdminUser.Role.OPERATOR)

    def test_duplicate_username_is_rejected(self) -> None:
        """账号名重复 → 15002。"""
        create_operator(username="taken", email="taken@platform.local")
        response = self._create(username="taken", email="another@platform.local")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15002)
        self.assertIn("已被占用", response.json()["message"])

    def test_duplicate_username_is_case_insensitive(self) -> None:
        """`TAKEN` 与 `taken` 视为同一个账号名（登录大小写不敏感）。"""
        create_operator(username="taken", email="taken@platform.local")
        response = self._create(username="TAKEN", email="another@platform.local")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15002)

    def test_duplicate_email_is_rejected(self) -> None:
        """邮箱重复 → 15003。"""
        create_operator(username="first", email="dup@platform.local")
        response = self._create(username="second", email="DUP@platform.local")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15003)
        self.assertIn("已被其他管理员使用", response.json()["message"])

    def test_short_password_is_rejected(self) -> None:
        """口令长度不足 → 10001。"""
        response = self._create(password="Ab1!")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)
        self.assertFalse(AdminUser.objects.filter(username="newbie").exists())

    def test_numeric_password_is_rejected(self) -> None:
        """纯数字口令被 `NumericPasswordValidator` 拒掉。"""
        response = self._create(password="123456789012")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_password_similar_to_username_is_rejected(self) -> None:
        """口令不能与账号名太像。"""
        response = self._create(username="zhangsan", password="zhangsan2024")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_invalid_username_is_rejected(self) -> None:
        """账号名沿用 Django 的字符集校验（空格 / 叹号不合法）。"""
        response = self._create(username="bad name!")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_missing_fields_are_rejected(self) -> None:
        """缺账号 / 邮箱 / 口令时报参数错误。"""
        response = self.client.post(LIST_URL, {"username": "x"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_new_account_is_active(self) -> None:
        """新建的账号一律启用（契约里没有"建一个停用账号"这条路）。"""
        self._create()
        admin = AdminUser.objects.get(username="newbie")
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.is_enabled)


class AdminUpdateTests(TestCase):
    """改资料与角色。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        self.target = create_operator()
        self.client.force_authenticate(user=self.super_admin)

    def test_update_profile_fields(self) -> None:
        """昵称 / 邮箱 / 备注都能改。"""
        response = self.client.patch(
            detail_url(self.target.pk),
            {"nickname": "张运营", "email": "zhang@platform.local", "remark": "转岗"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.nickname, "张运营")
        self.assertEqual(self.target.email, "zhang@platform.local")
        self.assertEqual(self.target.remark, "转岗")

    def test_update_without_changes_is_reported(self) -> None:
        """一个字段都没传时明确报错，而不是假装保存成功。"""
        response = self.client.patch(detail_url(self.target.pk), {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_update_keeps_own_email(self) -> None:
        """不改邮箱的保存不能被自己的邮箱挡住（判重排除自己）。"""
        response = self.client.patch(
            detail_url(self.target.pk),
            {"email": self.target.email, "nickname": "改昵称"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_update_rejects_taken_email(self) -> None:
        """改成别人的邮箱 → 15003。"""
        create_admin_role(username="other", email="other@platform.local")
        response = self.client.patch(
            detail_url(self.target.pk),
            {"email": "other@platform.local"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15003)

    def test_username_is_not_editable(self) -> None:
        """账号名不可改：传了也被忽略（契约里没有这个字段）。"""
        response = self.client.patch(
            detail_url(self.target.pk),
            {"username": "renamed", "nickname": "只改昵称"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, "ops")

    def test_promote_to_super_admin(self) -> None:
        """升为超级管理员：role / is_superuser / is_staff 三者同步。"""
        response = self.client.patch(
            detail_url(self.target.pk),
            {"role": AdminUser.Role.SUPER_ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, AdminUser.Role.SUPER_ADMIN)
        self.assertTrue(self.target.is_superuser)
        self.assertTrue(self.target.is_staff)
        self.assertEqual(response.json()["data"]["effective_role"], AdminUser.Role.SUPER_ADMIN)

    def test_promoted_admin_can_then_manage_admins(self) -> None:
        """升权之后真的能用（不是只改了展示字段）。"""
        self.client.patch(
            detail_url(self.target.pk),
            {"role": AdminUser.Role.SUPER_ADMIN},
            format="json",
        )
        self.target.refresh_from_db()
        client = APIClient()
        client.force_authenticate(user=self.target)
        self.assertEqual(client.get(LIST_URL).status_code, 200)

    def test_demote_another_super_admin(self) -> None:
        """还有别的超级管理员时，可以给某位超级管理员降级。"""
        other = create_super(username="root2", email="root2@platform.local")
        response = self.client.patch(
            detail_url(other.pk),
            {"role": AdminUser.Role.ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        other.refresh_from_db()
        self.assertFalse(other.is_superuser)
        self.assertFalse(other.is_staff)
        self.assertEqual(other.effective_role, AdminUser.Role.ADMIN)

    def test_cannot_demote_self_when_others_exist(self) -> None:
        """有别的超级管理员时也不能给自己降级 → 15004。"""
        create_super(username="root2", email="root2@platform.local")
        response = self.client.patch(
            detail_url(self.super_admin.pk),
            {"role": AdminUser.Role.ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15004)
        self.super_admin.refresh_from_db()
        self.assertEqual(self.super_admin.role, AdminUser.Role.SUPER_ADMIN)

    def test_cannot_demote_last_super_admin(self) -> None:
        """只剩一位超级管理员时给自己降级 → 15005。"""
        response = self.client.patch(
            detail_url(self.super_admin.pk),
            {"role": AdminUser.Role.OPERATOR},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15005)
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.is_superuser)

    def test_legacy_superuser_counts_as_super_admin(self) -> None:
        """`is_superuser=True` 的历史行也算超级管理员——护栏不能只看 `role`。

        这类行是历史上由 `createsuperuser` 之外途径产生、`role` 还没升上来的形态，
        权限判断（`effective_role`）把它当超级管理员，护栏也必须同样算它。
        """
        from apps.accounts.exceptions import AdminLastSuperAdmin
        from apps.accounts.views_admin import _assert_not_last_super, _enabled_super_admin_count

        legacy = create_operator(username="legacy", email="legacy@platform.local")
        legacy.is_superuser = True
        legacy.is_staff = True
        legacy.save()

        # 护栏数的就是 effective_role 口径：root 与 legacy 都算。
        self.assertEqual(_enabled_super_admin_count(), 2)
        self.assertEqual(_enabled_super_admin_count(exclude_pk=legacy.pk), 1)

        # 通过 API 把 legacy 降成普通管理员：root 还在，允许。
        response = self.client.patch(
            detail_url(legacy.pk),
            {"role": AdminUser.Role.ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        legacy.refresh_from_db()
        self.assertFalse(legacy.is_superuser)
        self.assertEqual(legacy.effective_role, AdminUser.Role.ADMIN)

        # 反过来：把 root 停掉之后，legacy 就是"最后一个启用中的超级管理员"，
        # 护栏必须认定这一点（这条路径通过 API 走不到——操作者自己一定被数进去，
        # 所以直接对护栏函数断言）。
        legacy.is_superuser = True
        legacy.is_staff = True
        legacy.save()
        self.super_admin.status = AdminUser.Status.DISABLED
        self.super_admin.save()
        with self.assertRaises(AdminLastSuperAdmin):
            _assert_not_last_super(legacy)

    def test_update_missing_admin_returns_15001(self) -> None:
        """改一个不存在的管理员 → 404 + 15001。"""
        response = self.client.patch(detail_url(999999), {"nickname": "x"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 15001)


class AdminStatusTests(TestCase):
    """启用 / 停用。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        self.target = create_operator()
        self.client.force_authenticate(user=self.super_admin)

    def test_disable_and_enable(self) -> None:
        """停用 → 启用，状态与 `is_active` 始终一致。"""
        response = self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.status, AdminUser.Status.DISABLED)
        self.assertFalse(self.target.is_active)
        self.assertFalse(self.target.is_enabled)

        response = self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.ACTIVE}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertTrue(self.target.is_enabled)

    def test_disabled_admin_cannot_login(self) -> None:
        """停用后立刻登不进来（登录返回 11002）。"""
        self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        response = APIClient().post(
            "/api/auth/login/",
            {"username": self.target.username, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 11002)

    def test_disabled_admin_old_token_is_rejected(self) -> None:
        """停用后旧 access 立刻失效（SimpleJWT 校验 `is_active`）。"""
        tokens = login(APIClient(), self.target.username, PASSWORD)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(client.get("/api/auth/me/").status_code, 200)

        self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        self.assertEqual(client.get("/api/auth/me/").status_code, 401)

    def test_disabled_admin_cannot_refresh(self) -> None:
        """停用后也不能靠 refresh 续期。"""
        tokens = login(APIClient(), self.target.username, PASSWORD)
        self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        response = APIClient().post(
            "/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], 11002)

    def test_reenable_restores_login(self) -> None:
        """重新启用后又能登录。"""
        self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.ACTIVE}, format="json"
        )
        tokens = login(APIClient(), self.target.username, PASSWORD)
        self.assertEqual(tokens["user"]["status"], AdminUser.Status.ACTIVE)

    def test_same_status_is_idempotent(self) -> None:
        """重复设置同一个状态不算错误（前端开关抖一下不该报红）。"""
        response = self.client.post(
            status_url(self.target.pk), {"status": AdminUser.Status.ACTIVE}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)

    def test_invalid_status_is_rejected(self) -> None:
        """非法状态 → 10001。"""
        response = self.client.post(status_url(self.target.pk), {"status": "sleeping"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_cannot_disable_self_when_others_exist(self) -> None:
        """还有别的超级管理员时也不能停用自己 → 15004。"""
        create_super(username="root2", email="root2@platform.local")
        response = self.client.post(
            status_url(self.super_admin.pk),
            {"status": AdminUser.Status.DISABLED},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15004)
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.is_enabled)

    def test_cannot_disable_last_super_admin(self) -> None:
        """只剩一位超级管理员时停用自己 → 15005。"""
        response = self.client.post(
            status_url(self.super_admin.pk),
            {"status": AdminUser.Status.DISABLED},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15005)
        self.super_admin.refresh_from_db()
        self.assertTrue(self.super_admin.is_enabled)

    def test_can_disable_super_admin_when_others_exist(self) -> None:
        """还有别的超级管理员时，可以停用另一位超级管理员。"""
        other = create_super(username="root2", email="root2@platform.local")
        response = self.client.post(
            status_url(other.pk), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        other.refresh_from_db()
        self.assertFalse(other.is_enabled)

    def test_status_missing_admin_returns_15001(self) -> None:
        """不存在的管理员 → 404 + 15001。"""
        response = self.client.post(
            status_url(999999), {"status": AdminUser.Status.DISABLED}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 15001)


class AdminPasswordTests(TestCase):
    """重置他人口令与本人改口令。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        self.target = create_operator()
        self.client.force_authenticate(user=self.super_admin)

    def test_reset_password_lets_target_login(self) -> None:
        """重置后目标账号能用新口令登录，旧口令失效。"""
        response = self.client.post(
            password_url(self.target.pk), {"new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)

        login(APIClient(), "ops", NEW_PASSWORD)
        old = APIClient().post(
            "/api/auth/login/", {"username": "ops", "password": PASSWORD}, format="json"
        )
        self.assertEqual(old.status_code, 400)
        self.assertEqual(old.json()["code"], 11001)

    def test_reset_password_revokes_refresh_tokens(self) -> None:
        """重置口令会吊销目标已签发的 refresh 令牌（改了密码别人就别想续期）。"""
        tokens = login(APIClient(), "ops", PASSWORD)
        response = self.client.post(
            password_url(self.target.pk), {"new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.json()["data"]["revoked_tokens"], 1)

        reuse = APIClient().post(
            "/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(reuse.status_code, 401)
        self.assertEqual(reuse.json()["code"], 11003)

    def test_reset_password_requires_strong_password(self) -> None:
        """弱口令被拒 → 10001，且原口令仍然有效。"""
        response = self.client.post(
            password_url(self.target.pk), {"new_password": "123"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)
        login(APIClient(), "ops", PASSWORD)

    def test_reset_password_of_self_is_allowed(self) -> None:
        """超级管理员给自己重置口令是允许的（不需要原口令的那条路）。"""
        response = self.client.post(
            password_url(self.super_admin.pk), {"new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        login(APIClient(), "root", NEW_PASSWORD)

    def test_reset_password_missing_admin_returns_15001(self) -> None:
        """不存在的管理员 → 404 + 15001。"""
        response = self.client.post(
            password_url(999999), {"new_password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 15001)

    def test_self_change_password(self) -> None:
        """本人改口令：带原口令即可，改完能登录。"""
        client = APIClient()
        client.force_authenticate(user=self.target)
        response = client.post(
            MY_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        login(APIClient(), "ops", NEW_PASSWORD)

    def test_self_change_wrong_old_password(self) -> None:
        """原口令错误 → 15006（不是 10001，也不是"请重新登录"）。"""
        client = APIClient()
        client.force_authenticate(user=self.target)
        response = client.post(
            MY_PASSWORD_URL,
            {"old_password": "not-my-password", "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15006)
        self.assertIn("原密码不正确", response.json()["message"])

    def test_self_change_same_password_is_rejected(self) -> None:
        """新口令不能与原口令相同 → 10001。"""
        client = APIClient()
        client.force_authenticate(user=self.target)
        response = client.post(
            MY_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_self_change_weak_new_password_is_rejected(self) -> None:
        """新口令强度不足 → 10001。"""
        client = APIClient()
        client.force_authenticate(user=self.target)
        response = client.post(
            MY_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": "abcdefgh"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 10001)

    def test_self_change_revokes_own_refresh_token(self) -> None:
        """本人改口令后自己的 refresh 也失效（其它设备需要重新登录）。"""
        tokens = login(APIClient(), "ops", PASSWORD)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = client.post(
            MY_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        reuse = APIClient().post(
            "/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(reuse.status_code, 401)

    def test_self_change_requires_login(self) -> None:
        """未登录不能改口令。"""
        response = APIClient().post(
            MY_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 10002)


class AdminDeleteTests(TestCase):
    """删除管理员。"""

    def setUp(self) -> None:
        self.client = APIClient()
        self.super_admin = create_super()
        self.target = create_operator()
        self.client.force_authenticate(user=self.super_admin)

    def test_delete_removes_row(self) -> None:
        """删除后表里没有这一行，响应给出被删的 id 与账号名。"""
        response = self.client.delete(detail_url(self.target.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["username"], "ops")
        self.assertFalse(AdminUser.objects.filter(pk=self.target.pk).exists())

    def test_deleted_admin_cannot_login(self) -> None:
        """删掉之后当然登不进来（账号不存在与口令错误同一个码）。"""
        self.client.delete(detail_url(self.target.pk))
        response = APIClient().post(
            "/api/auth/login/", {"username": "ops", "password": PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 11001)

    def test_cannot_delete_self_when_others_exist(self) -> None:
        """还有别的超级管理员时也不能删自己 → 15004。"""
        create_super(username="root2", email="root2@platform.local")
        response = self.client.delete(detail_url(self.super_admin.pk))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15004)
        self.assertTrue(AdminUser.objects.filter(pk=self.super_admin.pk).exists())

    def test_cannot_delete_last_super_admin(self) -> None:
        """只剩一位超级管理员时删自己 → 15005。"""
        response = self.client.delete(detail_url(self.super_admin.pk))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 15005)
        self.assertTrue(AdminUser.objects.filter(pk=self.super_admin.pk).exists())

    def test_can_delete_another_super_admin(self) -> None:
        """还有别人兜底时，可以删除另一位超级管理员。"""
        other = create_super(username="root2", email="root2@platform.local")
        response = self.client.delete(detail_url(other.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AdminUser.objects.filter(pk=other.pk).exists())

    def test_delete_missing_admin_returns_15001(self) -> None:
        """删除不存在的管理员 → 404 + 15001。"""
        response = self.client.delete(detail_url(999999))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], 15001)

    def test_ban_history_survives_admin_deletion(self) -> None:
        """删掉管理员之后，封禁流水仍然读得出来（操作人取自账号名快照）。"""
        PlayerBan.objects.create(
            player_id=1001,
            account="player1",
            player_name="玩家一",
            action=PlayerBan.Action.BAN,
            reason="外挂",
            operator=self.target,
            operator_name=self.target.username,
        )
        self.client.delete(detail_url(self.target.pk))

        record = PlayerBan.objects.get(player_id=1001)
        self.assertIsNone(record.operator)
        self.assertEqual(record.operator_name, "ops")
        self.assertEqual(record.as_payload()["operator_name"], "ops")


class AdminIsolationTests(TestCase):
    """账号体系隔离：管理员管理只碰 `accounts_adminuser`，不碰玩家库。"""

    #: 这条测试要往**玩家库连接**上挂 `CaptureQueriesContext` 数 SQL，
    #: 所以必须显式声明允许访问该别名（Django 默认只允许 `default`）。
    databases = {"default", "player"}

    def test_admin_endpoints_never_touch_player_database(self) -> None:
        """跑一遍管理员管理接口，玩家库连接上不应当产生任何查询。

        与 `tests/test_players.py::PlayerSourceIsolationTests` 同一手法：
        用 `CaptureQueriesContext` 挂在**玩家库连接**上数 SQL。
        管理员账号是平台的表，这条路径上一条玩家库查询都不该有。
        """
        from django.db import connections
        from django.test.utils import CaptureQueriesContext

        super_admin = create_super()
        target = create_operator()
        client = APIClient()
        client.force_authenticate(user=super_admin)

        with CaptureQueriesContext(connections["player"]) as captured:
            client.get(LIST_URL)
            client.get(OVERVIEW_URL)
            client.get(detail_url(target.pk))
            client.post(
                LIST_URL,
                {
                    "username": "isolation-check",
                    "email": "isolation@platform.local",
                    "password": NEW_PASSWORD,
                },
                format="json",
            )

        self.assertEqual(len(captured.captured_queries), 0, captured.captured_queries)
