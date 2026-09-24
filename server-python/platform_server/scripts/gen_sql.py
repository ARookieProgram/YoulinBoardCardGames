#!/usr/bin/env python
"""`manage.py` 之外的离线工具：生成管理平台的 MySQL 建表脚本。

**为什么需要它**：正常部署是 `manage.py migrate`，Django 自己去建表，不需要 SQL 文件。
但运维/评审经常要一份"这个库到底长什么样"的 DDL，而且不能是手抄的——
手抄的 DDL 一旦与模型脱节，建出来的库和 `migrate` 建出来的就不是同一个东西。

所以这里**不自己写 DDL**，而是让 Django 自己生成：

1. 伪造一次 MySQL 8.0 的连接握手（只替换 `get_new_connection`，
   回答后端唯一会查的那一条 `SELECT VERSION(), @@sql_mode, ...`）；
2. 借道 `sqlmigrate`，按**迁移文件**逐条产出 Django 将要执行的 SQL。

结果与 `migrate` 真正执行的语句一致（`sqlmigrate` 用的就是同一套
schema editor）。跑完把输出写进 `sql/db_scmj_admin.sql`，见 `--output`。

用法（必须在 `platform_server/` 目录下）::

    ../.venv/bin/python scripts/gen_sql.py                     # 打印到标准输出
    ../.venv/bin/python scripts/gen_sql.py --output sql/db_scmj_admin.sql

**不需要 MySQL 服务**——这正是本脚本存在的意义之一：CI 与开发机上不必装库
也能核对 schema。

改了模型之后：`makemigrations` → 跑本脚本 → 一起提交。
`README.md` 的「数据库脚本」一节会提醒这件事。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path
from typing import Any

# 让脚本能直接 `python scripts/gen_sql.py` 跑（把 platform_server/ 放进 sys.path）。
PLATFORM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLATFORM_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from io import StringIO  # noqa: E402

#: 假装成哪个 MySQL 版本。8.0 是当前生产使用的版本线；
#: 它决定 `supports_*` 这一批特性开关（例如 CHECK 约束、utf8mb4 排序规则）。
FAKE_SERVER_VERSION = "8.0.36"

#: `mysql_server_data` 只查这一条，按列顺序回一行即可。
SERVER_DATA_SQL_MARKER = "select version()"


class _FakeCursor:
    """够用的假游标。

    要回答两类查询：

    1. **服务器变量探测**（`SELECT VERSION(), @@sql_mode, ...`）——Django 建表前
       会问一次，用来决定用哪些特性（CHECK 约束、AUTO_INCREMENT 写法等）。
    2. **introspection**：`collect_sql` 是"从空库开始重放迁移"，遇到
       `AlterField` 时 Django 仍会去问"这张表现有的约束叫什么"。真实空库里
       答案是"什么都没有"，所以这里一律回空结果——这正是 `migrate` 在空库上
       会遇到的情况，因此产出的 SQL 与实际执行一致。

    第 2 类的调用方会读 `cursor.description`，所以它必须在任何 `execute()` 之后
    都可读（哪怕是空的）。
    """

    def __init__(self) -> None:
        self._row: tuple[Any, ...] | None = None
        self._rows: list[tuple[Any, ...]] = []
        #: introspection 会遍历它来拼字段信息；空表示"没有这个表/没有这些约束"。
        self.description: list[Any] = []

    def execute(self, sql: str, params: Any = None) -> None:
        if SERVER_DATA_SQL_MARKER in sql.lower():
            # VERSION(), @@sql_mode, @@default_storage_engine, @@sql_auto_is_null,
            # @@lower_case_table_names, CONVERT_TZ(...) IS NOT NULL
            self._rows = [
                (
                    FAKE_SERVER_VERSION,
                    "STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION",
                    "InnoDB",
                    0,
                    0,  # lower_case_table_names=0（Linux 默认，区分大小写）
                    1,  # mysql.time_zone 已加载
                )
            ]
        else:
            # 任何 introspection 查询：空库，什么都没有。
            self._rows = []
        self._row = self._rows[0] if self._rows else None

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def close(self) -> None:
        """Django 在 `temporary_connection()` 退出时会调用。"""

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConnection:
    """够用的假连接：只为让版本探测通过。"""

    def cursor(self, *args: Any, **kwargs: Any) -> _FakeCursor:
        return _FakeCursor()

    def close(self) -> None:
        """忽略。"""

    def commit(self) -> None:
        """忽略。"""

    def rollback(self) -> None:
        """忽略。"""


def install_fake_mysql_handshake() -> None:
    """把默认连接的"建连"换成假实现，使 DDL 生成不需要真实 MySQL。"""
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.mysql":
        raise SystemExit(
            "本脚本只在 PLATFORM_DB_ENGINE=mysql（默认）下工作，"
            "否则生成的 DDL 会是 SQLite 方言。"
        )
    connection.get_new_connection = lambda conn_params: _FakeConnection()
    connection.connection = _FakeConnection()


def migration_plan() -> list[tuple[str, str]]:
    """按 migrate 的执行顺序列出 (app_label, migration_name)。

    用 `showmigrations --plan` 的输出解析——它给出的顺序与 `migrate` 一致，
    比手工拼依赖关系可靠。
    """
    out = StringIO()
    call_command("showmigrations", "--plan", stdout=out, no_color=True)
    plan: list[tuple[str, str]] = []
    for line in out.getvalue().splitlines():
        # 形如： "[ ]  accounts.0001_initial"
        text = line.strip()
        if not text.startswith("[") or "." not in text:
            continue
        name = text.split("]", 1)[1].strip()
        app_label, _, migration = name.partition(".")
        if app_label and migration:
            plan.append((app_label, migration))
    return plan


def collect_sql() -> dict[str, str]:
    """逐条迁移产出 SQL，返回 {app_label.migration: sql}。

    `sqlmigrate` 对"没有数据库操作"的迁移（例如只有 `RunPython` 或空迁移）
    会往 stderr 打一行 `No operations found.`——这属于正常情况，
    这里把 stderr 收走，免得生成时刷屏、也免得被误当成失败。
    """
    results: dict[str, str] = {}
    for app_label, migration in migration_plan():
        out = StringIO()
        with contextlib.redirect_stderr(StringIO()):
            call_command("sqlmigrate", app_label, migration, stdout=out, no_color=True)
        results[f"{app_label}.{migration}"] = out.getvalue()
    return results


def strip_comments(sql: str) -> str:
    """去掉 sqlmigrate 打印的注释头（"--\\n-- Create model ...\\n--"）。"""
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    return "\n".join(lines).strip()


def describe_state(model: Any) -> str:
    """把模型的**最终**字段与索引列出来，作为可读的 schema 参考。

    上面那部分是"逐条迁移的真实执行 SQL"，等价于空库 `migrate`，
    因此会包含建完又改的中转语句（例如 `token_blacklist` 的
    `jti` → `jti_hex` → `jti`）。这一段直接读 Django 的最终状态，
    省得别人对着建表语句推算"到底有哪些列"。

    这里是**描述**，不是 DDL，所以不需要（也不应该）手工维护——
    它同样来自模型定义，模型改了这里就跟着变。
    """
    meta = model._meta
    lines = [f"-- 表：`{meta.db_table}`（{meta.verbose_name}）"]
    lines.append("-- 字段：")
    for field in meta.local_fields:
        flags: list[str] = []
        if field.primary_key:
            flags.append("主键")
        if getattr(field, "unique", False):
            flags.append("唯一")
        if getattr(field, "db_index", False):
            flags.append("索引")
        if getattr(field, "null", False):
            flags.append("可空")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        columns = [field.column]
        # 外键列名带 _id，单独标注指向哪张表，免得看的人还要去翻模型。
        if field.is_relation and field.related_model is not None:
            columns.append(f"→ {field.related_model._meta.db_table}")
        lines.append(f"--   {' / '.join(columns):<28} {field.get_internal_type()}{suffix}")
    if meta.indexes:
        lines.append("-- 组合索引：")
        for index in meta.indexes:
            lines.append(f"--   {index.name:<28} ({', '.join(index.fields)})")
    return "\n".join(lines)


#: 管理平台自己的 app（末尾的 schema 速查按这个顺序罗列）。
#: 新增业务模块时把 label 加进来，否则速查段会漏掉它的表。
PLATFORM_APP_LABELS: tuple[str, ...] = ("accounts", "players")


def state_summary() -> str:
    """列出管理平台自己的表（Django 内置表不重复罗列，它们在 DDL 里一目了然）。"""
    from django.apps import apps

    sections = []
    for label in PLATFORM_APP_LABELS:
        for model in apps.get_app_config(label).get_models():
            sections.append(describe_state(model))
    return "\n\n".join(sections)


def render(per_migration: dict[str, str]) -> str:
    """拼出可直接执行的完整脚本。"""
    db_name = settings.DATABASES["default"]["NAME"]
    rules = "\n".join(f"  {name}\n{strip_comments(sql)}" for name, sql in per_migration.items())

    return f"""-- ============================================================================
-- 幼麟麻将 · 管理平台数据库（{db_name}）
-- ============================================================================
--
-- 本文件由 Django 的迁移自动生成，**不要手工编辑**。
--   生成命令：cd server-python/platform_server && ../.venv/bin/python scripts/gen_sql.py \\
--               --output sql/db_scmj_admin.sql
--   自检命令：../.venv/bin/python manage.py test tests.test_sql_script
--
-- 权威定义是 Django 的迁移文件（apps/*/migrations/）：
-- 改了模型 → `makemigrations` → 重新生成本文件 → 一起提交。
--
-- ⚠️ 这是"初始建库"脚本，等价于在**空库**上跑一次 `migrate`。
--    已有数据的库升级请用 `manage.py migrate`，不要重跑本文件
--    （Django 靠 django_migrations 表判断哪些迁移已应用，重跑会撞表）。
--
-- 内容分三部分：
--   1. 建库语句；
--   2. 逐条迁移的真实执行 SQL（与 `migrate` 实际执行的语句一致，
--      因此会有"建完又改"的中转语句，例如 token_blacklist 的 jti 列）；
--   3. 最终 schema 速查（只是注释，方便阅读，不执行）。
--
-- 与玩家库 `db_scmj` 隔离：本库只放管理平台的账号与登录态，
-- 不含 t_accounts / t_users 等玩家表。玩家数据由平台通过**只读数据源**
-- （Django 的 DATABASES['player']，只执行 SELECT）读取，不落在本库。
-- 玩家封禁记录是本平台的表（players_playerban），同理不落到玩家库。
--
-- 目标：MySQL 8.0+ / utf8mb4
-- ============================================================================

-- 建库（已存在时跳过）。字符集必须 utf8mb4：管理员昵称、备注可能是四字节字符。
CREATE DATABASE IF NOT EXISTS `{db_name}`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `{db_name}`;

-- 建表期间不校验外键，避免因表的创建顺序导致失败（与原 db_babykylin.sql 同一手法）。
SET FOREIGN_KEY_CHECKS=0;

{rules}

SET FOREIGN_KEY_CHECKS=1;

-- ============================================================================
-- 最终 schema 速查（注释，仅供阅读；实际结构以上面的 DDL 为准）
-- ============================================================================

{state_summary()}

-- ============================================================================
-- 完成。
--
-- 建完还需要一个能登录的超级管理员——SQL 里不含口令（口令是 PBKDF2 哈希，
-- 必须在应用层生成），所以请接着执行：
--
--   cd server-python/platform_server
--   ../.venv/bin/python manage.py seed_admin --username admin
-- ============================================================================
"""


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="生成管理平台的 MySQL 建表脚本")
    parser.add_argument(
        "--output",
        default=None,
        help="写入的文件（相对于 platform_server/ 或绝对路径）；不传则打印到标准输出",
    )
    args = parser.parse_args()

    install_fake_mysql_handshake()
    per_migration = collect_sql()
    script = render(per_migration)

    if args.output:
        target = Path(args.output)
        if not target.is_absolute():
            target = PLATFORM_DIR / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
        print(f"已生成 {target}（{len(per_migration)} 条迁移）", file=sys.stderr)
    else:
        print(script)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
