#!/usr/bin/env bash
# server-python 的三进程一键启停（薄壳，逻辑都在 manage.py 里）。
#
#   ./start_all_mac.sh                 一键启动 + 状态表
#   ./start_all_mac.sh status          只看状态（全部就绪退出码 0）
#   ./start_all_mac.sh stop            优雅停止
#   ./start_all_mac.sh restart         先停后起
#   ./start_all_mac.sh logs game       跟踪某个进程的日志
#   ./start_all_mac.sh --config /abs/path/configs_win.py status
set -euo pipefail
cd "$(dirname "$0")"
PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "找不到 $PY。先建虚拟环境："
  echo "  cd server-python && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
exec "$PY" manage.py "$@"
