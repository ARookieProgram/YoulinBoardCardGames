#!/usr/bin/env python
"""管理平台（游戏后台）的 Django 命令行入口。

与 `server-python/` 下的三进程完全独立：这里跑的是**管理平台**的后端，
不是游戏客户端连的账号服/大厅服/游戏服。两者的账号体系物理隔离，
见 `platform_server/README.md`。

用法（必须在 `server-python/platform_server/` 目录下执行）::

    ../.venv/bin/python manage.py migrate          # 建表（需要 MySQL 里的 db_scmj_admin）
    ../.venv/bin/python manage.py seed_admin       # 建初始超级管理员
    ../.venv/bin/python manage.py runserver 0.0.0.0:8000
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """按环境变量选择配置模块并执行 Django 命令。"""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - 只在缺失依赖时触发
        raise ImportError(
            "无法导入 Django。请先用 server-python/.venv 安装依赖："
            "../.venv/bin/pip install -r requirements-platform.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
