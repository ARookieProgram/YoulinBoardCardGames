#!/usr/bin/env bash
# 管理平台端到端验收脚本：登录闭环 + 玩家管理（本机手工跑，不进门禁）。
#
# 前置：
#   1) platform_server 已在 127.0.0.1:8000 运行，且已 seed_admin；
#   2) 玩家库（`DATABASES["player"]`）可连——第 9 节的封禁 / 解封断言需要库里有
#      **未被封禁**的玩家；没有数据时这一小段会自动跳过并打印提示，不算失败。
#
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

echo "== 9. 玩家管理（只读数据源 + 封禁流水）=="

# 第 8 节已经退出了登录态，这里重新登一次拿新的 access。
login2=$(curl -s -X POST "$BASE/api/auth/login/" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
access2=$(jq_get "$login2" "['data']['access']")

# 9.1 认证与权限下限
nologin=$(curl -s -w '\n%{http_code}' "$BASE/api/players/")
check "无令牌访问玩家列表返回 401" "401" "$(printf '%s' "$nologin" | tail -1)"
check "无令牌 code=10002" "10002" "$(jq_get "$(printf '%s' "$nologin" | sed '$d')" "['code']")"

# 9.2 概览与列表（列表能力 = 只读数据源的核心）
overview=$(curl -s "$BASE/api/players/overview/" -H "Authorization: Bearer $access2")
check "玩家概览 code=0" "0" "$(jq_get "$overview" "['code']")"

list=$(curl -s "$BASE/api/players/?page=1&page_size=5" -H "Authorization: Bearer $access2")
check "玩家列表 code=0" "0" "$(jq_get "$list" "['code']")"
check "列表含分页键 items" "yes" "$(printf '%s' "$list" | grep -q '"items"' && echo yes || echo no)"
check "列表含房卡字段 gems" "yes" "$(printf '%s' "$list" | grep -q '"gems"' && echo yes || echo no)"

# 9.3 参数校验与不存在
badparam=$(curl -s -w '\n%{http_code}' "$BASE/api/players/?page_size=0" -H "Authorization: Bearer $access2")
check "非法分页参数 HTTP 400" "400" "$(printf '%s' "$badparam" | tail -1)"
check "非法分页参数 code=10001" "10001" "$(jq_get "$(printf '%s' "$badparam" | sed '$d')" "['code']")"

missing=$(curl -s -w '\n%{http_code}' "$BASE/api/players/999999/" -H "Authorization: Bearer $access2")
check "玩家不存在 HTTP 404" "404" "$(printf '%s' "$missing" | tail -1)"
check "玩家不存在 code=12001" "12001" "$(jq_get "$(printf '%s' "$missing" | sed '$d')" "['code']")"

# 9.4 预留入口：契约已定，数据源待接入（不访问玩家库，任意 ID 都有答复）
games=$(curl -s "$BASE/api/players/999999/games/" -H "Authorization: Bearer $access2")
check "对局记录入口已预留" "True" "$(jq_get "$games" "['data']['reserved']")"
check "对局记录入口分页形状不变" "0" "$(jq_get "$games" "['data']['total']")"

recharges=$(curl -s "$BASE/api/players/999999/recharges/" -H "Authorization: Bearer $access2")
check "充值记录入口已预留" "True" "$(jq_get "$recharges" "['data']['reserved']")"

# 9.5 封禁 / 解封：需要玩家库里有**未被封禁**的玩家
normal=$(curl -s "$BASE/api/players/?ban_state=normal&page_size=1" -H "Authorization: Bearer $access2")
player_id=$(printf '%s' "$normal" | python3 -c \
  "import json,sys;d=json.load(sys.stdin);items=d['data']['items'];print(items[0]['player_id'] if items else '')" \
  2>/dev/null || echo "")

if [ -z "$player_id" ]; then
  printf '  \033[33m!\033[0m 玩家库没有可用的玩家数据，跳过封禁 / 解封断言（导入玩家数据后再跑本段）\n'
else
  detail=$(curl -s "$BASE/api/players/$player_id/" -H "Authorization: Bearer $access2")
  check "玩家详情 code=0" "0" "$(jq_get "$detail" "['code']")"
  check "详情返回同一玩家" "$player_id" "$(jq_get "$detail" "['data']['player_id']")"

  banned=$(curl -s -X POST "$BASE/api/players/$player_id/ban/" \
    -H "Authorization: Bearer $access2" -H 'Content-Type: application/json' \
    -d '{"reason":"e2e 自动验收","duration_hours":1}')
  check "封禁 code=0" "0" "$(jq_get "$banned" "['code']")"
  check "封禁后 banned=true" "True" "$(jq_get "$banned" "['data']['banned']")"

  again=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/players/$player_id/ban/" \
    -H "Authorization: Bearer $access2" -H 'Content-Type: application/json' \
    -d '{"reason":"重复封禁"}')
  check "重复封禁 HTTP 400" "400" "$(printf '%s' "$again" | tail -1)"
  check "重复封禁 code=12002" "12002" "$(jq_get "$(printf '%s' "$again" | sed '$d')" "['code']")"

  filtered=$(curl -s "$BASE/api/players/?ban_state=banned&keyword=$player_id" \
    -H "Authorization: Bearer $access2")
  check "封禁状态过滤能查到该玩家" "True" \
    "$(printf '%s' "$filtered" | python3 -c \
      "import json,sys;d=json.load(sys.stdin);print(d['data']['total'] > 0)" 2>/dev/null || echo "")"

  unbanned=$(curl -s -X POST "$BASE/api/players/$player_id/unban/" \
    -H "Authorization: Bearer $access2" -H 'Content-Type: application/json' \
    -d '{"reason":"e2e 自动验收收尾"}')
  check "解封 code=0" "0" "$(jq_get "$unbanned" "['code']")"
  check "解封后 banned=false" "False" "$(jq_get "$unbanned" "['data']['banned']")"

  again2=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/players/$player_id/unban/" \
    -H "Authorization: Bearer $access2" -H 'Content-Type: application/json' -d '{}')
  check "重复解封 HTTP 400" "400" "$(printf '%s' "$again2" | tail -1)"
  check "重复解封 code=12003" "12003" "$(jq_get "$(printf '%s' "$again2" | sed '$d')" "['code']")"
fi

echo "== 10. 内部封禁校验接口（游戏服调的就是它）=="
# 共享密钥必须与游戏服配置 ban_check()["PRI_KEY"] 一致；两边都是开发默认值时可不用传。
INTERNAL_KEY="${E2E_INTERNAL_KEY:-scmj-ban-check-dev-key}"
ban_sign() { # ban_sign <拼接串> → md5
  python3 -c "import hashlib,sys;print(hashlib.md5(sys.argv[1].encode()).hexdigest())" "$1"
}

# 10.1 认证：没有签名、签名不对都必须拒绝，而不是放行
nosign=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/internal/players/ban-check/?account=guest_123456")
check "内部接口无签名 HTTP 403" "403" "$nosign"
nosign_body=$(curl -s "$BASE/api/internal/players/ban-check/?account=guest_123456")
check "内部接口无签名 code=10003" "10003" "$(jq_get "$nosign_body" "['code']")"
wrongsign=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/internal/players/ban-check/?account=guest_123456&sign=deadbeef")
check "内部接口错误签名 HTTP 403" "403" "$wrongsign"

# 10.2 未登录也能调（调用方是游戏服进程，不走 JWT）
target=$(curl -s "$BASE/api/players/?ban_state=normal&page_size=1" -H "Authorization: Bearer $access2")
target_id=$(printf '%s' "$target" | python3 -c \
  "import json,sys;d=json.load(sys.stdin);items=d['data']['items'];print(items[0]['player_id'] if items else '')" \
  2>/dev/null || echo "")
target_account=$(printf '%s' "$target" | python3 -c \
  "import json,sys;d=json.load(sys.stdin);items=d['data']['items'];print(items[0]['account'] if items else '')" \
  2>/dev/null || echo "")

if [ -z "$target_id" ]; then
  printf '  \033[33m!\033[0m 玩家库没有可用玩家，跳过内部接口的查询断言\n'
else
  by_account=$(curl -s "$BASE/api/internal/players/ban-check/?account=$target_account&sign=$(ban_sign "account${target_account}player_id${INTERNAL_KEY}")")
  check "按 account 查询 code=0" "0" "$(jq_get "$by_account" "['code']")"
  check "按 account 回带同一 player_id" "$target_id" "$(jq_get "$by_account" "['data']['player_id']")"

  sign_id=$(ban_sign "accountplayer_id${target_id}${INTERNAL_KEY}")
  by_id=$(curl -s "$BASE/api/internal/players/ban-check/?player_id=$target_id&sign=$sign_id")
  check "按 player_id 查询 code=0" "0" "$(jq_get "$by_id" "['code']")"
  check "未封禁的人 banned=false" "False" "$(jq_get "$by_id" "['data']['banned']")"

  # 10.3 封禁 → 内部接口必须立刻反映（游戏服据此拦人）
  curl -s -X POST "$BASE/api/players/$target_id/ban/" -H "Authorization: Bearer $access2" \
    -H 'Content-Type: application/json' -d '{"reason":"e2e 内部接口验收"}' >/dev/null
  banned_view=$(curl -s "$BASE/api/internal/players/ban-check/?player_id=$target_id&sign=$sign_id")
  check "封禁后 banned=true" "True" "$(jq_get "$banned_view" "['data']['banned']")"
  check "封禁后回带原因" "e2e 内部接口验收" "$(jq_get "$banned_view" "['data']['reason']")"

  curl -s -X POST "$BASE/api/players/$target_id/unban/" -H "Authorization: Bearer $access2" \
    -H 'Content-Type: application/json' -d '{"reason":"e2e 内部接口验收收尾"}' >/dev/null
  after_view=$(curl -s "$BASE/api/internal/players/ban-check/?player_id=$target_id&sign=$sign_id")
  check "解封后 banned=false" "False" "$(jq_get "$after_view" "['data']['banned']")"
fi

echo
echo "通过 $pass 项，失败 $fail 项"
[ "$fail" -eq 0 ]
