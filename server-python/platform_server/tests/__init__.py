"""管理平台后端测试包。

用 Django 自带的测试运行器（stdlib 风格，无第三方依赖）：

    cd server-python/platform_server
    ../.venv/bin/python manage.py test

**不需要 MySQL**：测试库由 Django 自己创建。默认按 `settings` 连 MySQL，
所以在没有 MySQL 的机器上跑测试要显式指定 SQLite：

    PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test

这条命令也是仓库根门禁 `npm run check:python` 之外的自查手段——门禁只做
`ast.parse` 语法检查，**不会**跑 Django 的测试（见 README「验证」）。
"""
