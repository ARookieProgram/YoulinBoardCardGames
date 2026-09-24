# AGENTS.md — 管理平台后端（platform_server）

本文件叠加在根级 `AGENTS.md` 与 `server-python/AGENTS.md` 之上，**仅覆盖
`server-python/platform_server/`**。冲突时以本文件为准。

面向人类的完整说明见 `repo:server-python/platform_server/README.md`。

---

## 1. 这是什么

**游戏管理平台的后端**，与游戏服务端（账号服 / 大厅服 / 游戏服）是两回事：

| | 管理平台 | 游戏服务端 |
| --- | --- | --- |
| 技术栈 | Django 6.1 + DRF + SimpleJWT | aiohttp + 自研 Socket.IO |
| 入口 | `repo:server-python/platform_server/manage.py` | `repo:server-python/*/app.py` |
| 端口 | 8000 | 9000 / 9001 / 9002 / 9003 / 10000 / 12581 |
| 数据库 | **`db_scmj_admin`** | `db_scmj` |
| 账号 | `AdminUser`（`accounts_adminuser` 表） | `t_accounts` / `t_users` |
| 认证 | JWT | 自研 md5 签名 token |

**账号体系完全隔离**，这不是风格选择而是需求本身，见 §2。

## 2. 隔离红线（改任何代码前先读）

1. **不读玩家库、不写玩家库**。管理平台的 ORM 里没有 `t_accounts` / `t_users`，
   也不要为了"顺手查一下"去 `import` `repo:server-python/utils/db.py`。
2. **不复用 `t_accounts` 当管理员表**。玩家侧口令是明文且玩家可自行注册，
   拿它做后台等于没有防线。
3. **不签发游戏 token、不校验游戏 token**。两套 token 的算法、密钥、信任域都不同。
4. **不改 `t_accounts.password` 的明文存储方式**。要改就去改游戏服务端两边
   （`repo:server/` 与 `repo:server-python/` 成对改），不能从管理平台侧偷偷动。
5. 需要展示玩家数据时，走账号服/大厅服已有的 HTTP 接口，或另加只读数据源，
   并把数据来源与权限边界写进 README。

`repo:server-python/platform_server/tests/test_auth.py::AccountIsolationTests`
把第 1、2 条钉成了断言。

## 3. 目录约定

```
platform_server/
├─ manage.py                     Django 入口
├─ requirements-platform.txt     **独立**依赖清单（不要并进 requirements.txt）
├─ .env.example                  环境变量模板
├─ config/                       工程配置（settings 是唯一配置来源）
├─ apps/common/                  响应外壳 / 错误码 / 异常 / 分页 / IP
├─ apps/accounts/                管理平台账号体系（模型 / 序列化 / 视图 / 权限）
├─ sql/db_scmj_admin.sql         **生成产物**：建库脚本（不要手改，见 §4.4）
└─ scripts/
    ├─ run.sh / serve.py         启停脚本（start/stop/restart/status/logs/init/check）
    ├─ gen_sql.py                生成上面的 SQL（不需要 MySQL）
    ├─ check_sql_fresh.sh        校验 SQL 是否与迁移一致
    └─ e2e_login_check.sh        真实 HTTP 端到端验收
```

**新增业务模块**放 `apps/<模块>/`，并在 `config/settings.py` 的 `INSTALLED_APPS`
里注册 `apps.<模块>`（`apps/` 是命名空间包，`label` 在各自 `apps.py` 里显式指定）。

## 4. 四条容易踩的坑

### 4.1 DRF 的 `ValidationError` 带不了业务码

`ValidationError(detail, code=...)` 的 `code` 是给"单条错误"用的，
统一异常处理器拿到的是一个不含自定义业务码的 `detail`，
只能映射成 `ERR_BAD_REQUEST(10001)`。

所以**认证类失败要抛 `apps/common/exceptions.py` 里的类型化异常**
（`LoginFailed` / `AccountDisabled` / `TokenInvalid`，都是 `PlatformError` 子类），
业务码挂在**异常类型**上。曾经因为这点出现过"文案对、code 却是 10001"的偏差，
单元测试当时只断言了文案所以没拦住，是 `scripts/e2e_login_check.sh` 先发现的。
**新增业务错误时，测试必须同时断言 `code` 与文案。**

### 4.2 返回 DRF `Response` 的视图必须经过 DRF 渲染

把 `apps/common/response.py` 的 `ok()` 挂在**裸 Django 视图**上会 500：

```
AssertionError: .accepted_renderer not set on Response
```

要么用 `APIView`，要么给函数视图加 `@api_view`（`/api/health/` 就是后者）。
新增任何返回统一外壳的路由后，跑一次
`repo:server-python/platform_server/scripts/e2e_login_check.sh` 的第 1 节。

### 4.3 错误码只有一份

业务码**只定义在 `repo:server-python/platform_server/apps/common/error_codes.py`**。
`apps/accounts/error_codes.py` 是转出口，不是第二份定义。
新增登录相关码加在 `11xxx` 段；前端对应常量在
`repo:admin-platform/src/api/types.ts` 的 `ErrorCode`，要同步改。

### 4.4 `sql/db_scmj_admin.sql` 是**生成产物**，不要手改

权威定义是**迁移文件**。这个 SQL 由 `scripts/gen_sql.py` 让 Django 自己吐出来
（伪造 MySQL 8 握手后走 `sqlmigrate`，因此不需要装 MySQL），
内容与空库 `migrate` 实际执行的语句一致。

- **不要手工编辑它**，也不要"顺手优化"里面的中转语句
  （`token_blacklist` 的 `jti` 列建了又改名，那是真实迁移过程）；
- 改了模型/迁移之后必须 `makemigrations` + 重新生成 + 跑 `check_sql_fresh.sh`，
  否则 `tests/test_sql_script.py` 的列覆盖断言会失败（它逐个比对模型字段）；
- 校验过期用 `scripts/check_sql_fresh.sh`（重新生成后逐字节比对），**不要**用
  `makemigrations --check` 那套自动检测器做离线判断：它要读 `django_migrations` 表，
  而且离线调用容易给出假阳性（曾误报过全部第三方 app，而真实
  `makemigrations --check` 回答 "No changes detected"）。

## 5. 改完怎么验证

```bash
cd server-python/platform_server

# 1) 接口测试（不需要 MySQL）。38 项（登录 29 + 建库脚本自检 9）。
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test

# 1b) 建库 SQL 是否与迁移一致（改了模型必跑）
./scripts/check_sql_fresh.sh

# 2) 真实 HTTP 端到端。24 项。
#    启停一律用 ./scripts/run.sh（等价于 runserver --noreload + 健康检查）：
./scripts/run.sh                       # 启动（等健康检查通过）
./scripts/e2e_login_check.sh           # 打真实接口
./scripts/run.sh stop

# 3) 仓库根门禁：它的 python 检查会 AST 解析本目录每个 .py
cd ../.. && npm run check:python
```

改完代码用 `./scripts/run.sh restart`（脚本用 `--noreload` 启动，
不会有自动重载，也不会留下孤儿 reloader 进程）。

`npm run verify` 里的 `syntax` / `types` 两项**不扫本目录**
（它们按 `.ts` 与 `client/` 写的），所以本目录靠上面三条。
注意 `check:python` 的第二半跑的是 `server-python/tests/` 下的 stdlib unittest
（`-s tests`，不递归到本目录），**不会**执行 Django 测试——别以为门禁绿了
就等于本平台的测试跑过了。

## 6. 配置与部署

* 配置**只有 `config/settings.py` 一个来源**，全部从环境变量读，
  默认值只服务本机开发。新增配置项要同时更新 `.env.example`。
* 本工程刻意不引 `python-dotenv`：配置来源要一眼看得清，
  用 `set -a; source .env; set +a` 或进程管理器注入。
* 生产必须改 `PLATFORM_SECRET_KEY`、关 `PLATFORM_DEBUG`、收窄
  `PLATFORM_ALLOWED_HOSTS`，并用 gunicorn/uvicorn 而不是 `runserver`。
* 密码哈希用 Django 的 PBKDF2（无需额外依赖），不要自作主张换成 md5。
* **起停统一走 `scripts/run.sh`**（`repo:server-python/platform_server/scripts/run.sh`），
  它跑 `runserver --noreload` 并等 `/api/health/` 通过才算就绪，PID 记在 `.run/pids.json`。
  不要改回带自动重载的 `runserver`：reloader 会 fork 父进程，PID 文件记不到真正
  监听端口的那个进程，`stop` 后会留下继续占端口的孤儿。
  它**不替代** `manage.py`（`migrate` / `test` / `shell` / `makemigrations` 仍走 manage.py）。

## 7. 不要提交

`var/`（SQLite 开发库、静态文件收集目录）、`logs/`、`.env`、`__pycache__/`，
以及根规则已有的那些。见本目录 `.gitignore`。
