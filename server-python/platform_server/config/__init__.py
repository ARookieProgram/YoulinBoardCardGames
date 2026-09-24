"""管理平台 Django 工程配置包。

`settings.py` 是唯一配置来源；数据库等敏感项从环境变量读取，
默认值只用于本机开发（与 `server-python/configs_mac.py` 的约定一致）。

**这一层只做一件事**：把 PyMySQL 注册成 MySQLdb。
Django 的 `django.db.backends.mysql` 在 import 时会 `import MySQLdb`，
而本工程用的是纯 Python 的 PyMySQL（与 `server-python/utils/db.py` 同一个驱动，
不需要在开发机上编译 mysqlclient）。注册必须在 Django 读 settings 之前完成，
所以放在包的 `__init__` 里——`DJANGO_SETTINGS_MODULE=config.settings`
会先 import `config` 包本身。
"""

from __future__ import annotations

# Django 6.1 的 mysql 后端会检查 `Database.version_info < (2, 2, 1)`。
# PyMySQL（最新 1.2.x）为了避免被拒，**故意把 `version_info`/`__version__` 报成
# `2.2.8`**，真实版本在 `pymysql.VERSION = (1, 2, 3, ...)`，所以这里不需要再打
# 猴子补丁去伪造版本号。（也正因如此，依赖清单里必须写 `PyMySQL>=1.2,<2`，
# 写 `>=2.2` 在 PyPI 上根本不存在——见 requirements-platform.txt 的说明。）
import pymysql

pymysql.install_as_MySQLdb()
