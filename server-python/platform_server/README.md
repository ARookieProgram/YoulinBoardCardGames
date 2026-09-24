# 管理平台后端（platform_server）

游戏管理平台的后端，技术栈 **Python 3.14 + Django 6.1 + DRF + SimpleJWT**。

> 这个目录是**管理平台**，不是游戏服务端。游戏服务端是它旁边的三个进程
> （账号服 / 大厅服 / 游戏服，见 `../AGENTS.md`）。两者跑在不同端口、
> 用不同数据库、有一套完全独立的账号体系。

---

## 1. 最重要的一条：账号体系完全隔离

`AdminUser`（管理员）与游戏玩家账号是**两套互不相干的东西**，隔离体现在五个层面：

| 层面 | 管理平台 | 游戏玩家 |
| --- | --- | --- |
| 数据表 | `accounts_adminuser` | `t_accounts` / `t_users` |
| 数据库 | **`db_scmj_admin`**（独立库） | `db_scmj` |
| 登录入口 | `POST /api/auth/login/`（Django，默认 :8000） | 账号服 `POST /login`（aiohttp，:9000） |
| 凭证机制 | JWT（SimpleJWT，HS256） | 自研 md5 签名 token（`game_server/tokenmgr.py`） |
| 口令存储 | Django PBKDF2 哈希 | 明文（历史实现，见下） |

由此推出两条硬结论：

1. **玩家账号无法登录管理平台**。登录查询只落在 `AdminUser` 表上，
   玩家的 `t_accounts` / `t_users` 根本不在 Django 的 ORM 里，物理上不可能命中。
2. **管理员账号不能当游戏账号用**。管理平台不向账号服写入任何数据。

另外，管理平台**刻意不去读写玩家库**，也**不修改/迁移** `t_accounts.password`
的明文存储方式——那是游戏的历史实现，属于 `server/` 与 `server-python/` 的范畴，
在管理平台里"顺手修一下"会造成两套服务端行为不一致。

`tests/test_auth.py::AccountIsolationTests` 把上面两条钉成了断言。

---

## 2. 目录结构

```
server-python/platform_server/
├─ manage.py                    ← Django 命令行入口（migrate / seed_admin / runserver / test）
├─ requirements-platform.txt    ← 本平台额外依赖（Django 等，独立于游戏服务端的 requirements.txt）
├─ .env.example                 ← 环境变量模板（复制成 .env 或直接 export）
├─ config/                      ← Django 工程配置
│   ├─ __init__.py              （把 PyMySQL 注册成 MySQLdb）
│   ├─ settings.py              唯一配置来源（数据库 / JWT / CORS / 日志）
│   ├─ urls.py                  根路由
│   ├─ wsgi.py / asgi.py        部署入口
├─ apps/
│   ├─ common/                  跨模块公共设施
│   │   ├─ response.py          统一响应外壳 {code, message, data}
│   │   ├─ error_codes.py       **全平台唯一**的业务错误码定义
│   │   ├─ exceptions.py        异常 → 响应外壳的翻译 + 业务异常类型
│   │   ├─ pagination.py        统一分页形状
│   │   └─ ip.py                客户端 IP 提取（X-Forwarded-For）
│   └─ accounts/                **管理平台账号体系**
│       ├─ models.py            AdminUser（自定义用户模型）
│       ├─ serializers.py       入参校验 / 认证 / 令牌签发与吊销
│       ├─ views.py             四个登录相关端点
│       ├─ urls.py              /api/auth/ 路由
│       ├─ permissions.py       角色权限类
│       ├─ admin.py             Django admin 站点注册（运维兜底）
│       ├─ error_codes.py       登录相关错误码的转出口
│       └─ management/commands/seed_admin.py   初始超级管理员
├─ sql/db_scmj_admin.sql         ← **生成产物**：MySQL 建库建表脚本（不要手改）
├─ scripts/
│   ├─ run.sh                    启停脚本入口（start/stop/restart/status/logs/init/check）
│   ├─ serve.py                  run.sh 的实现（只依赖标准库）
│   ├─ gen_sql.py                生成上面的 SQL（不需要 MySQL）
│   ├─ check_sql_fresh.sh        校验 SQL 是否与迁移一致（重新生成后比对）
│   └─ e2e_login_check.sh        真实 HTTP 端到端验收（24 项）
├─ tests/test_auth.py            登录闭环接口测试（29 项）
├─ tests/test_sql_script.py      建库脚本的内容自检（9 项）
├─ 合计 `manage.py test`          38 项
└─ scripts/e2e_login_check.sh   真实 HTTP 端到端验收（24 项）
```

---

## 3. 快速开始

### 3.1 建库

管理平台用**独立的库**，与玩家库分开：

```sql
CREATE DATABASE db_scmj_admin
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

### 3.2 安装依赖

本平台复用 `server-python/.venv`（同一个 Python 3.14 环境），
只是多装几个包。**不要**把它和游戏服务端的 `requirements.txt` 混在一起。

```bash
cd server-python
.venv/bin/pip install -r platform_server/requirements-platform.txt
```

> **`PyMySQL` 的版本号有个坑**：它的最新版是 **1.2.x**（不是 2.x）。
> `django/db/backends/mysql/base.py` 里有一句
> `if Database.version_info < (2, 2, 1): raise ImproperlyConfigured(...)`，
> PyMySQL 为了让 Django 放行，**故意把 `version_info` 报成 `(2, 2, 8, ...)`**——
> 真实版本在 `pymysql.VERSION`（`(1, 2, 3, ...)`）。
> 所以按 Django 源码里那个 `(2, 2, 1)` 去写 `PyMySQL>=2.2` 会得到
> `No matching distribution found`，正确写法是 `PyMySQL>=1.2,<2`
> （`requirements-platform.txt` 里已经是这个）。

### 3.3 配置

```bash
cd server-python/platform_server
cp .env.example .env      # 按需修改，或用 export 传环境变量
```

关键变量（全部有默认值，默认值只用于本机开发）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PLATFORM_DB_NAME` | `db_scmj_admin` | 管理平台数据库，**不要**指向 `db_scmj` |
| `PLATFORM_DB_USER` / `PLATFORM_DB_PASSWORD` | `root` / `li663399` | 与本机 MySQL 保持一致 |
| `PLATFORM_DB_HOST` / `PLATFORM_DB_PORT` | `127.0.0.1` / `3306` | |
| `PLATFORM_SECRET_KEY` | 开发用的固定串 | **生产必须改**，否则重启即掉登录态 |
| `PLATFORM_DEBUG` | `1` | 生产设 `0` |
| `PLATFORM_ALLOWED_HOSTS` | `*` | 生产必须收窄 |
| `PLATFORM_CORS_ORIGINS` | 本机 5173/4173 | 前端 dev server 地址 |
| `PLATFORM_ACCESS_TOKEN_MINUTES` | `120` | access 有效期 |
| `PLATFORM_REFRESH_TOKEN_DAYS` | `7` | refresh 有效期 |
| `PLATFORM_DB_ENGINE` | `mysql` | 设成 `sqlite` 可离线跑（见 §5.2） |

### 3.4 建表 + 建初始管理员 + 启动

推荐用启停脚本 `scripts/run.sh`（等价命令见本节末尾）：

```bash
cd server-python/platform_server

# 1) 建表 + 建初始超级管理员（首次部署跑一次，可重复执行）
./scripts/run.sh init
#    想指定账号口令就用 manage.py，避免口令进 shell 历史：
#    PLATFORM_ADMIN_PASSWORD='YourPass!2024' ../.venv/bin/python manage.py seed_admin --username ops

# 2) 启动（等健康检查通过后打印状态表）
./scripts/run.sh
```

启动后：

* 健康检查：<http://127.0.0.1:8000/api/health/>（不需要登录）
* 前端登录页：<http://127.0.0.1:5173/>（`admin-platform/` 的 dev server）

### 3.5 启停脚本 `scripts/run.sh`

| 命令 | 作用 |
| --- | --- |
| `./scripts/run.sh` | 启动 + 等健康检查通过 + 打印状态表 |
| `./scripts/run.sh init` | 建表（migrate）+ 建初始管理员（seed_admin），首次部署跑一次 |
| `./scripts/run.sh stop` | 优雅停止（SIGTERM，超时再 SIGKILL；只停本脚本启动的进程） |
| `./scripts/run.sh restart` | 先停后起（**改完代码用这个**） |
| `./scripts/run.sh status` | 只看状态；就绪退出码 0，否则 1（可直接进 CI/监控） |
| `./scripts/run.sh logs` | 跟踪日志（`logs/platform.log`，Ctrl-C 退出） |
| `./scripts/run.sh check` | 环境自检（解释器 / 依赖 / 数据库连通性 / 待应用迁移），**不启动** |

设计要点：

* **以"健康检查通过"为就绪判据**，不是"端口在监听"。Django 先绑端口再初始化应用，
  端口 listening 但应用还没就绪是常见状态；`/api/health/` 刻意不查数据库，
  所以能单独回答"Web 进程真的能服务请求了吗"。
* **`runserver --noreload`**：默认的自动重载会 fork 出 reloader 父进程，
  PID 文件里记的就不是真正监听端口的那个，停止时子进程会变孤儿继续占端口。
  改完代码用 `restart`。
* **端口冲突会明确报错**（区分"我们启的进程在监听"与"被别人占着"），
  不会假装启动成功。
* **拒绝占用游戏服务端的端口**（9000/9001/9002/9003/10000/12581），
  配置错了立刻就能发现，而不是等游戏服起不来。
* 端口用 `PLATFORM_PORT`（默认 8000）；数据库后端用 `PLATFORM_DB_ENGINE`：

```bash
PLATFORM_PORT=8010 ./scripts/run.sh                 # 换端口
PLATFORM_DB_ENGINE=sqlite ./scripts/run.sh init     # 没有 MySQL 时
```

`scripts/run.sh` 只是 `scripts/serve.py` 的一层壳（与 `server-python/start_all_mac.sh`
的风格一致），只依赖标准库；PID 记在 `.run/pids.json`，日志写 `logs/platform.log`。
**它不替代 `manage.py`**：Django 自己的命令（`migrate` / `test` / `shell` /
`makemigrations`）仍然走 `manage.py`，本脚本只负责"把服务跑起来 / 停下来 / 看状态"。

不用脚本的等价命令：

```bash
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py seed_admin
../.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
```

---

## 4. 数据库脚本

### 4.1 权威定义是迁移，不是 SQL 文件

建表的**权威定义是 Django 的迁移文件**（`apps/*/migrations/`）。
生产部署只需要：

```bash
../.venv/bin/python manage.py migrate
```

`sql/db_scmj_admin.sql` 是**给运维/评审用的可读产物**（很多人需要一个"这库长什么样"的
DDL），它由迁移生成、与迁移严格一致。**不要手工编辑它**，改了也会在下次生成时被覆盖。

### 4.2 生成

```bash
cd server-python/platform_server
../.venv/bin/python scripts/gen_sql.py --output sql/db_scmj_admin.sql
```

**不需要 MySQL 服务**：生成器伪造一次 MySQL 8.0 的连接握手
（只替换 `get_new_connection`，回答 Django 唯一会查的那条服务器变量语句），
然后借道 `sqlmigrate` 让 Django 自己产出 SQL——用的就是 `migrate` 那套 schema editor，
所以内容与真实执行一致，而不是手抄的 DDL。

脚本分三段：

1. `CREATE DATABASE ... utf8mb4`（管理员昵称/备注可能是四字节字符）；
2. **逐条迁移的真实执行 SQL**——因此含"建完又改"的中转语句
   （例如 `token_blacklist` 的 `jti` 列建了又改名又加回来），这是空库 `migrate` 的真实过程；
3. **最终 schema 速查**（纯注释）：直接读 Django 的最终模型状态列出字段与索引，
   省得对着建表语句推算"到底有哪些列"。

### 4.3 校验是否过期（改完模型必跑）

```bash
./scripts/check_sql_fresh.sh
```

判据是**重新生成一遍再逐字节比对**。模型/迁移改了却忘记重新生成，
这个脚本会失败并打印 diff——过期脚本被当成事实用在建库里，比没有脚本更危险。

改了模型的完整流程：

```bash
../.venv/bin/python manage.py makemigrations
../.venv/bin/python scripts/gen_sql.py --output sql/db_scmj_admin.sql
./scripts/check_sql_fresh.sh
../.venv/bin/python manage.py test          # 含 sql 脚本内容自检
```

> ⚠️ `sql/db_scmj_admin.sql` 只适用于**空库初始化**。
> 已有数据的库升级请用 `manage.py migrate`：Django 靠 `django_migrations` 表判断
> 哪些迁移已应用，重跑这个脚本会撞表。

---

## 5. 接口契约

### 5.1 统一响应外壳

**所有**接口都返回同一个形状，前端只写一套解析：

```json
{ "code": 0, "message": "ok", "data": { } }
```

`code === 0` 表示成功。HTTP 状态码仍然有意义（401/403/404/…），
前端按状态码决定"是否跳登录页"，按 `code` 决定"弹什么提示"。

### 5.2 错误码

定义在 `apps/common/error_codes.py`（**全平台唯一一份**）：

| code | 含义 |
| --- | --- |
| `10001` | 参数不合法 |
| `10002` | 未登录 / 令牌失效 → 前端跳登录页 |
| `10003` | 无权限 |
| `10004` | 资源不存在 |
| `10005` | 请求过于频繁 |
| `10500` | 服务端内部错误 |
| `11001` | 账号或口令错误 |
| `11002` | 账号已被禁用 |
| `11003` | 刷新令牌无效或已过期 |

> **踩过的坑**：DRF 的 `ValidationError` 携带不了自定义业务码，
> 如果认证失败只在序列化器里抛 `ValidationError`，统一异常处理器只能把它
> 压成 `10001`，于是"文案是账号或密码错误、code 却是 10001"。
> 所以 `LoginFailed` / `AccountDisabled` / `TokenInvalid` 是
> `PlatformError` 的子类（见 `apps/common/exceptions.py`），
> 业务码挂在异常类型上。改这块务必跑 `tests` 与 `scripts/e2e_login_check.sh`。

### 5.3 端点

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/health/` | 否 | 健康检查（**不查数据库**，用于区分"进程活着"与"库连不上"） |
| `POST` | `/api/auth/login/` | 否 | 账号 + 口令 → access/refresh + 管理员信息 |
| `POST` | `/api/auth/refresh/` | 否 | refresh → 新 access（**并轮换 refresh**） |
| `GET` | `/api/auth/me/` | 是 | 当前登录管理员信息 |
| `POST` | `/api/auth/logout/` | 是 | 吊销 refresh |
| — | `/admin/` | Django session | Django 自带的数据库管理站点（运维兜底，不是本平台前端） |

`POST /api/auth/login/` 成功返回：

```json
{
  "code": 0,
  "message": "登录成功",
  "data": {
    "access": "eyJ...",
    "refresh": "eyJ...",
    "access_expires_at": 1790236024,
    "user": {
      "id": 1, "username": "admin", "nickname": "超级管理员",
      "display_name": "超级管理员", "email": "admin@platform.local",
      "role": "super_admin", "role_display": "超级管理员",
      "status": "active", "status_display": "启用",
      "is_superuser": true,
      "last_login": "2026-09-24 13:47:04", "last_login_ip": "127.0.0.1",
      "created_at": "2026-09-24 13:46:56"
    }
  }
}
```

响应里**永远不含** `password`（有测试钉住）。

### 5.4 登录口径

* 账号名**大小写不敏感**（`Admin` 能登进 `admin`）——刻意不用 Django 的
  `authenticate()`，因为 `ModelBackend` 对 `username` 是精确匹配；
* 账号不存在与口令错误返回**同一句文案、同一个码**，防止枚举管理员账号；
* 账号被禁用返回明确的 `11002`（运营需要知道是"被禁用"而不是"密码错"）；
* 账号不存在时也做一次等价耗时的哈希运算，避免通过响应时间枚举账号；
* 登录成功记录 `last_login` 与 `last_login_ip`。

### 5.5 令牌

* access / refresh 都是 JWT，claim 里带 `admin_id` / `role` / `username`；
* `ROTATE_REFRESH_TOKENS = True`：每次刷新都换发新 refresh，
  旧 refresh **立即进黑名单**（依赖 `token_blacklist` 应用），
  所以前端必须用响应里的新 refresh 覆盖本地那个；
* 退出登录只能吊销 refresh。JWT 是无状态的，**已签发的 access 在过期前依然有效**；
  需要"立即失效"就把 `PLATFORM_ACCESS_TOKEN_MINUTES` 调短；
* 账号被禁用后：`/me/` 立刻失效（SimpleJWT 校验 `is_active`），
  refresh 也会被 `RefreshTokenView` 拦下。

---

## 6. 验证

### 6.1 接口测试（推荐，不需要 MySQL）

```bash
cd server-python/platform_server
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test
```

38 项（`test_auth` 29 + `test_sql_script` 9），覆盖登录成功/失败、账号枚举防护、
禁用账号、大小写、IP 记录、`/me/`、令牌轮换与黑名单、退出登录、
**账号体系隔离**、`seed_admin`、健康检查，以及建库脚本的内容自检。

默认（不带 `PLATFORM_DB_ENGINE=sqlite`）会连 MySQL 建测试库，
这样能顺带验证真实 MySQL 下的建表与查询。

### 6.2 没有 MySQL 时怎么跑

设 `PLATFORM_DB_ENGINE=sqlite` 就把数据库换成单文件 SQLite
（路径 `PLATFORM_SQLITE_PATH`，默认 `var/platform_dev.sqlite3`）：

```bash
cd server-python/platform_server
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py migrate
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py seed_admin --password 'AdminPass!2024'
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py runserver 127.0.0.1:8000
```

这条路径只是为了**在没有 MySQL 的机器上把登录流程跑通**，
生产一律用 MySQL。

### 6.3 端到端验收

后端起来之后，用真实 HTTP 把整条登录链路跑一遍：

```bash
cd server-python/platform_server
./scripts/e2e_login_check.sh                     # 默认 http://127.0.0.1:8000
./scripts/e2e_login_check.sh http://host:port    # 指定地址
```

24 项断言：健康检查 → 登录 → 大小写 → 口令错误 → 账号不存在 →
`/me/` → 令牌轮换与旧令牌失效 → 退出登录。

它比单元测试更贴近真实：**上面那个 10001/11001 的偏差就是它先发现的**
（单元测试当时只断言了文案，没断言 `code`）。

### 6.4 仓库根门禁

```bash
npm run verify            # 七项检查
npm run check:python      # 只跑 Python 语法 + server-python/tests 的离线测试
```

`check:python` 的 **AST 解析那一半会扫到本目录的每个 `.py`**（含迁移文件），
所以本目录新增文件后请跑一次门禁。

注意它跑的是 `server-python/tests/` 下的 stdlib unittest（`-s tests`，
不递归到 `platform_server/tests/`），**不会**执行本目录的 Django 测试——
Django 测试需要 `manage.py test` 来配置 settings 与建测试库。
两者都要跑，见 §5.1。

---

## 7. 与游戏服务端的关系

**可以同时运行**，端口不冲突：

| 进程 | 端口 |
| --- | --- |
| 游戏账号服 | 9000（客户端）、12581（代理 API） |
| 游戏大厅服 | 9001、9002 |
| 游戏游戏服 | 10000、9003 |
| **管理平台后端** | **8000** |
| 管理平台前端（dev） | 5173 |

隔离是刻意的，请不要为了方便而"顺手打通"：

* ❌ 不要 `import` `../utils/db.py` 去读玩家表 —— 那会绕过 Django 的迁移与事务边界；
* ❌ 不要复用 `t_accounts` 存管理员 —— 明文口令 + 玩家可注册，等于后台没有防线；
* ❌ 不要让管理平台签发游戏 token —— 两套 token 的算法与信任域不同；
* ✅ 需要展示玩家数据时，走账号服/大厅服已有的 HTTP 接口，或**另外**加一个
  只读的数据源，并在文档里写清楚数据来源与权限边界。

---

## 8. 已知边界

* **未做登录限流**。暴力破解的防线目前只有 PBKDF2 的迭代成本。
  上生产前建议加 `django-ratelimit` 或反向代理层的限流
  （错误码 `10005` 已经预留）。
* **未做操作审计日志**。目前只有登录/退出打日志，没有落库的审计流水。
* **`/admin/` 与 JWT 是两套认证**。前者是 Django session（仅 `is_staff` 可进），
  后者是 JWT。两者都只认 `AdminUser` 表，但改权限模型时要同时想到这两条路径。
* **access 无法主动吊销**。这是 JWT 的固有限制，缓解手段是把有效期调短。

---

## 9. 不要提交

`var/`（SQLite 开发库、收集的静态文件）、`logs/`、`.env`、`__pycache__/`，
以及仓库根规则里已有的那些。见本目录 `.gitignore`。
