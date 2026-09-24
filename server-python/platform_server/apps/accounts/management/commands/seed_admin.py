"""`manage.py seed_admin` —— 创建/重置初始超级管理员。

为什么需要它：管理平台的账号体系与玩家账号完全隔离，所以**没有任何现成的
玩家账号可以拿来登录后台**。全新部署时如果不先建一个管理员，登录接口永远
返回"账号或密码错误"，人会被挡在门外。

行为：

* 默认幂等——账号已存在就**不改口令**，只补角色/启用状态；
* 加 `--reset-password` 才重置口令（用于忘记口令的救急）；
* 口令来源优先级：`--password` > 环境变量 `PLATFORM_ADMIN_PASSWORD` >
  随机生成并打印一次。

安全：口令只在这里打印/传入，不写日志文件；`--password` 会留在 shell 历史里，
生产建议用环境变量或交互式输入。
"""

from __future__ import annotations

import secrets
import string
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.accounts.models import AdminUser

#: 随机口令使用的字符集：去掉容易看混的 0/O/1/l/I。
PASSWORD_ALPHABET = "".join(
    ch for ch in string.ascii_letters + string.digits if ch not in "0O1lI"
)
PASSWORD_LENGTH = 16


def generate_password() -> str:
    """生成一次性随机口令。"""
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))


class Command(BaseCommand):
    """创建或修复初始超级管理员账号。"""

    help = "创建管理平台的初始超级管理员（幂等；口令默认不覆盖）"

    def add_arguments(self, parser: CommandParser) -> None:
        """声明命令行参数。"""
        parser.add_argument(
            "--username",
            default="admin",
            help="管理员账号（默认 admin）",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="口令；不传则读环境变量 PLATFORM_ADMIN_PASSWORD，再否则随机生成",
        )
        parser.add_argument(
            "--nickname",
            default="超级管理员",
            help="昵称（默认 超级管理员）",
        )
        parser.add_argument(
            "--email",
            default="",
            help="邮箱；不传则用 <username>@platform.local 占位",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="账号已存在时也重置口令（救急用）",
        )

    def handle(self, *args: Any, **options: Any) -> str:
        """执行创建/修复。"""
        username: str = options["username"].strip()
        if not username:
            self.stderr.write(self.style.ERROR("账号不能为空"))
            return "failed"

        email: str = options["email"].strip() or f"{username}@platform.local"
        nickname: str = options["nickname"]
        reset: bool = options["reset_password"]

        existing = AdminUser.objects.filter(username=username).first()

        if existing is not None:
            # 已存在：默认只补角色与启用状态，**不动口令**。
            changed_fields: list[str] = []
            if existing.role != AdminUser.Role.SUPER_ADMIN:
                existing.role = AdminUser.Role.SUPER_ADMIN
                changed_fields.append("role")
            if not existing.is_superuser:
                existing.is_superuser = True
                existing.is_staff = True
                changed_fields.extend(["is_superuser", "is_staff"])
            if existing.status != AdminUser.Status.ACTIVE:
                existing.status = AdminUser.Status.ACTIVE
                changed_fields.append("status")

            if reset:
                raw = options["password"] or generate_password()
                existing.set_password(raw)
                changed_fields.append("password")

            if changed_fields:
                # `save()` 会同步 is_active，所以 status 变了也必须走全量 save。
                existing.save()
                self.stdout.write(
                    self.style.WARNING(
                        f"账号已存在，已更新：{', '.join(sorted(set(changed_fields)))}"
                    )
                )
            else:
                self.stdout.write(self.style.WARNING("账号已存在，未做任何修改"))

            if reset:
                self._print_password(username, raw)
            else:
                self.stdout.write("（口令未改动；忘记口令请加 --reset-password）")
            return "ok"

        raw_password = options["password"] or self._password_from_env() or generate_password()
        AdminUser.objects.create_superuser(
            username=username,
            password=raw_password,
            email=email,
            nickname=nickname,
        )
        self.stdout.write(self.style.SUCCESS(f"已创建超级管理员：{username}"))
        self._print_password(username, raw_password)
        return "ok"

    def _password_from_env(self) -> str | None:
        """从环境变量读口令。"""
        import os

        value = os.environ.get("PLATFORM_ADMIN_PASSWORD", "").strip()
        return value or None

    def _print_password(self, username: str, password: str) -> None:
        """提示口令。"""
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("  登录信息（请立即保存，口令不会再次显示）"))
        self.stdout.write(f"    账号：{username}")
        self.stdout.write(f"    口令：{password}")
        self.stdout.write("")
        self.stdout.write("  登录页：http://127.0.0.1:5173/  （前端 dev server）")
        self.stdout.write("")
