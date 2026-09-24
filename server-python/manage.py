#!/usr/bin/env python3
"""server-python 的三进程管理脚本（对应 `server/start_all_mac.sh`）。

用法（`start_all_mac.sh` 只是它的一层壳）：

    ./start_all_mac.sh                 # 启动三个进程并打印状态表
    ./start_all_mac.sh status          # 只看状态；全部就绪退出码 0，否则 1
    ./start_all_mac.sh stop            # 优雅停止（只停本脚本启动的进程）
    ./start_all_mac.sh restart
    ./start_all_mac.sh logs game       # 跟踪某个进程的日志（account / hall / game）
    ./start_all_mac.sh --config /path/to/configs_win.py status

只依赖标准库与 `server-python/.venv`；PID 记在 `.run/pids.json`，
日志写 `logs/<名字>.log`（每次启动重写，只对应最近一次运行）。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / ".venv" / "bin" / "python"
RUN_DIR = HERE / ".run"
LOG_DIR = HERE / "logs"
PID_FILE = RUN_DIR / "pids.json"

PROCESSES = [
    ("account", "account_server.app", "账号服"),
    ("hall", "hall_server.app", "大厅服"),
    ("game", "game_server.app", "游戏服"),
]

DEFAULT_CONFIG = "../configs_mac.py"


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    print("找不到 server-python/.venv/bin/python。请先建虚拟环境并安装依赖：")
    print("  cd server-python && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
    raise SystemExit(1)


def _load_config(config_path: str) -> dict[str, int]:
    """按配置文件里的字段读出 6 个端口（不写死在脚本里）。"""
    code = (
        "import sys, json; sys.path.insert(0, %r);"
        "from utils.config import load_configs;"
        "c = load_configs(sys.argv[1], %r);"
        "print(json.dumps({'account': c.account_server()['CLIENT_PORT'],"
        "'dealer': c.account_server()['DEALDER_API_PORT'],"
        "'hall': c.hall_server()['CLEINT_PORT'],"
        "'hall_room': c.hall_server()['ROOM_PORT'],"
        "'game_http': c.game_server()['HTTP_PORT'],"
        "'game_client': c.game_server()['CLIENT_PORT']}))"
    ) % (str(HERE), str(HERE))
    result = subprocess.run(
        [_python(), "-c", code, config_path], capture_output=True, text=True, cwd=str(HERE)
    )
    if result.returncode != 0:
        print("读取配置失败，改用内置默认端口：")
        print(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "未知错误")
        return {
            "account": 9000,
            "dealer": 12581,
            "hall": 9001,
            "hall_room": 9002,
            "game_http": 9003,
            "game_client": 10000,
        }
    return json.loads(result.stdout.strip().splitlines()[-1])


PORTS_OF = {
    "account": ("account", "dealer"),
    "hall": ("hall", "hall_room"),
    "game": ("game_client", "game_http"),
}

LABEL_OF = {"account": "账号服", "hall": "大厅服", "game": "游戏服"}


def _read_pids() -> dict[str, int]:
    if not PID_FILE.is_file():
        return {}
    try:
        return {k: int(v) for k, v in json.loads(PID_FILE.read_text()).items()}
    except (ValueError, OSError):
        return {}


def _write_pids(pids: dict[str, int]) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(pids, indent=2))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _port_listening(port: int) -> int | None:
    """返回正在监听该端口的 PID；没人监听返回 None。

    优先用 `lsof` 拿真实 PID（这样状态表能区分"我们启动的进程在监听"与"被别人占着"）；
    拿不到 `lsof` 时退回到一次 TCP 连接探测，用 -1 表示"有人在监听但不知道是谁"。
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if out:
            return int(out.splitlines()[0])
        # lsof 可用且没有输出 = 确实没有人在监听
        return None
    except (OSError, ValueError):
        pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            return -1
    return None


def _tail(path: Path, lines: int = 12) -> str:
    if not path.is_file():
        return "(没有日志)"
    content = path.read_text(errors="replace").splitlines()
    return "\n".join(content[-lines:])


def cmd_start(config_path: str) -> int:
    ports = _load_config(config_path)
    pids = _read_pids()
    _python()  # 提前校验解释器存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    for name, module, _ in PROCESSES:
        if name in pids and _alive(pids[name]):
            print(f"{LABEL_OF[name]} 已在运行（PID {pids[name]}），跳过。")
            continue

        for key in PORTS_OF[name]:
            occupied = _port_listening(ports[key])
            if occupied is not None:
                owner = f"PID {occupied}" if occupied > 0 else "未知进程"
                print(f"{LABEL_OF[name]} 无法启动：端口 {ports[key]} 已被占用（{owner}）。")
                failures.append(name)
                break
        else:
            log_path = LOG_DIR / f"{name}.log"
            with log_path.open("w") as log:
                process = subprocess.Popen(
                    [_python(), "-u", "-m", module, config_path],
                    cwd=str(HERE),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            pids[name] = process.pid
            print(f"{LABEL_OF[name]} 启动中（PID {process.pid}）...")

    _write_pids(pids)

    # 等端口真的 listening（最多 15 秒）
    deadline = time.time() + 15
    while time.time() < deadline:
        if all(_port_listening(ports[key]) is not None for name, _, _ in PROCESSES if name not in failures for key in PORTS_OF[name]):
            break
        time.sleep(0.3)

    for name in failures:
        print(f"\n--- {LABEL_OF[name]} 日志尾部 ---")
        print(_tail(LOG_DIR / f"{name}.log"))

    return cmd_status(config_path, quiet=False)


def cmd_status(config_path: str, quiet: bool = True) -> int:
    ports = _load_config(config_path)
    pids = _read_pids()
    all_ready = True

    print()
    print("=" * 78)
    print(f" {'进程':<8} {'PID':>8}  {'端口状态':<34} 日志")
    print("=" * 78)
    for name, _module, _label in PROCESSES:
        pid = pids.get(name)
        running = pid is not None and _alive(pid)
        cells = []
        for key in PORTS_OF[name]:
            port = ports[key]
            listening = _port_listening(port)
            if listening is None:
                cells.append(f"{port}[未监听]")
                all_ready = False
            elif running and listening == pid:
                cells.append(f"{port}[监听中]")
            else:
                cells.append(f"{port}[被占用]")
        state = str(pid) if running else "未运行"
        if not running:
            all_ready = False
        print(f" {LABEL_OF[name]:<8} {state:>8}  {' '.join(cells):<34} logs/{name}.log")
    print("=" * 78)
    print(" 全部就绪" if all_ready else " 有进程未就绪（./start_all_mac.sh logs <名字> 看日志）")
    print()
    return 0 if all_ready else 1


def cmd_stop() -> int:
    pids = _read_pids()
    for name, _module, _label in PROCESSES:
        pid = pids.pop(name, None)
        if pid is None or not _alive(pid):
            continue
        print(f"停止 {LABEL_OF[name]}（PID {pid}）...")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
    _write_pids(pids)

    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.3)
        break
    return 0


def cmd_logs(config_path: str, name: str | None) -> int:
    targets = [name] if name else [n for n, _, _ in PROCESSES]
    files = [str(LOG_DIR / f"{n}.log") for n in targets]
    for path in files:
        if not os.path.isfile(path):
            print(f"日志不存在：{path}")
            return 1
    try:
        subprocess.run(["tail", "-n", "40", "-f", *files])
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default="start")
    parser.add_argument("name", nargs="?")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    args, extra = parser.parse_known_args()
    if extra and args.name is None:
        args.name = extra[0]

    command = args.command
    if command in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    if command == "start":
        return cmd_start(args.config)
    if command == "status":
        return cmd_status(args.config)
    if command == "stop":
        return cmd_stop()
    if command == "restart":
        cmd_stop()
        time.sleep(0.5)
        return cmd_start(args.config)
    if command == "logs":
        return cmd_logs(args.config, args.name)
    print(f"未知命令：{command}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
