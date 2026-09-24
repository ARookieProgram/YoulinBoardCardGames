"""建库 SQL 脚本（`sql/db_scmj_admin.sql`）的自检。

这个文件是**由迁移生成的产物**，最容易出的问题是"模型改了、SQL 忘了重新生成"，
于是一份过期脚本在评审/建库时被当成事实。这里把"脚本与模型一致"钉成断言。

测试全部是**纯只读**的：只读已提交的 `.sql` 文件，不连数据库、不执行迁移，
所以 SQLite / MySQL 两种设置下都能跑：

    cd server-python/platform_server
    PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test tests.test_sql_script
"""

from __future__ import annotations

import re
from pathlib import Path

from django.apps import apps

from django.test import SimpleTestCase

#: 已提交的建库脚本。
SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "db_scmj_admin.sql"

#: 空库 `migrate` 之后应当存在的表（Django 自建 django_migrations，不在脚本里）。
EXPECTED_TABLES = {
    # 管理平台自己的表
    "accounts_adminuser",
    "accounts_adminuser_groups",
    "accounts_adminuser_user_permissions",
    # Django 内置
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
    "django_admin_log",
    "django_content_type",
    "django_session",
    # JWT 黑名单（退出登录靠它）
    "token_blacklist_blacklistedtoken",
    "token_blacklist_outstandingtoken",
}


class SqlScriptTests(SimpleTestCase):
    """校验脚本本身的内容契约。"""

    def setUp(self) -> None:
        self.sql = SQL_FILE.read_text(encoding="utf-8")

    def test_script_exists_and_is_not_empty(self) -> None:
        """脚本必须存在且非空。"""
        self.assertTrue(SQL_FILE.is_file(), f"缺少建库脚本：{SQL_FILE}")
        self.assertGreater(len(self.sql), 1000)

    def test_creates_every_expected_table(self) -> None:
        """每个应有的表都有 CREATE TABLE。"""
        created = set(re.findall(r"CREATE TABLE `([a-z_]+)`", self.sql))
        missing = EXPECTED_TABLES - created
        self.assertFalse(missing, f"脚本缺少这些表：{sorted(missing)}")

    def test_creates_database_with_utf8mb4(self) -> None:
        """建库语句必须显式 utf8mb4（否则四字节昵称会写不进去）。"""
        self.assertRegex(self.sql, r"CREATE DATABASE IF NOT EXISTS `db_scmj_admin`")
        self.assertIn("utf8mb4", self.sql)

    def test_admin_table_covers_every_model_field(self) -> None:
        """`accounts_adminuser` 的列必须**逐个覆盖**模型的字段。

        这是"模型改了、SQL 忘了重新生成"最直接、也最可靠的探针：
        新增 / 删除 / 重命名字段都会让它失败。

        刻意**不用** `makemigrations --check` 那套自动检测器来做这件事：
        它要读 `django_migrations` 表（`SimpleTestCase` 禁止数据库访问），
        而离线的检测器实现容易给出假阳性（曾误报过**全部**第三方 app，
        同时 `makemigrations --check` 在有库时明确回答 "No changes detected"）。
        "脚本是否与迁移一致"的权威判据是 `scripts/check_sql_fresh.sh`：
        它重新生成一遍再逐字节比对——那才是定义本身。
        """
        admin_model = apps.get_model("accounts", "AdminUser")
        expected_columns = {field.column for field in admin_model._meta.local_fields}

        match = re.search(r"CREATE TABLE `accounts_adminuser` \((.*?)\);", self.sql, re.S)
        self.assertIsNotNone(match, "脚本里没有 accounts_adminuser 的建表语句")
        assert match is not None  # 让类型检查器知道下面可以取 group
        body = match.group(1)
        actual_columns = set(
            re.findall(
                r"`([a-z_]+)`\s+(?:bigint|integer|varchar|char|bool|datetime|longtext|smallint)",
                body,
            )
        )

        missing = expected_columns - actual_columns
        self.assertFalse(
            missing,
            f"accounts_adminuser 缺少列 {sorted(missing)}——"
            "模型改了之后请重新生成脚本（见脚本头的生成命令）",
        )
        extra = actual_columns - expected_columns
        self.assertFalse(
            extra,
            f"accounts_adminuser 多出列 {sorted(extra)}——模型删了字段但脚本没更新",
        )

    def test_admin_table_has_composite_index(self) -> None:
        """模型上声明的组合索引必须出现在脚本里。"""
        admin_model = apps.get_model("accounts", "AdminUser")
        for index in admin_model._meta.indexes:
            self.assertIn(
                f"CREATE INDEX `{index.name}`",
                self.sql,
                f"脚本缺少索引 {index.name}",
            )

    def test_state_summary_lists_model_fields(self) -> None:
        """脚本末尾的"最终 schema 速查"也要跟着模型走。"""
        admin_model = apps.get_model("accounts", "AdminUser")
        for field in admin_model._meta.local_fields:
            self.assertIn(
                f"--   {field.column:<28}",
                self.sql,
                f"速查段缺少字段 {field.column}",
            )

    def test_script_documents_its_own_regeneration(self) -> None:
        """脚本头必须写清"由生成器产出、不要手改、怎么重新生成"。"""
        head = self.sql[:1500]
        self.assertIn("不要手工编辑", head)
        self.assertIn("scripts/gen_sql.py", head)
        self.assertIn("manage.py migrate", head)

    def test_script_has_no_password_or_secret(self) -> None:
        """脚本里不能出现口令/密钥（它是要进版本库的）。"""
        for needle in ("PLATFORM_SECRET_KEY", "PLATFORM_DB_PASSWORD", "pbkdf2_sha256$"):
            self.assertNotIn(needle, self.sql, f"脚本不应包含 {needle}")

    def test_script_isolated_from_player_tables(self) -> None:
        """不得包含玩家侧的表——这是账号体系隔离的底线。"""
        for player_table in ("t_accounts", "t_users", "t_games", "t_rooms", "t_guests"):
            self.assertNotIn(
                f"CREATE TABLE `{player_table}`",
                self.sql,
                f"管理平台脚本不应创建玩家表 {player_table}",
            )
