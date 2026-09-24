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
│   │   ├─ pagination.py        统一分页形状（page_payload + PageNumberPagination）
│   │   └─ ip.py                客户端 IP 提取（X-Forwarded-For）
│   ├─ accounts/                **管理平台账号体系**
│   │   ├─ models.py            AdminUser（自定义用户模型）
│   │   ├─ serializers.py       入参校验 / 认证 / 令牌签发与吊销
│   │   ├─ views.py             四个登录相关端点
│   │   ├─ urls.py              /api/auth/ 路由
│   │   ├─ permissions.py       角色权限类
│   │   ├─ admin.py             Django admin 站点注册（运维兜底）
│   │   ├─ error_codes.py       登录相关错误码的转出口
│   │   └─ management/commands/seed_admin.py   初始超级管理员
│   └─ players/                 **玩家管理**（见 §6）
│       ├─ player_source.py     玩家库 `db_scmj` 的**只读**数据源（唯一读它的地方；
│       │                       `t_users` 与房间表 `t_rooms` 共用这一条通道）
│       ├─ models.py            PlayerBan：封禁 / 解封流水（落本平台的库）
│       ├─ serializers.py       入参校验 + 出参形状（含预留端点的契约）
│       ├─ views.py             列表 / 概览 / 详情 / 封禁 / 解封 / 两个预留入口
│       ├─ urls.py              /api/players/ 路由
│       ├─ internal.py          给游戏服的内部只读校验接口（共享密钥，见 §6.5）
│       ├─ urls_internal.py     /api/internal/players/ 路由
│       ├─ exceptions.py        玩家相关的类型化异常（12001~12004）
│       ├─ admin.py             封禁流水的**只读** admin 视图
│       └─ management/commands/init_player_dev.py  SQLite 玩家库的样例数据（仅开发）
│   └─ rooms/                   **房间管理**（见 §6.6；只有视图与序列化器，没有模型）
│       ├─ serializers.py       入参校验 + 出参形状（含预留运维入口的契约）
│       ├─ views.py             列表 / 概览 / 详情 / 预留的强制解散
│       ├─ urls.py              /api/rooms/ 路由
│       └─ exceptions.py        房间相关的类型化异常（13001）
├─ sql/db_scmj_admin.sql         ← **生成产物**：MySQL 建库建表脚本（不要手改）
├─ scripts/
│   ├─ run.sh                    启停脚本入口（start/stop/restart/status/logs/init/check）
│   ├─ serve.py                  run.sh 的实现（只依赖标准库）
│   ├─ gen_sql.py                生成上面的 SQL（不需要 MySQL）
│   ├─ check_sql_fresh.sh        校验 SQL 是否与迁移一致（重新生成后比对）
│   └─ e2e_login_check.sh        真实 HTTP 端到端验收（74 项：登录 / 玩家 / 房间 / 内部接口）
├─ tests/test_auth.py            登录闭环接口测试（29 项）
├─ tests/test_players.py         玩家管理 + 内部封禁校验 + 只读隔离测试（55 项）
├─ tests/test_rooms.py           房间管理 + 预留入口 + 只读隔离测试（32 项）
├─ tests/test_sql_script.py      建库脚本的内容自检（13 项）
└─ 合计 `manage.py test`          129 项
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
| `12001` | 玩家不存在 |
| `12002` | 该玩家已处于封禁中 |
| `12003` | 该玩家当前不在封禁中 |
| `12004` | 玩家只读数据源不可用（连不上玩家库） |
| `13001` | 房间不存在或已结束 |

> **`12004` 与 `12001` 刻意分开**：前者是运维问题（去看数据库配置），
> 后者是运营输入问题（账号 / ID 写错了）。前端据此给不同的提示。

> **房间没有单开"数据源不可用"码**：房间数据与玩家数据来自**同一条只读数据源**
> （同一个玩家库），连不上的处置方式是同一个，所以继续用 `12004`；
> 房间侧新增的只有 `13001`（房间查不到）。房间是**瞬时**的——游戏服销毁房间时
> 会删掉 `t_rooms` 里的一行，所以 `13001` 最常见的原因是"房间已经打完了"。

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
| `GET` | `/api/players/` | 是 | 玩家列表：搜索 / 封禁状态过滤 / 排序 / 分页 |
| `GET` | `/api/players/overview/` | 是 | 概览：玩家总数、封禁中人数 |
| `GET` | `/api/players/<id>/` | 是 | 玩家详情 + 封禁流水 |
| `POST` | `/api/players/<id>/ban/` | 管理员及以上 | 封禁（可限时） |
| `POST` | `/api/players/<id>/unban/` | 管理员及以上 | 解封 |
| `GET` | `/api/players/<id>/games/` | 是 | **预留**：对局记录（当前返回 `reserved: true`） |
| `GET` | `/api/players/<id>/recharges/` | 是 | **预留**：充值记录（同上） |
| `GET` | `/api/rooms/` | 是 | 存活房间列表：搜索 / 玩法 / 座位占用过滤 / 排序 / 分页 |
| `GET` | `/api/rooms/overview/` | 是 | 概览：房间总数、已满座、未满座、24 小时新建 |
| `GET` | `/api/rooms/<room_id>/` | 是 | 房间详情（配置 + 四个座位 + 预留入口说明）；`room_id` 可以是房间号或 uuid |
| `POST` | `/api/rooms/<room_id>/dissolve/` | 管理员及以上 | **预留**：强制解散（恒返回 `reserved: true`，见 §6.6） |
| `GET` | `/api/internal/players/ban-check/` | **共享密钥** | **内部接口**：给游戏服查封禁状态（不走 JWT，见 §6.5） |
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

## 6. 业务模块：数据来源与权限边界

这一节是 `AGENTS.md` §2 第 5 条要求写清楚的内容：**数据从哪来、能做什么、不能做什么**。

* §6.1 ~ §6.5：**玩家管理**（`apps/players/`）；
* §6.6：**房间管理**（`apps/rooms/`）——它复用玩家管理那条只读通道读 `t_rooms`。

### 6.1 数据来源：一条显式的只读数据源

| 数据 | 来源 | 读写 |
| --- | --- | --- |
| 玩家账号 / 昵称 / 房卡 `gems` / 金币 / 等级 / 所在房间 | **玩家库 `db_scmj` 的 `t_users`** | **只读**（只执行 SELECT） |
| 封禁状态与封禁流水 | **管理平台库 `db_scmj_admin` 的 `players_playerban`** | 读写（本平台自己的表）；游戏服通过内部接口只读它，见 §6.5 |
| 管理员账号 | `db_scmj_admin` 的 `accounts_adminuser` | 读写 |

> 房间管理读的 `t_rooms` 也在玩家库里，同样只走这条通道，见 §6.6。

实现位置：

* 只读数据源：`apps/players/player_source.py`，走 `settings.DATABASES["player"]`
  （别名固定为 `player`），是**唯一**读玩家库的地方；
* 封禁流水：`apps/players/models.py` 的 `PlayerBan`，只落本平台的库。

三条硬边界：

1. **只读**。`player_source._assert_read_only()` 拒绝任何非 SELECT、含分号的多语句、
   以及句子里出现写关键字（INSERT / UPDATE / DELETE / ...）的 SQL。
   `tests/test_players.py::PlayerSourceIsolationTests` 会跑一遍列表 / 详情 / 封禁 / 解封，
   断言玩家库连接上**执行的每一条 SQL 都以 SELECT 开头**。
   **生产建议再给 `PLATFORM_PLAYER_DB_USER` 配一个只有 SELECT 权限的账号**——
   应用层校验只是第二道防线。
2. **不落模型、不落迁移**。管理平台在玩家库里没有 Django 模型，
   `manage.py migrate` 也不会碰 `db_scmj`。跨库外键在 MySQL 上不合法，
   `PlayerBan.player_id` 因此只是一个整数（附账号 / 昵称快照）。
3. **不复用游戏服的访问层**。不 import `server-python/utils/db.py`，也不共享它的连接池；
   `tests/test_players.py` 用 AST 解析 `player_source` 的 import 来钉住这一点。

> 为什么不直接调游戏服的接口？大厅服 `/login`、渠道 API `/get_user_info` 都是
> **按 account 取单个玩家**，没有列表 / 搜索 / 分页能力。后台的"查玩家"必须能按
> 账号、昵称、ID 检索并翻页，所以按 `AGENTS.md` §2 第 5 条开了这条只读数据源。

### 6.2 权限边界

| 操作 | 需要的角色 | 说明 |
| --- | --- | --- |
| 查看列表 / 详情 / 概览 / 预留入口 | 任意启用中的管理员（`operator` 及以上） | 看数据是运营日常 |
| 封禁 / 解封 | **管理员及以上**（`admin` / `super_admin`） | 改玩家状态，多一层 `IsAdminOrAbove` |

无权限返回 `10003`，未登录返回 `10002`——前端据此区分"弹无权限提示"与"跳登录页"。

### 6.3 封禁语义

* **追加流水，不改行**：每次封禁 / 解封都 `INSERT` 一条 `players_playerban`，
  当前状态由"最新一条"推导。好处是审计链完整（谁、何时、为什么），
  也不会在改状态时把上一条原因覆盖掉。
* **限时封禁**：`duration_hours` 给出自动解封时间；到期后**自动视为正常**
  （`is_effective` 判 `expires_at > now`），不需要定时任务。
* **重复操作有明确错误码**：已在封禁中再封 → `12002`；不在封禁中解封 → `12003`。
* **解封不依赖玩家库**：玩家库连不上时依然能解封（账号 / 昵称取最近一条流水快照），
  避免数据源故障把人锁死在"封着"的状态。
* ✅ **封禁会真的拦住玩家**：游戏服（大厅服 + 游戏服）在登录 / 建房 / 进房前会调
  §6.5 的内部校验接口，被封的账号进不来。生效延迟最多一个缓存 TTL（默认 30 秒）。
* **不打断进行中的对局**：封禁在"登录 / 进房"这一刻生效，不会把正在打牌的玩家踢下线
  （那需要平台反向推送到游戏服，是另一次改动）。

### 6.5 游戏服联动：内部只读校验接口

`GET /api/internal/players/ban-check/?account=<account>&sign=<md5>`
（或 `?player_id=<id>&sign=<md5>`）是**游戏服进程**调用的接口，不走 JWT：

| 项 | 说明 |
| --- | --- |
| 调用方 | 大厅服（`/login`、`/create_private_room`、`/enter_private_room`）与游戏服（socket `login`） |
| 认证 | 共享密钥：`sign = md5("account" + account + "player_id" + player_id + PRI_KEY)` |
| 密钥 | 平台侧 `PLATFORM_INTERNAL_KEY` ↔ 游戏服侧 `ban_check()["PRI_KEY"]`，**必须逐字一致** |
| 返回 | `{account, player_id, known, banned, reason, expires_at}` |
| 实现 | 平台 `apps/players/internal.py`；游戏服 `server-python/utils/bancheck.py`、`server/utils/bancheck.ts` |

三条你必须知道的运行语义：

1. **fail-open**：游戏服超时 / 连不上 / 拿到非 0，一律**放行**并打警告日志。
   管理后台是运营工具，它挂掉不该让全体玩家登不上游戏——代价是平台故障期间
   被封玩家能临时进来。这个取舍是刻意选的（见 `server-python/utils/bancheck.py`）。
2. **密钥不一致 = 封禁静默失效**：平台回 `10003`，游戏服 fail-open 放行，
   只在游戏服日志里留一行警告。**排查"封了没生效"先看这行日志，再核对两侧密钥。**
3. **缓存**：游戏服按 `CACHE_TTL_MS`（默认 30 秒）缓存结果，正负都缓存；
   失败后有 5 秒冷却窗口，避免平台挂掉时每次登录都白等一个超时。
   所以"后台点封禁"到"玩家被拦下"最多滞后一个 TTL。

**信任边界**：`/api/internal/` 不走 JWT、不做 CSRF，只认密钥。部署时应在反向代理上
把该前缀限制成只允许游戏服所在网络访问，不要暴露到公网。密钥留空时接口**拒绝服务**
（`10500`）而不是放行——未配置密钥的"内部接口"等于一个人人可查的公开接口。

契约由三处参考向量钉住：`server-python/tests/test_protocol.py`、
`platform_server/tests/test_players.py::InternalBanCheckTests`、
`tools/lib/smoke.mjs`（Node 侧），任何一处改了拼接顺序都会同时红。

### 6.4 预留入口：对局记录 / 充值记录

`GET /api/players/<id>/games/` 与 `.../recharges/` **契约已定、数据源待接入**：

* 返回形状与真实列表接口**完全一致**（`items` / `total` / `page` / `page_size` / `pages`），
  额外多一个 `reserved: true`、`feature`、`source`、`message`；
* 分页参数**此刻就校验**（`page` / `page_size`），所以接上数据源时前端不用改契约；
* 预留端点**不访问玩家库**（数据源没接入就没有查询可发），因此玩家库故障时它们照常可用；
* 前端在玩家详情抽屉里已经有两个 Tab 接上它们，列表行的"更多"也能直接跳过去。

计划的数据来源写在响应里，也记在这里：

| 入口 | 计划来源 |
| --- | --- |
| 对局记录 | `t_users.history`（房间 uuid 列表）+ `t_games` / `t_games_archive`（逐局明细） |
| 充值记录 | 充值订单表——**当前玩家库没有订单流水**，只有 `t_users.coins` / `gems` 余额，需要先有落库的订单 |

### 6.6 房间管理：同一只读通道的第二张表

**只读监控**玩家库 `t_rooms` 里的存活房间：谁在建的、什么配置、四个座位坐着谁、
打了多少局、跑在哪台游戏服上。

| 能力 | 端点 | 权限 |
| --- | --- | --- |
| 列表（搜索 / 玩法 / 座位占用 / 排序 / 分页） | `GET /api/rooms/` | 登录即可 |
| 概览（总数 / 已满座 / 未满座 / 24 小时新建） | `GET /api/rooms/overview/` | 登录即可 |
| 详情（配置 + 四个座位 + 预留入口说明） | `GET /api/rooms/<room_id>/` | 登录即可 |
| **预留**：强制解散 | `POST /api/rooms/<room_id>/dissolve/` | 管理员及以上 |

数据来源与三条硬边界（**这条通道是唯一的**）：

* 数据来自玩家库 `db_scmj` 的 `t_rooms`，SQL 写在 **`apps/players/player_source.py`**
  的 `t_users` 那一段下面——房间与玩家共用一个库，`AGENTS.md` §2 第 1 / 5 条
  要求"只走 `player_source`，不要另开第二条"，所以 `apps/rooms/` 里
  **只有视图与序列化器，没有任何连接或 SQL**（`tests/test_rooms.py` 用 AST 钉住这一点）；
* 房间数据**不落本平台的库**：`apps/rooms/` 没有模型、没有迁移，
  `sql/db_scmj_admin.sql` 里不会出现 `t_rooms`；
* 只在 SQL 层面 `SELECT`：`_assert_read_only()` 与
  `tests/test_rooms.py::RoomSourceIsolationTests` 双向保证。

**几个容易误读的点**（都写在 `player_source.py` 的注释里）：

* `t_rooms` 里只有**尚未销毁**的房间。游戏服的 `roommgr.destroy()` 会删掉整行，
  进程重启时再用这些行把房间恢复回内存。所以这张表约等于"当前存活房间"，
  而 `13001`（房间不存在）最常见的含义是"已经打完了"；
* **状态是推导出来的**：`state` 由座位占用决定——`playing` 只表示"四个座位都有人"，
  不代表牌局正在出牌；
* 房间配置在 `base_info` 这个 **JSON 字符串**里，后台按
  `LIKE '%"type":"xx"%'` 过滤玩法（`type` 是紧凑 JSON 的第一个键，
  见 `utils/db._conf_to_wire`）；
* `create_time` 是 Unix 秒，出参里额外给了格式化好的 `created_at`；
* `conf.single`（单人模式）**不落库**，所以后台看不出一个房间是不是人机房；
* 关键词**不匹配房主**：`conf.creator` 在 `base_info` 的 JSON 里，只能做子串匹配
  （搜 `1003` 会误命中 `10030`），所以按房主找房间请用"座位上的玩家 ID"——
  房主平时就坐在座位上；他离座之后，后台按 ID 搜不到那个房间。

**强制解散是预留入口**（本期不做实事）：`POST /api/rooms/<id>/dissolve/`
会先确认房间还在，然后返回 `reserved: true` + `feature` + `source` + `message`，
**不会**改动任何数据（测试断言了这一点）。真正生效需要**平台 → 游戏服**的内部接口
（共享密钥、按房间 uuid 通知 `roommgr`），属跨进程改动，要 Node 与 Python 两套游戏服
同时加接口与签名校验——那是另一次改动，方向与 §6.5 的"游戏服 → 平台"相反。
前端的调用链（按钮 → 二次确认 → 调接口 → 展示提示）现在就已经接通，
后端换掉实现即可，契约不用改。

---

## 7. 验证

### 7.1 接口测试（推荐，不需要 MySQL）

```bash
cd server-python/platform_server
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test
```

129 项（`test_auth` 29 + `test_players` 55 + `test_rooms` 32 + `test_sql_script` 13），
覆盖登录成功/失败、账号枚举防护、禁用账号、大小写、IP 记录、`/me/`、令牌轮换与黑名单、
退出登录、**账号体系隔离**、`seed_admin`、健康检查、玩家列表/搜索/过滤/分页、
封禁解封与业务码、预留入口契约、**玩家库只读隔离**、
**内部封禁校验接口（签名向量 / fail-open / 不配密钥就拒服务）**、
房间列表/搜索/玩法与状态过滤/分页、房间详情与概览、预留的强制解散入口、
**房间路径的只读隔离**，以及建库脚本的内容自检。

默认（不带 `PLATFORM_DB_ENGINE=sqlite`）会连 MySQL 建测试库，
这样能顺带验证真实 MySQL 下的建表与查询。只读数据源用的是它自己的测试库
（SQLite 下是内存库，MySQL 下是 `test_db_scmj`），**不会碰真实的 `db_scmj`**。

### 7.2 没有 MySQL 时怎么跑

设 `PLATFORM_DB_ENGINE=sqlite` 就把数据库换成单文件 SQLite
（路径 `PLATFORM_SQLITE_PATH`，默认 `var/platform_dev.sqlite3`）：

```bash
cd server-python/platform_server
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py migrate
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py seed_admin --password 'AdminPass!2024'
# 玩家管理 / 房间管理还需要一个 SQLite 玩家库：建表 + 塞样例数据（生产不要跑）
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py init_player_dev
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py runserver 127.0.0.1:8000
```

这条路径只是为了**在没有 MySQL 的机器上把平台跑通**（登录 + 玩家管理 + 房间管理），
生产一律用 MySQL。`init_player_dev` 只允许跑在 SQLite 玩家库上：
玩家库配置成 MySQL 时它会直接报错退出，避免误碰真实数据。
它给 `t_users` 与 `t_rooms` 各造一份样例（房间刻意有"满座在打"和"未满座"两种），
用来把两个页面的筛选试出来。

### 7.3 端到端验收

后端起来之后，用真实 HTTP 把整条链路跑一遍：

```bash
cd server-python/platform_server
./scripts/e2e_login_check.sh                     # 默认 http://127.0.0.1:8000
./scripts/e2e_login_check.sh http://host:port    # 指定地址
```

74 项断言，分四段：

1. **登录闭环（24 项，第 1~8 节）**：健康检查 → 登录 → 大小写 → 口令错误 → 账号不存在 →
   `/me/` → 令牌轮换与旧令牌失效 → 退出登录；
2. **玩家管理（24 项，其中 11 项依赖玩家数据）**：未登录被拒 → 概览 → 列表与房卡字段 →
   非法参数 `10001` → 不存在时 `12001` → 两个预留入口的 `reserved` 契约 →
   详情 → 封禁 → 重复封禁 `12002` → 封禁状态过滤 → 解封 → 重复解封 `12003`。
3. **内部封禁校验接口（10 项）**：无签名 / 错误签名必须 403 + `10003`（不能放行）→
   按 `account` 与按 `player_id` 查询 → 封禁后 `banned=true` 且回带原因 → 解封后 `false`。
   这一段用的是**与游戏服完全相同的签名公式**（密钥可用 `E2E_INTERNAL_KEY` 覆盖），
   所以它同时验证了"平台与游戏服两边拼出来的签名一致"。
4. **房间管理（16 项，其中 10 项依赖房间数据）**：未登录被拒 → 非法参数 `10001` →
   房间不存在 `13001` → 概览 → 列表分页形状 → 详情（含四个座位）→
   预留的解散入口返回 `reserved: true` 且**不改动房间**。

> 第 2、4 段需要玩家库里有数据：第 2 段要**未被封禁**的玩家，第 4 段要 `t_rooms`
> 里有存活房间。真实 `db_scmj` 为空时，脚本会**跳过**依赖数据的断言并打印一行提示，
> 不会把它们算成失败。

它比单元测试更贴近真实：**上面那个 10001/11001 的偏差就是它先发现的**
（单元测试当时只断言了文案，没断言 `code`）。

### 7.4 仓库根门禁

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

## 8. 与游戏服务端的关系

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
* ❌ 不要往玩家库**写**任何东西（包括封禁状态）—— 玩家库只有
  `apps/players/player_source.py` 这一条只读通道（玩家的 `t_users` 与房间的
  `t_rooms` 都走它，见 §6.6）；
* ✅ 游戏服要读封禁状态时走 `/api/internal/players/ban-check/`（共享密钥、只读），
  不要让游戏服直连 `db_scmj_admin`——那会把平台的表结构变成对外契约；
* ✅ 需要展示玩家数据时，走账号服/大厅服已有的 HTTP 接口，或**另外**加一个
  只读的数据源，并在文档里写清楚数据来源与权限边界 ——
  玩家管理就是这么做的，来源与边界见 §6。

> 反方向的"平台 → 游戏服"目前**只有预留入口，没有真实通道**：
> 强制解散房间（§6.6）要真的生效，得先在游戏服上加一个共享密钥的内部接口。
> 在此之前，管理平台对所有游戏数据仍然是纯只读的。


---

## 9. 已知边界

* **未做登录限流**。暴力破解的防线目前只有 PBKDF2 的迭代成本。
  上生产前建议加 `django-ratelimit` 或反向代理层的限流
  （错误码 `10005` 已经预留）。
* **未做登录/管理操作的落库审计**。目前只有登录、退出、封禁、解封打日志；
  封禁本身有流水表（`players_playerban`），但"谁改了哪个管理员"这类操作没有落库流水。
* **封禁是 fail-open 的**。游戏服调不通本平台时会放行并在日志里告警（见 §6.5），
  所以平台 / 网络故障期间被封玩家能临时进游戏；同时封禁最迟在一个缓存 TTL（30 秒）
  内生效，且**不会打断正在进行的对局**（只在登录 / 进房那一刻拦）。
* **`/admin/` 与 JWT 是两套认证**。前者是 Django session（仅 `is_staff` 可进），
  后者是 JWT。两者都只认 `AdminUser` 表，但改权限模型时要同时想到这两条路径。
* **access 无法主动吊销**。这是 JWT 的固有限制，缓解手段是把有效期调短。
* **玩家昵称的模糊搜索按 Base64 片段匹配**。`t_users.name` 是 Base64 存的，
  搜索词也按同样口径编码后再 `LIKE`。前缀能对上（3 字节对齐时），
  跨字节边界的中间片段可能搜不到——按账号或玩家 ID 搜索永远准确。
  房间管理按**座位昵称**搜索时是同一套口径与同一个限制。
* **房间管理只看"还活着"的房间**。`t_rooms` 里没有历史房间——游戏服销毁房间时
  会删掉整行（见 §6.6），所以打完 / 解散的房间查不到，也没有"历史房间"列表。
  要审计已经结束的对局，得读 `t_games` / `t_games_archive`（本期未接入）。
* **房间的运维动作是预留的**。强制解散 / 踢人需要**平台 → 游戏服**的内部接口，
  本期只把契约、权限与前端调用链定下来（`POST /api/rooms/<id>/dissolve/`
  恒返回 `reserved: true`，不做实事）。在此之前，管理平台无法影响进行中的对局。
* **房间的"状态"是推导出来的**。`playing` 的含义是"四个座位都有人"，
  不是"正在出牌"；`t_rooms` 里没有更细的状态字段可用。

---

## 10. 不要提交

`var/`（SQLite 开发库、收集的静态文件）、`logs/`、`.env`、`__pycache__/`，
以及仓库根规则里已有的那些。见本目录 `.gitignore`。
