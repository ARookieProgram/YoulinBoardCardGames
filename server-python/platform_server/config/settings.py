"""管理平台（游戏后台）的 Django 配置。

与 `server-python/` 的账号服/大厅服/游戏服**没有任何运行时耦合**：

* 跑在独立进程、独立端口（默认 8000），不是客户端连的 9000/9001/10000；
* 用**独立的数据库** `db_scmj_admin`，管理员表与玩家表物理隔离；
* 管理员口令用 Django 的 PBKDF2 哈希，而玩家侧 `t_accounts.password` 是明文
  （那是游戏的历史实现，管理平台不去碰它，也不复用它的表）。

配置项一律从环境变量读取，默认值只服务于本机开发。可用变量见
`platform_server/.env.example`。
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

# ---------------------------------------------------------------- 路径

#: `platform_server/` 目录（本文件在 `platform_server/config/settings.py`）。
BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str) -> str:
    """读取字符串环境变量，未设置时用默认值。"""
    return os.environ.get(name, default)


def env_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量，接受 1/true/yes/on（大小写不敏感）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    """读取逗号分隔的列表环境变量，自动去掉空项与首尾空格。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


# ---------------------------------------------------------------- 基础

#: 会话/CSRF 签名密钥。生产必须通过环境变量提供固定值，否则重启即失效。
SECRET_KEY = env(
    "PLATFORM_SECRET_KEY",
    "dev-only-insecure-key-change-me-in-production",
)

#: 调试开关。默认开启方便本机开发；生产用 PLATFORM_DEBUG=0 关掉。
DEBUG = env_bool("PLATFORM_DEBUG", True)

#: 允许访问的主机名/IP。开发时默认放开，生产必须收窄。
ALLOWED_HOSTS = env_list("PLATFORM_ALLOWED_HOSTS", ["*"])

# ---------------------------------------------------------------- 应用

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",  # 退出登录要吊销 refresh token
    "corsheaders",
    # 本方
    "apps.accounts",
    "apps.players",
    # 房间管理没有模型（房间数据在玩家库里，只读），注册进来是为了统一目录约定。
    "apps.rooms",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # 必须在 CommonMiddleware 之前
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------- 数据库
#
# 管理平台与玩家库**物理隔离**：默认连 db_scmj_admin，不是 db_scmj。
# `PLATFORM_DB_ENGINE=sqlite` 时退化成单文件 SQLite，只用于跑测试和没有
# MySQL 的机器上验证登录流程（见 README「验证」一节）。

DB_ENGINE = env("PLATFORM_DB_ENGINE", "mysql").strip().lower()

if DB_ENGINE == "sqlite":
    # SQLite 不会自动创建父目录，缺目录时报的是"unable to open database file"，
    # 很难看出是路径问题，所以这里主动建一次。
    _sqlite_path = Path(
        env("PLATFORM_SQLITE_PATH", str(BASE_DIR / "var" / "platform_dev.sqlite3"))
    )
    _sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(_sqlite_path),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("PLATFORM_DB_NAME", "db_scmj_admin"),
            "USER": env("PLATFORM_DB_USER", "root"),
            "PASSWORD": env("PLATFORM_DB_PASSWORD", "li663399"),
            "HOST": env("PLATFORM_DB_HOST", "127.0.0.1"),
            "PORT": env("PLATFORM_DB_PORT", "3306"),
            # 管理员口令哈希、用户名等都可能是四字节字符，库/表统一 utf8mb4。
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# ---------------------------------------------------------------- 玩家库（只读数据源）
#
# 玩家管理要展示 `t_users` 里的账号 / 昵称 / 房卡（`gems`）/ 金币，这些表在**玩家库**
# `db_scmj` 里。按 `AGENTS.md` §2 第 5 条，这里显式声明一条**只读**数据源：
#
# * 管理平台的模型与迁移**不落在这个库上**（本库是 `db_scmj_admin`）；
# * `apps/players/player_source.py` 是唯一读它的地方，且只执行 SELECT；
# * 不 import 游戏服的 `utils/db.py`，也不复用它的连接池——那是游戏服的访问层。
#
# 默认跟随主库引擎：`PLATFORM_DB_ENGINE=sqlite` 时它也是 sqlite，
# 保证"没有 MySQL 也能把平台跑起来"这条路径继续成立。
PLAYER_DB_ENGINE = env("PLATFORM_PLAYER_DB_ENGINE", DB_ENGINE).strip().lower()

if PLAYER_DB_ENGINE == "sqlite":
    _player_sqlite_path = Path(
        env("PLATFORM_PLAYER_SQLITE_PATH", str(BASE_DIR / "var" / "player_dev.sqlite3"))
    )
    _player_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES["player"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(_player_sqlite_path),
        # 离线开发库由 `manage.py init_player_dev` 建表并塞样例数据，
        # 它不是 Django 迁移的一部分（本平台在玩家库里没有任何模型）。
        "TEST": {"NAME": None},
    }
else:
    DATABASES["player"] = {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("PLATFORM_PLAYER_DB_NAME", "db_scmj"),
        "USER": env("PLATFORM_PLAYER_DB_USER", env("PLATFORM_DB_USER", "root")),
        "PASSWORD": env("PLATFORM_PLAYER_DB_PASSWORD", env("PLATFORM_DB_PASSWORD", "li663399")),
        "HOST": env("PLATFORM_PLAYER_DB_HOST", env("PLATFORM_DB_HOST", "127.0.0.1")),
        "PORT": env("PLATFORM_PLAYER_DB_PORT", env("PLATFORM_DB_PORT", "3306")),
        # 只读用途也要显式 utf8mb4：昵称入库前是 Base64，但账号与房间号里可能有四字节字符。
        "OPTIONS": {"charset": "utf8mb4"},
        # 生产建议给这个连接配一个只有 SELECT 权限的 MySQL 账号；
        # 应用层的只读校验（player_source._assert_read_only）只是第二道防线。
        "TEST": {"NAME": None},
    }

#: 自定义用户模型：**管理平台自己的账号表**，与 `t_accounts` / `t_users` 无关。
AUTH_USER_MODEL = "accounts.AdminUser"

# ---------------------------------------------------------------- 内部接口密钥
#
# `/api/internal/...` 下的接口是**给游戏服（账号服以外的两个进程）调用的**，不走 JWT：
# 游戏服没有管理平台账号，调用时用 `md5(参数 + 本密钥)` 证明身份。
#
#   * 游戏服侧的配置在 `server-python/configs_*.py` / `server/configs_*.ts` 的
#     `ban_check()["PRI_KEY"]`，**两边必须逐字一致**（默认值都是本机开发用的串）；
#   * 生产必须换成随机长串，并让平台与游戏服同时更新——**改一侧会让校验全部变成
#     10003，而游戏服是 fail-open，表现为"封禁静默失效"**，所以改完要看日志；
#   * 留空表示"不开放内部接口"：此时任何调用都返回 10500，而不是放行——
#     未配置密钥绝不能变成一个人人可用的公开接口。
PLATFORM_INTERNAL_KEY = env("PLATFORM_INTERNAL_KEY", "scmj-ban-check-dev-key")

#: 内部接口的路径前缀。游戏服侧拼的也是这个前缀，改一处要同步另一处。
PLATFORM_INTERNAL_PREFIX = "api/internal"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

#: 口令哈希算法：PBKDF2-SHA256 是 Django 默认且无需额外依赖。
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# ---------------------------------------------------------------- 国际化

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "var" / "static"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- DRF

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # 默认全部要求登录，需要公开的接口在视图上显式 AllowAny。
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    # 统一响应外壳（{code, message, data}），见 apps/common/response.py。
    "EXCEPTION_HANDLER": "apps.common.exceptions.platform_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DATETIME_FORMAT": "%Y-%m-%d %H:%M:%S",
}

# ---------------------------------------------------------------- JWT

SIMPLE_JWT = {
    # access 短、refresh 长；前端用 refresh 换新 access。
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("PLATFORM_ACCESS_TOKEN_MINUTES", "120"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("PLATFORM_REFRESH_TOKEN_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,  # 由登录视图自己记录（要带 IP）
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("PLATFORM_JWT_SIGNING_KEY", SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "admin_id",
    "TOKEN_TYPE_CLAIM": "token_type",
}

# ---------------------------------------------------------------- CORS
#
# 前端 Vite dev server 与 Django 不同源（5173 vs 8000），浏览器需要 CORS。
# 生产建议把前端构建产物交给同一个反向代理，不必依赖这里。

CORS_ALLOWED_ORIGINS = env_list(
    "PLATFORM_CORS_ORIGINS",
    [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
)
CORS_ALLOW_CREDENTIALS = True

#: 反向代理层数与 HTTPS 判定交给部署环境，这里只在显式开启时使用。
if env_bool("PLATFORM_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------- 生产安全项
#
# 只在 DEBUG=0 时启用：本机开发走 http，开了这些会导致重定向到 https 而打不开页面。
# `manage.py check --deploy` 的 W004/W008/W012/W016 就是这几项，
# 生产部署下应当干净（W009 关于 SECRET_KEY 的告警请靠环境变量解决，不要改这里）。

if not DEBUG:
    # 全站 HTTPS 由反向代理或应用层强制。
    SECURE_SSL_REDIRECT = env_bool("PLATFORM_SECURE_SSL_REDIRECT", True)
    # Cookie 只在 HTTPS 上传输。
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # 会话 Cookie 不允许 JS 读取（Django 默认已是 True，这里显式写清依赖）。
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False  # 前端要读 csrftoken 时保持可读；本平台用 JWT，不受影响
    SESSION_COOKIE_SAMESITE = "Lax"
    # HSTS：默认关闭，确认全站 HTTPS 后再按需开启（例如 31536000 = 一年）。
    # 开错会造成"浏览器长期拒绝 http 访问"，属于不可逆操作，所以不设默认值。
    SECURE_HSTS_SECONDS = int(env("PLATFORM_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = env_bool("PLATFORM_HSTS_PRELOAD", False)

# ---------------------------------------------------------------- 日志

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("PLATFORM_LOG_LEVEL", "INFO")},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
