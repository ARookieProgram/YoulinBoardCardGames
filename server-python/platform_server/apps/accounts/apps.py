"""`accounts` 应用的 AppConfig。"""

from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """管理平台账号体系。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "管理平台账号"
