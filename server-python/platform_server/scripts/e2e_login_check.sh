#!/usr/bin/env bash
# 管理平台登录闭环的端到端验收脚本（本机手工跑，不进门禁）。
#
# 前置：platform_server 已在 127.0.0.1:8000 运行，且已 seed_admin。
# 用法：./scripts/e2e_login_check.sh [base_url]
set -uo pipefail

BASE="${1:-http://127.0.0.1:8000}"
USERNAME="${E2E_USERNAME:-admin}"
PASSWORD="${E2E_PASSWORD:-AdminPass!2024}"

pass=0
fail=0

check() { # check <描述> <期望> <实际>
  if [ "$2" = "$3" ]; then
    printf '  \033[32m✓\033[0m %s\n' "$1"
    pass=$((pass + 1))
  else
    printf '  \033[31m✗\033[0m %s (期望 %s，实际 %s)\n' "$1" "$2" "$3"
    fail=$((fail + 1))
  fi
}

jq_get() { printf '%s' "$1" | python3 -c "import json,sys;d=json.load(sys.stdin);print(eval('d'+sys.argv[1]))" "$2" 2>/dev/null || echo ""; }

echo "== 1. 健康检查 =="
health=$(curl -s -w '\n%{http_code}' "$BASE/api/health/")
check "GET /api/health/ 返回 200" "200" "$(printf '%s' "$health" | tail -1)"
check "健康检查 code=0" "0" "$(jq_get "$(printf '%s' "$health" | sed '$d')" "['code']")"

echo "== 2. 登录成功 =="
login=$(curl -s -X POST "$BASE/api/auth/login/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
check "登录 code=0" "0" "$(jq_get "$login" "['code']")"
access=$(jq_get "$login" "['data']['access']")
refresh=$(jq_get "$login" "['data']['refresh']")
check "返回 access" "yes" "$([ -n "$access" ] && echo yes || echo no)"
check "返回 refresh" "yes" "$([ -n "$refresh" ] && echo yes || echo no)"
check "返回 user.username" "$USERNAME" "$(jq_get "$login" "['data']['user']['username']")"
check "响应不含口令字段" "no" "$(printf '%s' "$login" | grep -q '"password"' && echo yes || echo no)"

echo "== 3. 账号名大小写不敏感 =="
upper=$(curl -s -X POST "$BASE/api/auth/login/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$(printf '%s' "$USERNAME" | tr '[:lower:]' '[:upper:]')\",\"password\":\"$PASSWORD\"}")
check "大写账号也能登录" "0" "$(jq_get "$upper" "['code']")"

echo "== 4. 口令错误 =="
bad=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/auth/login/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"definitely-wrong\"}")
check "口令错误 HTTP 400" "400" "$(printf '%s' "$bad" | tail -1)"
check "口令错误 code=11001" "11001" "$(jq_get "$(printf '%s' "$bad" | sed '$d')" "['code']")"

echo "== 5. 账号不存在（与口令错误不可区分）=="
nouser=$(curl -s -X POST "$BASE/api/auth/login/" -H 'Content-Type: application/json' \
  -d '{"username":"no-such-admin-xyz","password":"definitely-wrong"}')
check "账号不存在 code=11001" "11001" "$(jq_get "$nouser" "['code']")"
check "文案与口令错误一致" \
  "$(jq_get "$(printf '%s' "$bad" | sed '$d')" "['message']")" \
  "$(jq_get "$nouser" "['message']")"

echo "== 6. 当前用户 =="
me=$(curl -s -w '\n%{http_code}' "$BASE/api/auth/me/" -H "Authorization: Bearer $access")
check "GET /me/ 返回 200" "200" "$(printf '%s' "$me" | tail -1)"
check "/me/ 返回同一账号" "$USERNAME" "$(jq_get "$(printf '%s' "$me" | sed '$d')" "['data']['username']")"

anon=$(curl -s -w '\n%{http_code}' "$BASE/api/auth/me/")
check "无令牌访问 /me/ 返回 401" "401" "$(printf '%s' "$anon" | tail -1)"
check "无令牌 code=10002" "10002" "$(jq_get "$(printf '%s' "$anon" | sed '$d')" "['code']")"

echo "== 7. 刷新令牌（轮换）=="
refreshed=$(curl -s -X POST "$BASE/api/auth/refresh/" -H 'Content-Type: application/json' \
  -d "{\"refresh\":\"$refresh\"}")
check "刷新 code=0" "0" "$(jq_get "$refreshed" "['code']")"
check "刷新返回新的 access" "yes" "$([ -n "$(jq_get "$refreshed" "['data']['access']")" ] && echo yes || echo no)"
new_refresh=$(jq_get "$refreshed" "['data']['refresh']")
check "刷新返回轮换后的 refresh" "yes" "$([ -n "$new_refresh" ] && echo yes || echo no)"

reuse=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/auth/refresh/" -H 'Content-Type: application/json' \
  -d "{\"refresh\":\"$refresh\"}")
check "旧 refresh 复用被拒（401）" "401" "$(printf '%s' "$reuse" | tail -1)"
check "旧 refresh 复用 code=11003" "11003" "$(jq_get "$(printf '%s' "$reuse" | sed '$d')" "['code']")"

echo "== 8. 退出登录 =="
logout=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/auth/logout/" \
  -H "Authorization: Bearer $access" -H 'Content-Type: application/json' \
  -d "{\"refresh\":\"$new_refresh\"}")
check "退出返回 200" "200" "$(printf '%s' "$logout" | tail -1)"
check "退出 revoked=true" "True" "$(jq_get "$(printf '%s' "$logout" | sed '$d')" "['data']['revoked']")"

after=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/auth/refresh/" -H 'Content-Type: application/json' \
  -d "{\"refresh\":\"$new_refresh\"}")
check "退出后 refresh 失效（401）" "401" "$(printf '%s' "$after" | tail -1)"

echo
echo "通过 $pass 项，失败 $fail 项"
[ "$fail" -eq 0 ]
