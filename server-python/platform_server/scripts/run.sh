#!/usr/bin/env bash
# 管理平台后端（platform_server）的一键启停（薄壳，逻辑都在 scripts/serve.py 里）。
#
#   ./scripts/run.sh                启动 + 健康检查 + 状态表
#   ./scripts/run.sh stop           优雅停止
#   ./scripts/run.sh restart        先停后起（改完代码用这个）
#   ./scripts/run.sh status         只看状态（就绪退出码 0）
#   ./scripts/run.sh logs           跟踪日志
#   ./scripts/run.sh init           建表 + 建初始管理员（首次部署）
#   ./scripts/run.sh check          环境自检（不启动）
#
# 端口用 PLATFORM_PORT（默认 8000）；数据库后端用 PLATFORM_DB_ENGINE（默认 mysql）。
# 例：
#   PLATFORM_DB_ENGINE=sqlite ./scripts/run.sh init
#   PLATFORM_PORT=8010 ./scripts/run.sh
#
# 与游戏服务端（9000/9001/9002/9003/10000/12581）可以同时运行，端口不冲突。
set -euo pipefail
cd "$(dirname "$0")/.."

PY="../.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "找不到 $PY。先建虚拟环境并安装依赖："
  echo "  cd server-python"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  echo "  .venv/bin/pip install -r platform_server/requirements-platform.txt"
  exit 1
fi

# `-u` 关掉输出缓冲：脚本会先打提示、再转发给 `manage.py`（子进程），
# 缓冲会让提示跑到子进程输出之后，看起来像是乱序。
exec "$PY" -u scripts/serve.py "$@"
