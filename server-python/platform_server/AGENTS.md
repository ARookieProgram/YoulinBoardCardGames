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

1. **不读玩家库、不写玩家库**。管理平台的 ORM 里没有 `t_accounts` / `t_users` /
   `t_rooms`，也不要为了"顺手查一下"去 `import` `repo:server-python/utils/db.py`。
2. **不复用 `t_accounts` 当管理员表**。玩家侧口令是明文且玩家可自行注册，
   拿它做后台等于没有防线。
3. **不签发游戏 token、不校验游戏 token**。两套 token 的算法、密钥、信任域都不同。
4. **不改 `t_accounts.password` 的明文存储方式**。要改就去改游戏服务端两边
   （`repo:server/` 与 `repo:server-python/` 成对改），不能从管理平台侧偷偷动。
5. 需要展示玩家数据时，走账号服/大厅服已有的 HTTP 接口，或另加只读数据源，
   并把数据来源与权限边界写进 README。

**第 5 条已经落地为玩家管理**（`apps/players/`），边界是：

* 唯一读玩家库的地方是 `apps/players/player_source.py`，走
  `settings.DATABASES["player"]`，**只执行 SELECT**（`_assert_read_only()` 硬校验，
  `tests/test_players.py::PlayerSourceIsolationTests` 断言玩家库连接上没有非 SELECT）；
* 玩家库上**没有模型、没有迁移**（`PlayerBan` 落本平台的 `db_scmj_admin`）；
* 不 import 游戏服的 `utils/db.py`，也不共享它的连接池；
* 数据来源与权限边界写在 `repo:server-python/platform_server/README.md` §6。

**房间管理**（`apps/rooms/`）是同一个红线的第二个落点：它要读的 `t_rooms`
也在玩家库里，所以**复用 `player_source.py` 那条通道**（房间查询就在该文件里，
`apps/rooms/` 只有视图与序列化器，自己不连库、不拼 SQL）。
`tests/test_rooms.py::RoomSourceIsolationTests` 用 AST 与执行期两种方式钉住这一点；
房间数据同样**不落本平台的库**（`apps/rooms/` 没有模型，所以也**不用**加进
`scripts/gen_sql.py` 的 `PLATFORM_APP_LABELS`）。

第 1 条说的是"不要顺手去读玩家表"，第 5 条是它的**唯一例外通道**：
要走 `player_source`，不要另开第二条。凡是往玩家库写的想法（包括封禁状态）
都属于游戏服务端的范畴，必须成对改 `repo:server/` 与 `repo:server-python/`，
不能在管理平台侧实现。

**反方向也有一条通道**：游戏服要读封禁状态时走 `/api/internal/players/ban-check/`
（`apps/players/internal.py`）——共享密钥认证、只读、走 HTTP，**不要**让游戏服直连
`db_scmj_admin`（那会把本平台的表结构变成对外契约）。密钥是
`PLATFORM_INTERNAL_KEY`，与游戏服 `ban_check()["PRI_KEY"]` 必须逐字一致；
不一致时游戏服 fail-open，表现为"封禁静默失效"。`/api/internal/` 前缀是信任边界，
部署时应在反向代理上限制成只允许游戏服网络访问。

`repo:server-python/platform_server/tests/test_auth.py::AccountIsolationTests`
把第 1、2 条钉成了断言；`tests/test_players.py::PlayerSourceIsolationTests`
把上面这套玩家库边界钉成了断言。

## 3. 目录约定

```
platform_server/
├─ manage.py                     Django 入口
├─ requirements-platform.txt     **独立**依赖清单（不要并进 requirements.txt）
├─ .env.example                  环境变量模板
├─ config/                       工程配置（settings 是唯一配置来源）
├─ apps/common/                  响应外壳 / 错误码 / 异常 / 分页 / IP
├─ apps/accounts/                管理平台账号体系（模型 / 序列化 / 视图 / 权限）
├─ apps/players/                 玩家管理（只读玩家库 player_source：t_users + t_rooms
│                                 + 封禁流水 PlayerBan + 给游戏服的内部校验 internal.py）
├─ apps/rooms/                   房间管理（只读监控 t_rooms；**没有模型**，
│                                 只有 serializers / views / urls / exceptions）
├─ sql/db_scmj_admin.sql         **生成产物**：建库脚本（不要手改，见 §4.4）
└─ scripts/
    ├─ run.sh / serve.py         启停脚本（start/stop/restart/status/logs/init/check）
    ├─ gen_sql.py                生成上面的 SQL（不需要 MySQL）
    ├─ check_sql_fresh.sh        校验 SQL 是否与迁移一致
    └─ e2e_login_check.sh        真实 HTTP 端到端验收
```

**新增业务模块**放 `apps/<模块>/`，并在 `config/settings.py` 的 `INSTALLED_APPS`
里注册 `apps.<模块>`（`apps/` 是命名空间包，`label` 在各自 `apps.py` 里显式指定），
同时把 label 加进 `scripts/gen_sql.py` 的 `PLATFORM_APP_LABELS`——
否则建库脚本末尾的 schema 速查会漏掉它的表（见 §4.4）。
**没有模型的模块（如 `apps/rooms/`）不用加进 `PLATFORM_APP_LABELS`**：
那里是给"本平台的表"做速查的，没有表就没什么可列的。

## 4. 五条容易踩的坑

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
`apps/accounts/error_codes.py`、`apps/players/error_codes.py`、
`apps/rooms/error_codes.py` 都只是转出口，不是第二份定义。
新增登录相关码加在 `11xxx` 段，玩家管理相关码加在 `12xxx` 段，
房间管理相关码加在 `13xxx` 段；
前端对应常量在 `repo:admin-platform/src/api/types.ts` 的 `ErrorCode`，要同步改。
内部接口（`/api/internal/`）的签名失败复用通用 `10003`、未配置密钥用 `10500`，
没有单开新码——它们不是给玩家看的业务错误。

**"玩家库连不上"只有一个码**（`12004`）：房间数据与玩家数据来自同一条只读数据源，
运维处置方式相同，所以房间侧**不要**再开一个 `13xxx` 的"数据源不可用"。
房间侧目前只有 `13001`（房间不存在）。

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

### 4.5 玩家库别名只读，且测试库是独立的一份

`settings.DATABASES["player"]` 是玩家库（`db_scmj`）的**只读**别名：

* 只有 `apps/players/player_source.py` 用它（`t_users` 与 `t_rooms` 都走它），
  SQL 必须过 `_assert_read_only()`（单条 SELECT）。
  **不要**在这个别名上跑迁移、建表或写数据；
* 别名的 `TEST.NAME` 是 `None`：测试库由 Django 另建（SQLite 内存库 / MySQL 的
  `test_db_scmj`），`tests/test_players.py` 与 `tests/test_rooms.py` 各自
  `CREATE TABLE`。所以**跑 `manage.py test` 永远不会碰真实 `db_scmj`**；
* 玩家库连不上时接口返回 `12004`（503），不是 500。新增玩家相关查询时，
  让异常冒到 `PlayerSourceUnavailable`，不要在视图里吞掉；
* 玩家表**没有**对应 Django 模型，字段口径（例如 `name` 是 Base64）
  记在 `player_source.py` 的模块文档里，改查询前先读它。

## 5. 改完怎么验证

```bash
cd server-python/platform_server

# 1) 接口测试（不需要 MySQL）。129 项（登录 29 + 玩家管理 55 + 房间管理 32 + 建库脚本自检 13）。
PLATFORM_DB_ENGINE=sqlite ../.venv/bin/python manage.py test

# 1b) 建库 SQL 是否与迁移一致（改了模型必跑）
./scripts/check_sql_fresh.sh

# 2) 真实 HTTP 端到端。74 项（登录 24 + 玩家管理 24 + 内部校验接口 10 + 房间管理 16）。
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
