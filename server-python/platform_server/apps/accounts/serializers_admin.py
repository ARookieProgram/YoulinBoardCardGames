"""管理员账号管理（`/api/admins/`）的入参校验与出参形状。

**入参**用 DRF 序列化器校验（非法参数映射成 `ERR_BAD_REQUEST` = 10001）；
**出参**统一走 `serializers.AdminUserSerializer`——登录响应与管理页展示的是
同一张表，形状只留一份，省得两边漂移。

三条口径（改之前先读）：

1. **口令强度用 Django 的 `AUTH_PASSWORD_VALIDATORS`**
   （`config/settings.py`：长度 ≥ 8、不能是常见口令、不能全数字、不能与账号/邮箱太像）。
   校验失败是**参数问题**（10001），不是业务错误，所以转成 DRF 的 `ValidationError`；
   而"账号名重复""邮箱重复"这类有明确业务语义的错误走类型化异常（15xxx），
   原因见 `apps/common/exceptions.py` 的 `LoginFailed` 注释。
2. **账号名不可改**。登录 claim 里带着 `username` 快照，改名会让历史日志与
   令牌里的名字对不上；确实要换名字就"新建一个 + 停用旧的"。
3. **判重是大小写不敏感的**（账号名与邮箱都是）。登录本身大小写不敏感
   （`LoginSerializer` 用 `username__iexact` 查），允许 `Admin` 与 `admin` 并存
   会让"到底登进哪一行"变得不确定。
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.common.pagination import PAGE_SIZE_MAX

from .exceptions import AdminEmailTaken, AdminOldPasswordIncorrect, AdminUsernameTaken
from .models import AdminUser
from .serializers import AdminUserSerializer

# ---------------------------------------------------------------- 列表取值

#: 列表页"全部角色 / 全部状态"的取值（与前端 `admins.ts` 的常量一致）。
ADMIN_ROLE_ALL = "all"
ADMIN_STATUS_ALL = "all"

#: 角色过滤的候选项：`all` + 模型上的三个角色。
ROLE_FILTER_CHOICES: tuple[tuple[str, str], ...] = (
    (ADMIN_ROLE_ALL, "全部"),
    *AdminUser.Role.choices,
)

#: 状态过滤的候选项：`all` + 模型上的两个状态。
STATUS_FILTER_CHOICES: tuple[tuple[str, str], ...] = (
    (ADMIN_STATUS_ALL, "全部"),
    *AdminUser.Status.choices,
)

#: 排序键与其中文说明。列表默认按创建时间倒序。
ADMIN_ORDERING_CHOICES: dict[str, str] = {
    "-created_at": "创建时间从新到旧",
    "created_at": "创建时间从旧到新",
    "username": "账号名",
    "-last_login": "最后登录从新到旧",
    "role": "角色",
}

#: 默认排序。
DEFAULT_ORDERING = "-created_at"


def validate_password_strength(password: str, *, username: str = "", email: str = "") -> str:
    """用 Django 的口令校验器检查强度，失败时按参数错误抛出。

    模拟一个 `AdminUser` 实例传给校验器，是因为 `UserAttributeSimilarityValidator`
    需要拿账号 / 邮箱做相似度比较（没有 user 时它会跳过这一项）。

    :raises rest_framework.serializers.ValidationError: 强度不足（→ 10001）。
    """
    candidate = AdminUser(username=username, email=email)
    try:
        password_validation.validate_password(password, candidate)
    except DjangoValidationError as exc:
        # Django 的 ValidationError 不在 DRF 的异常链上（会变成 500），
        # 这里显式转成 DRF 的参数错误，业务码由统一处理器映射成 10001。
        raise serializers.ValidationError(list(exc.messages)) from exc
    return password


def check_username_available(username: str) -> str:
    """账号名合法且未被占用时返回它，否则抛出。

    :raises rest_framework.serializers.ValidationError: 账号名不合法（→ 10001）。
    :raises AdminUsernameTaken: 已被占用（→ 15002）。
    """
    # 复用模型字段上的 UnicodeUsernameValidator，口径与 Django 一致
    # （长度、允许的字符集），避免自己再写一套正则。
    for validator in AdminUser._meta.get_field("username").validators:
        try:
            validator(username)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
    if AdminUser.objects.filter(username__iexact=username).exists():
        raise AdminUsernameTaken(username)
    return username


def check_email_available(email: str, *, exclude_pk: int | None = None) -> str:
    """邮箱未被其他管理员占用时返回它，否则抛出。

    :param exclude_pk: 改资料时排除自己，否则"不改邮箱的保存"会被自己挡住。
    :raises AdminEmailTaken: 已被占用（→ 15003）。
    """
    queryset = AdminUser.objects.filter(email__iexact=email)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    if queryset.exists():
        raise AdminEmailTaken(email)
    return email


# ---------------------------------------------------------------- 入参


class AdminListQuerySerializer(serializers.Serializer[Any]):
    """`GET /api/admins/` 的查询参数。"""

    keyword = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        default="",
        help_text="账号 / 昵称 / 邮箱（子串匹配，大小写不敏感）",
    )
    role = serializers.ChoiceField(
        choices=ROLE_FILTER_CHOICES,
        required=False,
        default=ADMIN_ROLE_ALL,
    )
    status = serializers.ChoiceField(
        choices=STATUS_FILTER_CHOICES,
        required=False,
        default=ADMIN_STATUS_ALL,
    )
    ordering = serializers.ChoiceField(
        choices=sorted(ADMIN_ORDERING_CHOICES),
        required=False,
        default=DEFAULT_ORDERING,
    )
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=PAGE_SIZE_MAX,
        default=20,
    )


class AdminCreateSerializer(serializers.Serializer[Any]):
    """`POST /api/admins/` 的入参。

    刻意**没有 `status` 字段**：新建的账号一律是启用状态，要停用请建完之后
    在列表上点状态开关。这样少一条"新账号一出生就是停用的"这种诡异路径，
    也避开 `create_superuser()` 会强制把 `status` 覆写成启用这件事。
    """

    username = serializers.CharField(
        max_length=150,
        trim_whitespace=True,
        error_messages={"blank": "请输入账号", "required": "请输入账号"},
    )
    nickname = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
        default="",
        help_text="昵称（展示用，可留空）",
    )
    email = serializers.EmailField(
        max_length=254,
        error_messages={"blank": "请输入邮箱", "required": "请输入邮箱", "invalid": "邮箱格式不正确"},
    )
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
        error_messages={"blank": "请输入密码", "required": "请输入密码"},
    )
    role = serializers.ChoiceField(
        choices=AdminUser.Role.choices,
        required=False,
        default=AdminUser.Role.OPERATOR,
    )
    remark = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        default="",
        help_text="备注（为什么给他开这个号，便于日后审计）",
    )

    def validate_username(self, value: str) -> str:
        """账号名合法性 + 大小写不敏感判重。"""
        return check_username_available(value)

    def validate_email(self, value: str) -> str:
        """邮箱判重。"""
        return check_email_available(value)

    def validate_password(self, value: str) -> str:
        """口令强度按 Django 校验器判定。"""
        return validate_password_strength(
            value,
            username=str(self.initial_data.get("username", "") or ""),
            email=str(self.initial_data.get("email", "") or ""),
        )


class AdminUpdateSerializer(serializers.Serializer[Any]):
    """`PATCH /api/admins/<id>/` 的入参（资料与角色）。

    **不含 `username` 与 `password`**：前者不可改（见模块文档），
    后者走专门的 `POST /api/admins/<id>/password/`（重置口令要单独记日志与吊销令牌）。
    状态也不在这里改，走 `POST /api/admins/<id>/status/`。
    """

    nickname = serializers.CharField(required=False, allow_blank=True, max_length=32)
    email = serializers.EmailField(required=False, max_length=254)
    role = serializers.ChoiceField(required=False, choices=AdminUser.Role.choices)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_email(self, value: str) -> str:
        """邮箱判重时排除自己。"""
        instance = self.instance
        exclude_pk = instance.pk if isinstance(instance, AdminUser) else None
        return check_email_available(value, exclude_pk=exclude_pk)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """一个字段都没传时明确报错，而不是静默返回成功。"""
        if not attrs:
            raise serializers.ValidationError("没有需要修改的字段")
        return attrs


class AdminStatusSerializer(serializers.Serializer[Any]):
    """`POST /api/admins/<id>/status/` 的入参。"""

    status = serializers.ChoiceField(
        choices=AdminUser.Status.choices,
        error_messages={"invalid_choice": "状态只能是 active 或 disabled"},
    )


class AdminPasswordSerializer(serializers.Serializer[Any]):
    """`POST /api/admins/<id>/password/` 的入参：超级管理员给他人重置口令。"""

    new_password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
        error_messages={"blank": "请输入新密码", "required": "请输入新密码"},
    )

    def validate_new_password(self, value: str) -> str:
        """口令强度按 Django 校验器判定。"""
        instance = self.instance
        username = instance.username if isinstance(instance, AdminUser) else ""
        email = instance.email if isinstance(instance, AdminUser) else ""
        return validate_password_strength(value, username=username, email=email)


class SelfPasswordSerializer(serializers.Serializer[Any]):
    """`POST /api/admins/me/password/` 的入参：本人改口令，必须带原口令。"""

    old_password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
        error_messages={"blank": "请输入原密码", "required": "请输入原密码"},
    )
    new_password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
        error_messages={"blank": "请输入新密码", "required": "请输入新密码"},
    )

    def validate_new_password(self, value: str) -> str:
        """口令强度按 Django 校验器判定，并拒绝与原口令相同。"""
        admin = self._admin()
        if admin is not None:
            if admin.check_password(value):
                raise serializers.ValidationError("新密码不能与原密码相同")
            return validate_password_strength(value, username=admin.username, email=admin.email)
        return validate_password_strength(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """核对原口令。

        原口令错误抛的是类型化异常 `AdminOldPasswordIncorrect`（15006），
        而不是参数错误：前端要区分"原密码填错了"与"新密码强度不够"。
        """
        admin = self._admin()
        if admin is not None and not admin.check_password(attrs["old_password"]):
            raise AdminOldPasswordIncorrect()
        return attrs

    def _admin(self) -> AdminUser | None:
        """从视图注入的 context 取当前管理员。"""
        admin = self.context.get("admin")
        return admin if isinstance(admin, AdminUser) else None


# ---------------------------------------------------------------- 出参


def admin_row(admin: AdminUser) -> dict[str, Any]:
    """一行管理员（列表 / 详情 / 创建 / 改状态的返回形状全都用它）。"""
    return dict(AdminUserSerializer(admin).data)
