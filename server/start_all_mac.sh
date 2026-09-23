#!/bin/bash
#
# 幼麟四川麻将 · 服务端一键启动 / 停止 / 运行状态（macOS）
#
# 用法：
#   ./start_all_mac.sh                 一键启动三个进程，随后打印运行状态（缺省命令）
#   ./start_all_mac.sh start           同上
#   ./start_all_mac.sh stop            停止三个进程（SIGTERM，等待优雅退出）
#   ./start_all_mac.sh restart         先停后起
#   ./start_all_mac.sh status          只打印运行状态（全部就绪退出码 0，否则 1）
#   ./start_all_mac.sh logs [名字]      跟踪日志；名字取 account / hall / game，缺省为全部
#   ./start_all_mac.sh help            显示本帮助
#
# 选项：
#   --config <文件>                     配置文件，缺省 ../configs_mac.js（端口从它里面读）
#
# 相比原来三行 nohup 的改动：
#   1. 先 cd 到脚本所在目录，在任何 cwd 下执行都能正确找到 ../configs_mac.js；
#   2. 端口不再写死，而是用 node require 配置文件按字段读出（改了配置，状态表自动跟着变）；
#   3. PID 记在 .run/pids；stop / restart / status 不再靠猜；
#   4. 日志按进程分开写 logs/account.log 等（原先三个进程混在一个 nohup.out 里）；
#   5. 启动后按端口轮询，真的 listening 才算"就绪"；失败时打印日志尾部，不再"提示成功、随即崩掉"；
#   6. 状态表：进程 / PID / 运行时长 / 每个端口是否在监听 / 日志路径。
#
# 进程与端口的对应关系（mac 默认配置，权威来源仍是 configs_mac.js）：
#   账号服  9000 客户端 HTTP、12581 渠道/代理 API
#   大厅服  9001 客户端 HTTP、9002 游戏服上报 HTTP
#   游戏服  10000 客户端 Socket.IO、9003 内部 HTTP
#
# 本脚本刻意只用 bash 3.2（macOS 自带）支持的特性：没有关联数组、没有 mapfile。
# 也刻意不用 ps：只用 kill -0 判断存活、lsof 判断端口，二者在受限环境下更可靠。
#
# 改这个脚本前先看这个坑：macOS 的 bash 3.2 有个多字节 bug —— `$VAR` 后面紧跟中文字符时，
# 中文字符的首字节会被并进变量名，结果变量展开成空、中文变成乱码。
# 所以下面凡 `$VAR` 后面直接跟中文的地方一律写成 `${VAR}`。改完先 `bash -n start_all_mac.sh`
# 过语法，再 `./start_all_mac.sh status` 看一眼中文输出是否正常。

# 就绪与停止的等待上限（秒），可用环境变量覆盖
WAIT_SECONDS="${WAIT_SECONDS:-15}"
STOP_SECONDS="${STOP_SECONDS:-10}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# 运行期产物：PID 文件与分进程日志。二者都在 .gitignore 里（logs/*.log 命中的是根级 *.log）
RUN_DIR=".run"
PID_FILE="$RUN_DIR/pids"
LOG_DIR="logs"

# CONFIG 是"传给 node 的写法"：三个 app.js 都是 require(process.argv[2])，相对路径按各自
# 模块所在目录解析，所以 account_server/app.js 收到 "../configs_mac.js" 时指的是
# server/configs_mac.js。而脚本自己要读同一份配置时，得按脚本目录（server/）解析——
# 同一个文件两种相对写法，所以下面把"传给 node 的写法"和"真实文件"分开记。
CONFIG="../configs_mac.js"
CONFIG_FILE=""
NODE="$(command -v node 2>/dev/null)"

# 三组数组按同一下标对应：bash 3.2 没有关联数组，用平行数组代替
PROC_NAME=(account hall game)
PROC_TITLE=(账号服 大厅服 游戏服)
PROC_ENTRY=(account_server/app.js hall_server/app.js game_server/app.js)
PROC_LABEL1=("客户端 HTTP" "客户端 HTTP" "客户端 Socket.IO")
PROC_LABEL2=("渠道/代理 API" "游戏服上报 HTTP" "内部 HTTP")

# 端口先给一份内置默认值；正常情况下会被 load_ports 从配置文件覆盖
HALL_IP="127.0.0.1"
PORT_A1=9000
PORT_A2=12581
PORT_H1=9001
PORT_H2=9002
PORT_G1=10000
PORT_G2=9003

# ---------------------------------------------------------------- 基础工具

# 进程是否存活。kill -0 只做存在性与权限检查，不真的发信号。
pid_alive() {
	[ -n "$1" ] && kill -0 "$1" 2>/dev/null
}

# 监听某个 TCP 端口的 PID；没有输出表示没有进程在监听
port_pid() {
	lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n 1
}

log_path() {
	echo "$LOG_DIR/$1.log"
}

# 日志里第一个 ": PID <数字>" 就是进程自己打印的启动横幅（utils/startup.js）记下的 PID。
# 取不到（日志还没有/被删了）就返回 0，表示"无法判断，按匹配处理"，不因此误判成没起。
pid_matches_log() {
	local banner
	banner="$(sed -n 's/.*: PID \([0-9][0-9]*\).*/\1/p' "$(log_path "$1")" 2>/dev/null | head -n 1)"
	[ -z "$banner" ] && return 0
	[ "$banner" = "$2" ]
}

# PID 文件每行：<名字> <pid> <启动时刻 epoch>。下面三个函数都围绕它工作。
# PID 还活着不等于它就是我们启动的那个进程：PID 会被复用（重启机器之后尤其可能）。
# 所以再用日志横幅里的 PID 核对一次，对不上就当作"没有记录"——宁可当作没起，
# 也不能让 stop 去 kill 一个碰巧复用了这个 PID 的无关进程。
pid_of() {
	[ -f "$PID_FILE" ] || return 0
	while read -r n p t; do
		if [ "$n" = "$1" ]; then
			if pid_alive "$p" && pid_matches_log "$1" "$p"; then
				echo "$p"
			fi
			return 0
		fi
	done < "$PID_FILE"
}

started_of() {
	[ -f "$PID_FILE" ] || return 0
	while read -r n p t; do
		if [ "$n" = "$1" ]; then
			echo "$t"
			return 0
		fi
	done < "$PID_FILE"
}

# 从 PID 文件里删掉某个名字：用临时文件重写，避免 macOS 上 sed -i 的写法差异
drop_pid() {
	[ -f "$PID_FILE" ] || return 0
	: > "$PID_FILE.tmp"
	while read -r n p t; do
		[ "$n" = "$1" ] && continue
		echo "$n $p $t" >> "$PID_FILE.tmp"
	done < "$PID_FILE"
	mv "$PID_FILE.tmp" "$PID_FILE"
}

save_pid() {
	mkdir -p "$RUN_DIR"
	drop_pid "$1"
	printf '%s %s %s\n' "$1" "$2" "$(date +%s)" >> "$PID_FILE"
}

# 把秒数说成人话。只保留两级单位，够看就行。
human_duration() {
	local secs="$1"
	[ "$secs" -lt 0 ] 2>/dev/null && secs=0
	local d=$((secs / 86400)) h=$(((secs % 86400) / 3600)) m=$(((secs % 3600) / 60)) s=$((secs % 60))
	if [ "$d" -gt 0 ]; then
		echo "${d}d${h}h"
	elif [ "$h" -gt 0 ]; then
		echo "${h}h${m}m"
	elif [ "$m" -gt 0 ]; then
		echo "${m}m${s}s"
	else
		echo "${s}s"
	fi
}

# ---------------------------------------------------------------- 配置读取

# 端口以配置文件为唯一来源：用 node require 它，按字段读出，而不是在脚本里抄一份。
# account_server().CLIENT_PORT / DEALDER_API_PORT、hall_server().CLEINT_PORT / ROOM_PORT、
# game_server().CLIENT_PORT / HTTP_PORT（注意 configs 里 CLEINT_PORT、DEALDER_API_PORT 的拼写）。
load_ports() {
	[ -n "$NODE" ] || return 1
	[ -f "$CONFIG_FILE" ] || return 1
	local out
	out="$("$NODE" -e '
		var c = require(process.argv[1]);
		var a = c.account_server(), h = c.hall_server(), g = c.game_server();
		var v = [a.CLIENT_PORT, a.DEALDER_API_PORT, h.CLEINT_PORT, h.ROOM_PORT, g.CLIENT_PORT, g.HTTP_PORT];
		for (var i = 0; i < v.length; ++i) {
			if (!v[i]) { process.exit(2); }
		}
		process.stdout.write((a.HALL_IP || "127.0.0.1") + " " + v.join(" "));
	' "$CONFIG_FILE" 2>/dev/null)" || return 1
	[ -n "$out" ] || return 1
	read -r HALL_IP PORT_A1 PORT_A2 PORT_H1 PORT_H2 PORT_G1 PORT_G2 <<< "$out"
	return 0
}

# ---------------------------------------------------------------- 启动 / 停止

# 等某个进程的两个端口都进入监听。以"端口真的在 listen"为准，不去 grep 日志，
# 因为端口才是客户端真正要连的东西；日志里的"启动成功"只是同一件事的转述。
wait_ports() {
	local i="$1" pid="$2"
	local deadline=$(($(date +%s) + WAIT_SECONDS))
	while :; do
		if [ -n "$(port_pid "${PROC_PORT1[$i]}")" ] && [ -n "$(port_pid "${PROC_PORT2[$i]}")" ]; then
			return 0
		fi
		# 进程自己先退了（EADDRINUSE、配置错误…）就没必要等满超时
		pid_alive "$pid" || return 1
		[ "$(date +%s)" -ge "$deadline" ] && return 1
		sleep 0.3
	done
}

start_one() {
	local i="$1"
	local name="${PROC_NAME[$i]}" title="${PROC_TITLE[$i]}" entry="${PROC_ENTRY[$i]}"
	local log="$(log_path "$name")"

	local running="$(pid_of "$name")"
	if [ -n "$running" ]; then
		printf '  %s 已在运行（PID %s），跳过启动\n' "$title" "$running"
		return 0
	fi

	# 端口被别的进程占着就起不来：先说清楚是谁占的，别等 node 甩一屏 EADDRINUSE
	local busy="" p lpid
	for p in "${PROC_PORT1[$i]}" "${PROC_PORT2[$i]}"; do
		lpid="$(port_pid "$p")"
		[ -n "$lpid" ] && busy="$busy $p(PID $lpid)"
	done
	if [ -n "$busy" ]; then
		printf '  %s 启动失败：端口已被占用 —%s\n' "$title" "$busy"
		printf '    处理：先 ./start_all_mac.sh stop，或用 lsof -i :端口 找到占用进程后停掉\n'
		return 1
	fi

	mkdir -p "$LOG_DIR" "$RUN_DIR"
	# 每次启动重写日志，保证 logs/<名字>.log 只对应最近一次运行，排查时不会被上一轮干扰
	: > "$log"
	nohup "$NODE" "$entry" "$CONFIG" >> "$log" 2>&1 < /dev/null &
	local pid=$!
	save_pid "$name" "$pid"
	printf '  %s 启动中（PID %s，日志 %s）' "$title" "$pid" "$log"

	if wait_ports "$i" "$pid"; then
		printf ' … 就绪\n'
		return 0
	fi

	if pid_alive "$pid"; then
		printf ' … 超时：进程还在，但端口没在 %s 秒内全部监听\n' "$WAIT_SECONDS"
	else
		printf ' … 失败：进程已退出\n'
	fi
	printf '    %s 最后几行：\n' "$log"
	tail -n 12 "$log" | sed 's/^/    /'
	return 1
}

wait_pid_gone() {
	local pid="$1"
	local deadline=$(($(date +%s) + STOP_SECONDS))
	while pid_alive "$pid"; do
		[ "$(date +%s)" -ge "$deadline" ] && return 1
		sleep 0.2
	done
	return 0
}

stop_one() {
	local i="$1"
	local name="${PROC_NAME[$i]}" title="${PROC_TITLE[$i]}"
	local pid="$(pid_of "$name")"

	if [ -z "$pid" ]; then
		# 没有记录在案的 PID：可能本来没起，也可能是崩溃后留下的孤儿
		local busy="" p lpid
		for p in "${PROC_PORT1[$i]}" "${PROC_PORT2[$i]}"; do
			lpid="$(port_pid "$p")"
			[ -n "$lpid" ] && busy="$busy $p(PID $lpid)"
		done
		if [ -n "$busy" ]; then
			# 刻意保守：只停本脚本启动的进程，不顺手杀掉别人的 node。
			# 走到这里通常是三种情况：别人手工起的（yarn hall 之类）、上个脚本留下的 nohup 进程、
			# 或者 PID 文件过期后剩下的孤儿。都要人确认，脚本不替你做这个决定。
			printf '  %s 没有记录在案的 PID，但端口仍被占用 —%s\n' "$title" "$busy"
			printf '    这可能不是本脚本启动的进程（别人手工起的 / 旧 nohup 留下的 / PID 文件过期后的孤儿），\n'
			printf '    确认后请自行处理：lsof -nP -iTCP:<端口> -sTCP:LISTEN 看是谁，再 kill 它\n'
		else
			printf '  %s 未在运行，跳过\n' "$title"
		fi
		drop_pid "$name"
		return 0
	fi

	kill "$pid" 2>/dev/null
	printf '  %s 停止中（PID %s）' "$title" "$pid"
	if wait_pid_gone "$pid"; then
		printf ' … 已停止\n'
	else
		printf ' … 超时：进程仍存活，需要时可强杀 kill -9 %s\n' "$pid"
	fi
	drop_pid "$name"
	return 0
}

# ---------------------------------------------------------------- 状态表

# 标记统一是 3 个汉字 + 方括号，显示宽度一致，所以后面的端口号能对齐。
print_port_line() {
	local owner="$1" port="$2" label="$3"
	local lpid="$(port_pid "$port")"
	local marker="[未监听]" suffix=""
	if [ -n "$lpid" ]; then
		if [ -n "$owner" ] && [ "$lpid" = "$owner" ]; then
			marker="[监听中]"
		else
			marker="[被占用]"
			suffix="  ← 被 PID $lpid 占用（不是本脚本启动的进程）"
		fi
	fi
	printf '           %s %-6s%s%s\n' "$marker" "$port" "$label" "$suffix"
}

# 打印状态表。全部进程与端口都就绪返回 0，否则返回 1（便于脚本化判断）。
print_status() {
	local bar='=============================================================='
	local thin='--------------------------------------------------------------'
	local i=0 total=${#PROC_NAME[@]}
	local procs_up=0 ports_up=0

	printf '%s\n' "$bar"
	printf ' 幼麟四川麻将 · 服务端运行状态\n'
	printf '%s\n' "$bar"
	printf ' 配置文件 : %s（%s）\n' "$CONFIG_DISPLAY" "$PORT_SOURCE"
	printf ' 检查时间 : %s\n' "$(date '+%Y-%m-%d %H:%M:%S')"
	[ -n "$NODE" ] && printf ' Node     : %s\n' "$("$NODE" --version 2>/dev/null)"
	printf '%s\n' "$thin"

	while [ "$i" -lt "$total" ]; do
		local name="${PROC_NAME[$i]}" title="${PROC_TITLE[$i]}"
		local pid="$(pid_of "$name")" line_up=0

		if [ -n "$pid" ]; then
			procs_up=$((procs_up + 1))
			local started="$(started_of "$name")" uptime="未知"
			[ -n "$started" ] && uptime="$(human_duration $(($(date +%s) - started)))"
			printf '%s   [运行中]  PID %-7s 运行 %s\n' "$title" "$pid" "$uptime"
		else
			printf '%s   [已停止]\n' "$title"
		fi

		print_port_line "$pid" "${PROC_PORT1[$i]}" "${PROC_LABEL1[$i]}"
		print_port_line "$pid" "${PROC_PORT2[$i]}" "${PROC_LABEL2[$i]}"
		printf '           日志: %s\n' "$(log_path "$name")"
		i=$((i + 1))
	done

	# 端口计数单独再扫一遍，避免把上面的循环写得更绕
	local p
	for p in "$PORT_A1" "$PORT_A2" "$PORT_H1" "$PORT_H2" "$PORT_G1" "$PORT_G2"; do
		[ -n "$(port_pid "$p")" ] && ports_up=$((ports_up + 1))
	done

	printf '%s\n' "$thin"
	printf ' 汇总: %s 个进程，%s 个运行中；%s 个端口，%s 个监听中，%s 个未监听\n' \
		"$total" "$procs_up" 6 "$ports_up" "$((6 - ports_up))"

	if [ "$procs_up" -eq "$total" ] && [ "$ports_up" -eq 6 ]; then
		printf ' 客户端入口: 账号服 http://%s:%s   大厅服 http://%s:%s   游戏服 Socket.IO %s:%s\n' \
			"$HALL_IP" "$PORT_A1" "$HALL_IP" "$PORT_H1" "$HALL_IP" "$PORT_G1"
		printf ' 运维命令  : 停止 ./start_all_mac.sh stop   重启 ./start_all_mac.sh restart   日志 ./start_all_mac.sh logs\n'
		printf '%s\n\n' "$bar"
		return 0
	fi

	printf ' 提示: 还有端点未就绪，先看日志 → ./start_all_mac.sh logs\n'
	printf '%s\n\n' "$bar"
	return 1
}

# ---------------------------------------------------------------- 参数解析

CMD=""
LOG_NAME=""
while [ "$#" -gt 0 ]; do
	case "$1" in
		--config)
			if [ -z "${2:-}" ]; then
				echo "--config 后面要跟配置文件路径" >&2
				exit 2
			fi
			CONFIG="$2"
			shift 2
			;;
		--config=*)
			CONFIG="${1#--config=}"
			shift
			;;
		-h|--help|help)
			CMD="help"
			shift
			;;
		*)
			if [ -z "$CMD" ]; then
				CMD="$1"
			elif [ -z "$LOG_NAME" ]; then
				LOG_NAME="$1"
			fi
			shift
			;;
	esac
done
[ -n "$CMD" ] || CMD="start"

# 把 --config 传来的写法落到真实文件上。两种写法都要认：
#   ../configs_mac.js   旧写法，相对的是入口文件目录（app.js 那边就是这么解析的）
#   configs_mac.js      相对脚本目录（server/），人更容易写对
resolve_config() {
	if [ -f "$CONFIG" ]; then
		CONFIG_FILE="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"
		return 0
	fi
	if [ -f "$SCRIPT_DIR/$(basename "$CONFIG")" ]; then
		CONFIG_FILE="$SCRIPT_DIR/$(basename "$CONFIG")"
		return 0
	fi
	return 1
}

if ! resolve_config; then
	echo "找不到配置文件：${CONFIG}（也试过 ${SCRIPT_DIR}/$(basename "$CONFIG")）" >&2
	exit 1
fi

# 状态表里显示相对 server/ 的路径，短一点也更好认
case "$CONFIG_FILE" in
	"$SCRIPT_DIR"/*) CONFIG_DISPLAY="${CONFIG_FILE#$SCRIPT_DIR/}" ;;
	*) CONFIG_DISPLAY="$CONFIG_FILE" ;;
esac

# 端口来源：优先配置文件，读不到就用内置默认值并明确说明，不静默用错
if load_ports; then
	PORT_SOURCE="端口取自配置文件"
else
	PORT_SOURCE="端口为内置默认值（未能从 ${CONFIG_DISPLAY} 读出，请检查 node 与配置文件）"
fi

PROC_PORT1=("$PORT_A1" "$PORT_H1" "$PORT_G1")
PROC_PORT2=("$PORT_A2" "$PORT_H2" "$PORT_G2")

# ---------------------------------------------------------------- 子命令

# 帮助就是脚本头部那段注释本身：从这里现读现用，改注释不会忘记改帮助。
# sed 那句是把开头的空行去掉，让帮助从"用法："开始，而不是先空一行。
usage() {
	awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" | sed '/./,$!d'
}

case "$CMD" in
	start|restart)
		if [ -z "$NODE" ]; then
			echo "找不到 node，请先安装 Node.js（三个进程都靠它跑）" >&2
			exit 1
		fi
		if [ ! -d node_modules/express ] || [ ! -d node_modules/mysql2 ] || [ ! -d node_modules/socket.io ]; then
			echo "依赖不完整：缺少 node_modules 里的 express / mysql2 / socket.io" >&2
			echo "先执行：cd server && yarn install --frozen-lockfile" >&2
			exit 1
		fi

		if [ "$CMD" = "restart" ]; then
			echo "重启幼麟四川麻将服务端（配置 ${CONFIG_DISPLAY}）"
			for i in 0 1 2; do
				stop_one "$i"
			done
			echo ""
		fi

		echo "启动幼麟四川麻将服务端（配置 ${CONFIG_DISPLAY}，${PORT_SOURCE}）"
		for i in 0 1 2; do
			start_one "$i"
		done
		echo ""
		print_status
		exit $?
		;;

	stop)
		echo "停止幼麟四川麻将服务端"
		for i in 0 1 2; do
			stop_one "$i"
		done
		# 停完给一张状态表，免得"以为停了其实还在"
		echo ""
		print_status
		exit 0
		;;

	status)
		print_status
		exit $?
		;;

	logs)
		if [ -n "$LOG_NAME" ]; then
			f="$(log_path "$LOG_NAME")"
			if [ ! -f "$f" ]; then
				echo "没有这个日志：${f}（名字应为 account / hall / game）" >&2
				exit 1
			fi
			echo "跟踪 ${f}（Ctrl+C 退出）"
			tail -n 50 -f "$f"
		else
			files=""
			for i in 0 1 2; do
				f="$(log_path "${PROC_NAME[$i]}")"
				[ -f "$f" ] && files="$files $f"
			done
			if [ -z "$files" ]; then
				echo "还没有日志（先 ./start_all_mac.sh）" >&2
				exit 1
			fi
			echo "跟踪${files}（Ctrl+C 退出）"
			tail -n 50 -f $files
		fi
		;;

	help|*)
		usage
		[ "$CMD" = "help" ] || exit 2
		exit 0
		;;
esac
