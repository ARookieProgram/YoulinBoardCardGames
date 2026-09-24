"""管理员模型 —— 管理平台唯一的身份来源。

继承 `AbstractUser` 拿到 Django 现成的口令哈希（PBKDF2）、权限字段与
`last_login`，在此之上补齐后台需要的运营字段（昵称、角色、启用状态、
登录来源 IP）。

**不要**把这个模型和玩家表混为一谈：它落在 `db_scmj_admin` 的
`accounts_adminuser` 表里，`t_accounts` / `t_users` 是另一套东西，
两者只共享"用户名"这个概念，不共享数据。
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class AdminUserManager(BaseUserManager["AdminUser"]):
    """管理员管理器。

    `create_superuser` 会强制 `role=SUPER_ADMIN`——超级管理员是管理平台里
    权限最高的角色，不允许出现"is_superuser=True 但 role=operator"这种
    自相矛盾的行。
    """

    use_in_migrations = True

    def _create_user(self, username: str, password: str | None, **extra: object) -> AdminUser:
        """按 Django 约定创建用户：规范化用户名、哈希口令、落库。"""
        if not username:
            raise ValueError("用户名不能为空")
        username = self.model.normalize_username(username)
        user = self.model(username=username, **extra)
        # `set_password(None)` 会写入不可用口令（Django 的约定），
        # 这样"没有口令的账号"永远登录不上，而不是留一个空口令后门。
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        username: str,
        password: str | None = None,
        **extra: object,
    ) -> AdminUser:
        """创建普通管理员（默认角色 `operator`，默认启用）。"""
        extra.setdefault("role", AdminUser.Role.OPERATOR)
        extra.setdefault("status", AdminUser.Status.ACTIVE)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(username, password, **extra)

    def create_superuser(
        self,
        username: str,
        password: str | None = None,
        **extra: object,
    ) -> AdminUser:
        """创建超级管理员。"""
        extra["role"] = AdminUser.Role.SUPER_ADMIN
        extra["status"] = AdminUser.Status.ACTIVE
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(username, password, **extra)


class AdminUser(AbstractUser):
    """管理平台账号。

    与 `AbstractUser` 的差异：

    * `email` 必填且唯一（后台要能按邮箱找回/通知）；
    * 新增 `role`（角色）与 `status`（启用/禁用）；
    * `is_active` 保留给 Django 用，但**始终与 `status` 同步**（见 `save`），
      业务判断统一读 `is_enabled`，不要两处各判一套。
    """

    class Role(models.TextChoices):
        """管理员角色。数值越大权限越高。"""

        OPERATOR = "operator", "运营"
        ADMIN = "admin", "管理员"
        SUPER_ADMIN = "super_admin", "超级管理员"

    class Status(models.TextChoices):
        """账号状态。"""

        ACTIVE = "active", "启用"
        DISABLED = "disabled", "禁用"

    #: 角色等级，用于"至少 XX 角色"的判断。
    ROLE_LEVELS: dict[str, int] = {
        Role.OPERATOR: 1,
        Role.ADMIN: 2,
        Role.SUPER_ADMIN: 3,
    }

    nickname = models.CharField("昵称", max_length=32, blank=True, default="")
    email = models.EmailField("邮箱", max_length=254, unique=True)
    role = models.CharField(
        "角色",
        max_length=20,
        choices=Role.choices,
        default=Role.OPERATOR,
        db_index=True,
    )
    status = models.CharField(
        "状态",
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    remark = models.CharField("备注", max_length=200, blank=True, default="")
    last_login_ip = models.GenericIPAddressField("最后登录IP", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now, editable=False)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects: AdminUserManager = AdminUserManager()  # type: ignore[assignment,misc]

    class Meta:
        db_table = "accounts_adminuser"
        verbose_name = "管理员"
        verbose_name_plural = "管理员"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["role", "status"], name="idx_admin_role_status"),
        ]

    def __str__(self) -> str:
        return f"{self.username}({self.get_role_display()})"

    def save(self, *args: object, **kwargs: object) -> None:
        """落库前把 `is_active` 与 `status` 对齐。

        Django 的 `ModelBackend` 与 `user_can_authenticate()` 只看 `is_active`，
        而业务表达"禁用"用的是 `status`。两者必须同进同退，否则会出现
        "接口拒了但 Django 认为有效"这类不一致。
        """
        self.is_active = self.status == self.Status.ACTIVE
        super().save(*args, **kwargs)

    # ------------------------------------------------------------ 便捷判断

    @property
    def is_enabled(self) -> bool:
        """账号是否处于启用状态。"""
        return self.status == self.Status.ACTIVE and self.is_active

    @property
    def effective_role(self) -> str:
        """对外展示的角色：`is_superuser` 一律视为超级管理员。

        兜底那些由 `createsuperuser` 之外的历史途径产生、`role` 还没升上来的行。
        """
        if self.is_superuser:
            return self.Role.SUPER_ADMIN
        return self.role

    def has_role_at_least(self, role: str) -> bool:
        """判断角色等级是否不低于 `role`。

        :param role: `Role` 里的取值。
        :return: 满足时返回 `True`。
        """
        current = self.ROLE_LEVELS.get(self.effective_role, 0)
        required = self.ROLE_LEVELS.get(role, 0)
        return current >= required

    @property
    def display_name(self) -> str:
        """优先昵称、否则用户名的展示名。"""
        return self.nickname or self.username
