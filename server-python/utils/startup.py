"""三个进程共用的启动横幅。

对应 `server/utils/startup.ts`。背景（原实现注释）：

原先每个 `start()` 都在自己的 `app.listen()` 之后立刻打印一行 "xxx is listening on ..."。
这有两个问题：

1. `listen()` 是异步的。端口被占用（EADDRINUSE）时那行提示照样打印，看上去"启动成功"，
   进程随后却带着一整屏堆栈崩掉，误导性很强；
2. 一个进程其实监听多个端口（账号服 2 个、大厅服 2 个、游戏服 2 个），提示分散成多行，
   读不出"一个进程整体是否就绪"。

现在改为：各 service 的 `start()` 是**协程**，只有端口真正绑定成功才返回
（aiohttp 的 `TCPSite.start()` 在 EADDRINUSE 时直接抛 `OSError`），
由各 `app.py` 汇总后交给本模块打印一次横幅；任一端口失败就打印原因并以非 0 退出。

输出不用 ANSI 颜色：`start_all_mac.sh` 走重定向，颜色码只会污染日志。

横幅里 `进程     : PID <pid>` 这一行的格式**不能改**：
启动脚本的 `pid_matches_log()` 靠 `": PID <数字>"` 核对进程身份。
"""

from __future__ import annotations

import asyncio
import errno
import os
import platform
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import web

# 横幅最小宽度（以终端显示列计）
MIN_WIDTH = 60

# 端点名称的列宽
LABEL_WIDTH = 20

# 数据库自检的最长等待时间：MySQL 不可达时不能让横幅一直不出现
DB_PING_TIMEOUT = 2.0


@dataclass
class Endpoint:
    """本次进程汇总的一个监听端点。"""

    #: 端点名称，横幅里左对齐成一列。
    label: str
    #: URL 协议，例如 "http"。
    scheme: str
    #: 监听地址（通配地址会在展示时换成回环地址）。
    host: str
    #: 配置里的端口。
    port: int
    #: 实际绑定的端口（配置写 0 时以它为准）。
    actual_port: int
    #: 可选的补充说明，追加在 URL 之后。
    note: str | None = None


@dataclass
class _DbStatus:
    ok: bool
    detail: str = ""


def _repeat(ch: str, count: int) -> str:
    return ch * max(count, 0)


def _display_width(text: str) -> int:
    """中文（CJK）在终端里占两列。不按显示宽度算，右侧竖条就会参差不齐。"""
    width = 0
    for char in text:
        # 0x2E80 起是 CJK 部首、汉字与全角标点
        width += 2 if ord(char) > 0x2E80 else 1
    return width


def _pad_end(text: str, width: int) -> str:
    diff = width - _display_width(text)
    return text + _repeat(" ", diff) if diff > 0 else text


def _display_host(host: str) -> str:
    """通配地址（0.0.0.0 / ::）不能直接当 URL 用，换成能点开的回环地址。"""
    if host == "" or host == "0.0.0.0" or host == "::":
        return "127.0.0.1"
    return host


def endpoint_url(endpoint: Endpoint) -> str:
    return f"{endpoint.scheme}://{_display_host(endpoint.host)}:{endpoint.actual_port}"


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _box(title: str, rows: list[str | None], width: int) -> str:
    bar = _repeat("=", width)
    thin = " " + _repeat("-", width - 2) + " "
    out = ["", bar, " " + title, bar]
    for row in rows:
        if row is None:
            out.append(thin)
            continue
        out.append(" " + _pad_end(row, width - 2) + " ")
    out.append(bar)
    out.append("")
    return "\n".join(out)


def _print_banner(
    title: str,
    config_file: str | None,
    note: str,
    endpoints: list[Endpoint],
    db_status: _DbStatus,
    db_label: str | None,
) -> None:
    rows: list[str | None] = []
    rows.append("状态     : 启动成功")
    rows.append("进程     : PID " + str(os.getpid()))
    rows.append(
        "运行环境 : " + platform.system() + " " + platform.machine() + ", Python " + platform.python_version()
    )
    rows.append("配置文件 : " + (config_file if config_file is not None else "(未指定)"))
    rows.append("启动时间 : " + _timestamp())
    rows.append(None)

    title_line = "幼麟四川麻将 · " + title
    width = _display_width(title_line) + 2

    for endpoint in endpoints:
        row = _pad_end(endpoint.label, LABEL_WIDTH) + " " + endpoint_url(endpoint)
        if endpoint.note:
            row += "   " + endpoint.note
        rows.append(row)

    if db_label is not None:
        rows.append(None)
        rows.append(
            "数据库   : 连接正常 (" + db_label + ")"
            if db_status.ok
            else "数据库   : 不可用 — " + db_status.detail + "（服务继续启动，相关接口会失败）"
        )

    rows.append(None)
    rows.append(note)

    for line in rows:
        if line is not None and _display_width(line) + 2 > width:
            width = _display_width(line) + 2
    if width < MIN_WIDTH:
        width = MIN_WIDTH

    print(_box(title_line, rows, width))


def _print_failure(title: str, endpoint: Endpoint, error: BaseException, config_file: str | None) -> None:
    lines: list[str] = []
    lines.append("")
    lines.append("启动失败：" + title)
    lines.append("  端点     : " + endpoint.label)
    lines.append("  地址     : " + endpoint_url(endpoint))
    code = getattr(error, "errno", None)
    lines.append("  错误     : " + (str(code) + " " if code else "") + str(error))
    if code == errno.EADDRINUSE or "address already in use" in str(error).lower():
        lines.append("  处理建议 : 端口已被占用。先执行 lsof -i :" + str(endpoint.actual_port) + " 找到并停掉占用进程，")
        lines.append("             或修改配置文件 " + str(config_file) + " 里的端口。")
    lines.append("  配置文件 : " + str(config_file))
    lines.append("")
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(1)


async def listen(app: web.Application, host: str, port: int) -> tuple[web.AppRunner, int]:
    """绑定并开始监听一个端口；成功返回 `(runner, 实际端口)`。

    失败时直接抛异常（`EADDRINUSE` 由调用方交给 `print_failure`），
    因此**调用方拿到返回值就代表端口真的在监听了**。
    """
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    actual = port
    if site._server is not None and site._server.sockets:
        actual = site._server.sockets[0].getsockname()[1]
    return runner, actual


async def report(
    title: str,
    config_file: str | None,
    note: str,
    endpoints: list[Endpoint],
    db_module: Any = None,
    db_label: str | None = None,
) -> None:
    """所有端点就绪后打印启动横幅。

    :param title: 进程名，例如 "账号服 (account_server)"。
    :param config_file: 启动时传入的配置文件（`sys.argv[1]`）。
    :param note: 横幅底部的提示语。
    :param endpoints: 本次进程汇总的所有监听端点。
    :param db_module: `utils.db` 模块；传入则在横幅里附带一次数据库连通性自检。
    :param db_label: 自检目标描述，例如 "db_scmj@127.0.0.1:3306"。
    """
    for endpoint in endpoints:
        try:
            socket.create_connection((_display_host(endpoint.host), endpoint.actual_port), timeout=0.2).close()
        except OSError:
            # 连不上不代表没在监听（例如只绑了 IPv6）；这里只做一次轻量确认，
            # 真正的"是否 listening"由 listen() 的返回值保证。
            pass

    if db_module is None:
        _print_banner(title, config_file, note, endpoints, _DbStatus(ok=True), None)
        return

    try:
        ok, detail = await asyncio.wait_for(db_module.ping(), timeout=DB_PING_TIMEOUT)
    except asyncio.TimeoutError:
        _print_banner(
            title,
            config_file,
            note,
            endpoints,
            _DbStatus(ok=False, detail=f"连接自检超时 {int(DB_PING_TIMEOUT * 1000)}ms"),
            db_label,
        )
        return

    _print_banner(
        title,
        config_file,
        note,
        endpoints,
        _DbStatus(ok=ok, detail=detail or "未知错误"),
        db_label,
    )


def fail(title: str, endpoint: Endpoint, error: BaseException, config_file: str | None) -> None:
    """打印启动失败信息并以退出码 1 结束（由 `app.py` 在 `listen` 抛异常时调用）。"""
    _print_failure(title, endpoint, error, config_file)


async def listen_or_fail(
    app: web.Application,
    host: str | None,
    port: int,
    endpoint: Endpoint,
    config_file: str | None,
    title: str,
) -> web.AppRunner:
    """绑定一个端点；失败时打印横幅并退出（退出码 1）。"""
    try:
        runner, actual_port = await listen(app, str(host) if host else None, port)
    except OSError as error:
        _print_failure(title, endpoint, error, config_file)
        raise  # `_print_failure` 已经抛 SystemExit，这行只为类型收窄
    endpoint.actual_port = actual_port
    return runner


async def wait_for_shutdown(runners: list[web.AppRunner]) -> None:
    """等到收到 SIGINT / SIGTERM，然后关掉所有的监听端点。

    Node 版靠 `process.exit`；这里把 aiohttp 的 runner 逐个 cleanup。
    连接池、共享 HTTP 会话等收尾动作统一由 `run(cleanup=[...])` 负责——
    这样"端口被占用而提前退出"时也一样会走到，不会留下半开的 MySQL 连接。
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            # 某些平台（Windows 的 ProactorEventLoop）不支持，退回 KeyboardInterrupt
            pass

    await stop.wait()
    print("\n正在停止服务 ...", flush=True)

    for runner in runners:
        await runner.cleanup()


def run(main_coroutine: Any, cleanup: list[Any] | None = None) -> None:
    """`asyncio.run` 的一层薄封装：Ctrl+C 不算异常退出，且**总是**执行收尾。

    :param main_coroutine: 进程主协程。
    :param cleanup: 收尾用的无参协程函数（关连接池、关共享会话…）。
        放在 `finally` 里执行，因此启动失败（例如端口被占用）时也会跑到。
    """

    async def wrapper() -> None:
        try:
            await main_coroutine
        finally:
            for func in cleanup or []:
                try:
                    await func()
                except Exception as error:  # noqa: BLE001 —— 收尾失败不能再掩盖退出原因
                    print(f"收尾失败：{type(error).__name__}: {error}")

    try:
        asyncio.run(wrapper())
    except KeyboardInterrupt:
        pass
