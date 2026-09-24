#!/usr/bin/env python3
"""管理平台后端（platform_server）的启停脚本。

用法（`run.sh` 只是它的一层壳，接口与 `server-python/start_all_mac.sh` 保持一致）:

    ./scripts/run.sh                 # 启动 + 健康检查 + 状态表
    ./scripts/run.sh start           # 同上
    ./scripts/run.sh stop            # 优雅停止（只停本脚本启动的进程）
    ./scripts/run.sh restart         # 先停后起（改完代码用这个）
    ./scripts/run.sh status          # 只看状态；就绪退出码 0，否则 1
    ./scripts/run.sh logs            # 跟踪日志（Ctrl-C 退出）
    ./scripts/run.sh init            # 建表 + 建初始管理员（首次部署跑一次）

**不是** `manage.py` 的替代品：`manage.py` 是 Django 自己的命令入口
（`migrate` / `test` / `shell` / `makemigrations`），本脚本负责
"把服务跑起来 / 停下来 / 看状态"，两者互补。`init` 内部只是转发给 `manage.py`。

只依赖标准库；PID 记在 `.run/pids.json`，日志写 `logs/platform.log`
（每次启动重写，只对应最近一次运行）。服务以 `PLATFORM_PORT`（默认 8000）监听。

与游戏服务端（9000/9001/9002/9003/10000/12581）**可以同时运行**，端口不冲突。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------- 路径与常量

HERE = Path(__file__).resolve().parent.parent  # platform_server/
SERVER_PYTHON = HERE.parent  # server-python/
VENV_PYTHON = SERVER_PYTHON / ".venv" / "bin" / "python"
RUN_DIR = HERE / ".run"
LOG_DIR = HERE / "logs"
PID_FILE = RUN_DIR / "pids.json"
LOG_FILE = LOG_DIR / "platform.log"

#: 进程名（也是 PID 文件里的键）。
NAME = "platform"
LABEL = "管理平台"

#: 默认端口（与 `docs` / README 一致）。改端口用 PLATFORM_PORT。
DEFAULT_PORT = 8000

#: 游戏服务端占用的端口。同时起两套是允许的，但这几个端口绝不能被管理平台占用——
#: 一旦撞上，说明 `PLATFORM_PORT` 配错了，会让游戏服起不来。
GAME_SERVER_PORTS = {9000, 9001, 9002, 9003, 10000, 12581}

#: 等待启动的上限（秒）。
STARTUP_TIMEOUT = 20


def _python() -> str:
    """返回虚拟环境里的解释器；缺失时给出可执行的补救指引。"""
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    print(f"找不到 {VENV_PYTHON}。请先建虚拟环境并安装依赖：")
    print("  cd server-python")
    print("  python3 -m venv .venv")
    print("  .venv/bin/pip install -r requirements.txt")
    print("  .venv/bin/pip install -r platform_server/requirements-platform.txt")
    raise SystemExit(1)


def _port() -> int:
    """服务端口，来自 PLATFORM_PORT（与后端其它配置同一套环境变量风格）。"""
    raw = os.environ.get("PLATFORM_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        print(f"PLATFORM_PORT 不是合法端口号：{raw!r}，改用默认 {DEFAULT_PORT}。")
        return DEFAULT_PORT
    if not (1 <= port <= 65535):
        print(f"PLATFORM_PORT 超出范围：{port}，改用默认 {DEFAULT_PORT}。")
        return DEFAULT_PORT
    return port


def _db_engine() -> str:
    """当前数据库后端，仅用于状态表展示。"""
    return os.environ.get("PLATFORM_DB_ENGINE", "mysql").strip().lower()


# ---------------------------------------------------------------- PID 与端口


def _read_pids() -> dict[str, int]:
    """读 PID 文件；损坏时当作没有（下次启动会重新写）。"""
    if not PID_FILE.is_file():
        return {}
    try:
        return {k: int(v) for k, v in json.loads(PID_FILE.read_text()).items()}
    except (ValueError, OSError):
        return {}


def _write_pids(pids: dict[str, int]) -> None:
    """写 PID 文件。"""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(pids, indent=2))


def _alive(pid: int) -> bool:
    """进程是否还活着（信号 0 只做存在性检查）。"""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _port_listening(port: int) -> int | None:
    """返回正在监听该端口的 PID；没人监听返回 None。

    优先用 `lsof` 拿真实 PID，这样状态表能区分"我们启动的进程在监听"与
    "端口被别人占着"（后者必须报错，不能假装启动成功）；
    拿不到 `lsof` 时退回一次 TCP 连接探测，用 -1 表示"有人监听但不知道是谁"。
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if out:
            return int(out.splitlines()[0])
        return None
    except (OSError, ValueError):
        pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            return -1
    return None


def _health_ok(port: int, timeout: float = 2.0) -> bool:
    """探测 `/api/health/` 是否返回 200。

    **比"端口在监听"更强的判据**：Django 是"先绑端口、再初始化应用"，
    端口已经 listening 但应用还没就绪（甚至刚要崩）是常见状态。
    这个接口刻意不查数据库（见 `config/urls.py`），所以它能单独回答
    "Web 进程真的能服务请求了吗"。
    """
    try:
        import urllib.error
        import urllib.request

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health/", timeout=timeout
        ) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def _tail(path: Path, lines: int = 15) -> str:
    """取日志尾部若干行。"""
    if not path.is_file():
        return "(没有日志)"
    content = path.read_text(errors="replace").splitlines()
    return "\n".join(content[-lines:])


# ---------------------------------------------------------------- 子命令


def cmd_init() -> int:
    """建表 + 建初始管理员（转发给 manage.py，保持单一事实来源）。"""
    python = _python()
    cwd = str(HERE)

    print(f"[1/2] 建表（migrate，数据库后端：{_db_engine()}）...")
    result = subprocess.run([python, "manage.py", "migrate", "--no-input"], cwd=cwd)
    if result.returncode != 0:
        print()
        print("建表失败。最常见的原因是数据库连不上或库不存在：")
        print(f"  * MySQL：先建库 → CREATE DATABASE db_scmj_admin DEFAULT CHARACTER SET utf8mb4;")
        print("           口令等配置见 platform_server/.env.example")
        print("  * 没有 MySQL：用 PLATFORM_DB_ENGINE=sqlite ./scripts/run.sh init")
        return result.returncode

    print()
    print("[2/2] 建初始超级管理员（seed_admin，幂等；口令不会覆盖已有的）...")
    result = subprocess.run(
        [python, "manage.py", "seed_admin"], cwd=cwd
    )
    return result.returncode


def cmd_start() -> int:
    """启动服务并等它真的就绪。"""
    python = _python()
    port = _port()

    if port in GAME_SERVER_PORTS:
        print(f"PLATFORM_PORT={port} 是游戏服务端占用的端口，不能给管理平台用。")
        print(f"请换一个（默认 {DEFAULT_PORT}），例如：PLATFORM_PORT=8010 ./scripts/run.sh")
        return 2

    pids = _read_pids()
    existing = pids.get(NAME)
    if existing is not None and _alive(existing):
        print(f"{LABEL} 已在运行（PID {existing}），跳过启动。")
        return cmd_status(quiet=False)

    occupied = _port_listening(port)
    if occupied is not None:
        owner = f"PID {occupied}" if occupied > 0 else "未知进程"
        print(f"{LABEL} 无法启动：端口 {port} 已被占用（{owner}）。")
        print(f"  * 换个端口：PLATFORM_PORT=8010 ./scripts/run.sh")
        print(f"  * 或先停掉占用者：lsof -nP -iTCP:{port} -sTCP:LISTEN")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"启动 {LABEL}（端口 {port}，数据库 {_db_engine()}）...")
    with LOG_FILE.open("w") as log:
        process = subprocess.Popen(
            # `--noreload` 很关键：runserver 默认会 fork 一个 reloader 父进程，
            # 那样 PID 文件里记的是父进程，停止时子进程（真正监听端口的那个）
            # 会变成孤儿继续占着端口。关掉自动重载后就是单进程，PID 可精确管理。
            # 改完代码用 `./scripts/run.sh restart` 重启。
            [python, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
            cwd=str(HERE),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pids[NAME] = process.pid
    _write_pids(pids)
    print(f"{LABEL} 启动中（PID {process.pid}）...")

    # 等"健康检查通过"，而不只是"端口在监听"。
    deadline = time.time() + STARTUP_TIMEOUT
    ready = False
    while time.time() < deadline:
        if not _alive(process.pid):
            break
        if _health_ok(port):
            ready = True
            break
        time.sleep(0.3)

    if not ready:
        print()
        print(f"✗ {LABEL} 未能在 {STARTUP_TIMEOUT} 秒内就绪。日志尾部：")
        print("-" * 78)
        print(_tail(LOG_FILE))
        print("-" * 78)
        # 进程可能还活着（例如卡在数据库等待），停掉它避免留下半死不活的进程。
        if _alive(process.pid):
            print("正在停止未就绪的进程...")
            _terminate(process.pid)
        pids.pop(NAME, None)
        _write_pids(pids)
        return 1

    return cmd_status(quiet=False)


def cmd_status(quiet: bool = True) -> int:
    """打印状态表；就绪返回 0，否则 1。"""
    port = _port()
    pids = _read_pids()
    pid = pids.get(NAME)
    running = pid is not None and _alive(pid)

    listener = _port_listening(port)
    healthy = running and _health_ok(port)

    if not quiet:
        print()
    print("=" * 78)
    print(f" {'进程':<8} {'PID':>8}  {'端口':<18} {'健康检查':<10} 日志")
    print("=" * 78)

    if listener is None:
        port_cell = f"{port} 未监听"
    elif running and listener == pid:
        port_cell = f"{port} 监听中"
    elif listener == -1:
        port_cell = f"{port} 监听中(?)"
    else:
        port_cell = f"{port} 被占用(PID {listener})"

    print(
        f" {LABEL:<8} {(str(pid) if running else '未运行'):>8}  "
        f"{port_cell:<18} {('ok' if healthy else '-'):<10} logs/platform.log"
    )
    print("=" * 78)

    if healthy:
        print(f" 已就绪：http://127.0.0.1:{port}/  （登录页在 admin-platform 的 5173）")
    elif running:
        print(" 进程在跑但健康检查未通过（./scripts/run.sh logs 看日志）")
    else:
        print(" 未运行（./scripts/run.sh 启动）")
    print()
    return 0 if healthy else 1


def _terminate(pid: int, grace: float = 8.0) -> bool:
    """先 SIGTERM，超时再 SIGKILL。返回是否确认已退出。"""
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True

    deadline = time.time() + grace
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.2)

    print(f"  PID {pid} 未在 {grace:.0f} 秒内退出，强制结束。")
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    time.sleep(0.3)
    return not _alive(pid)


def cmd_stop() -> int:
    """优雅停止（只停本脚本启动的进程）。"""
    pids = _read_pids()
    pid = pids.get(NAME)

    if pid is None or not _alive(pid):
        print(f"{LABEL} 未在运行。")
        pids.pop(NAME, None)
        _write_pids(pids)
        return 0

    print(f"停止 {LABEL}（PID {pid}）...")
    stopped = _terminate(pid)
    pids.pop(NAME, None)
    _write_pids(pids)

    port = _port()
    if stopped and _port_listening(port) is None:
        print("已停止。")
        return 0
    if not stopped:
        print("✗ 进程仍在运行，请手动检查。")
        return 1
    # 进程没了但端口还被占：不是我们启的那个（或是 TIME_WAIT 等残留）。
    print(f"注意：进程已退出，但端口 {port} 仍显示被占用，请确认没有别的实例。")
    return 1


def cmd_logs() -> int:
    """跟踪日志（Ctrl-C 退出）。"""
    if not LOG_FILE.is_file():
        print(f"日志不存在：{LOG_FILE}（先启动一次）")
        return 1
    print(f"跟踪 {LOG_FILE}（Ctrl-C 退出）")
    try:
        subprocess.run(["tail", "-n", "40", "-f", str(LOG_FILE)])
    except KeyboardInterrupt:
        pass
    return 0


def cmd_check() -> int:
    """环境自检：解释器、依赖、数据库连通性、待应用的迁移。

    回答"现在 `start` 会不会成功"，而不是启动失败了再去翻日志。
    """
    problems = 0

    print("[1/4] 解释器")
    if VENV_PYTHON.is_file():
        print(f"      {VENV_PYTHON}")
    else:
        print(f"      ✗ 找不到 {VENV_PYTHON}")
        problems += 1

    print("[2/4] 依赖与服务端口")
    python = str(VENV_PYTHON) if VENV_PYTHON.is_file() else "python3"
    result = subprocess.run(
        [python, "-c", "import django, rest_framework; print(django.get_version())"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"      Django {result.stdout.strip()} + DRF 已安装")
    else:
        print("      ✗ Django/DRF 未安装，先跑：")
        print(f"        {python} -m pip install -r requirements-platform.txt")
        problems += 1

    port = _port()
    if port in GAME_SERVER_PORTS:
        print(f"      ✗ PLATFORM_PORT={port} 与游戏服务端冲突")
        problems += 1
    else:
        print(f"      服务端口 {port}（数据库后端 {_db_engine()}）")

    print("[3/4] 数据库连通性与迁移状态")
    problem = _database_problem(python)
    if problem is None:
        print("      数据库可连，且没有未应用的迁移")
    else:
        print(f"      ✗ {problem}")
        problems += 1

    print("[4/4] 启动方式")
    if shutil.which("gunicorn"):
        print("      gunicorn 可用（生产推荐）")
    else:
        print("      runserver（开发用；生产请装 gunicorn/uvicorn，见 README）")
    print(f"      将监听 127.0.0.1:{port}")

    print()
    if problems == 0:
        print("✓ 自检通过（./scripts/run.sh 启动）")
        return 0
    print(f"✗ 有 {problems} 项需要处理")
    return 1


def _database_problem(python: str) -> str | None:
    """检查数据库，返回问题描述；一切正常时返回 None。

    刻意**不用** `manage.py migrate --check`：它只比对迁移文件与依赖图，
    **完全不连数据库**（实测 MySQL 连不上时它照样返回 0），
    拿它判断"库能不能用"会给出假阴性。这里自己探两件事：

    1. `connection.ensure_connection()` —— 真的建一次连接；
    2. 连上之后，比对 `django_migrations` 里已应用的集合与磁盘上的迁移集合，
       差集就是待应用的迁移。
    """
    probe = (
        "from django.db import connection;"
        "from django.db.migrations.executor import MigrationExecutor;"
        "connection.ensure_connection();"
        "loader = MigrationExecutor(connection).loader;"
        "pending = sorted('%s.%s' % n for n in set(loader.graph.nodes) - set(loader.applied_migrations));"
        "print('PENDING:' + ','.join(pending))"
    )
    result = subprocess.run(
        [python, "manage.py", "shell", "-c", probe],
        cwd=str(HERE),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        tail = detail[-1] if detail else "未知错误"
        return (
            f"数据库连不上或不可用（{tail}）\n"
            "        * MySQL：确认服务在跑、库已建、口令正确"
            "（见 platform_server/.env.example）\n"
            "        * 没有 MySQL：PLATFORM_DB_ENGINE=sqlite ./scripts/run.sh init"
        )

    marker = [line for line in result.stdout.splitlines() if line.startswith("PENDING:")]
    if not marker:
        return "无法解析迁移状态（manage.py shell 输出异常）"
    pending = [name for name in marker[0][len("PENDING:") :].split(",") if name]
    if pending:
        shown = ", ".join(pending[:3]) + ("..." if len(pending) > 3 else "")
        return f"有 {len(pending)} 条迁移未应用（{shown}）——先跑 ./scripts/run.sh init"
    return None


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default="start")
    args = parser.parse_args()

    command = args.command
    if command in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    if command == "start":
        return cmd_start()
    if command == "status":
        return cmd_status(quiet=False)
    if command == "stop":
        return cmd_stop()
    if command == "restart":
        code = cmd_stop()
        if code != 0:
            print("停止未完全成功，仍继续启动（端口可能仍被占用）。")
        return cmd_start()
    if command == "logs":
        return cmd_logs()
    if command == "init":
        return cmd_init()
    if command == "check":
        return cmd_check()

    print(f"未知命令：{command}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
