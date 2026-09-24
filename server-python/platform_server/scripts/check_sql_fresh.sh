#!/usr/bin/env bash
# 校验 `sql/db_scmj_admin.sql` 是否与当前的迁移/模型一致。
#
# 判据很直接：**重新生成一遍，逐字节比对**。不一致就说明有人改了模型或迁移
# 但忘了重新生成脚本——那种过期脚本会被当成事实用在建库和评审里，所以必须挡住。
#
# 用法（在 platform_server/ 下）：
#   ./scripts/check_sql_fresh.sh
#
# 不需要 MySQL：生成器用假连接驱动 Django 的 mysql 后端（见 scripts/gen_sql.py）。
set -euo pipefail

cd "$(dirname "$0")/.."

PY="../.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

TARGET="sql/db_scmj_admin.sql"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ ! -f "$TARGET" ]; then
  echo "✗ 缺少 $TARGET（先跑：$PY scripts/gen_sql.py --output $TARGET）" >&2
  exit 1
fi

"$PY" scripts/gen_sql.py --output "$TMP/regenerated.sql" >/dev/null

if diff -u "$TARGET" "$TMP/regenerated.sql" >"$TMP/diff.txt"; then
  echo "✓ $TARGET 与当前迁移一致"
  exit 0
fi

echo "✗ $TARGET 已过期：与当前迁移/模型不一致。" >&2
echo "  重新生成：$PY scripts/gen_sql.py --output $TARGET" >&2
echo >&2
head -40 "$TMP/diff.txt" >&2
exit 1
