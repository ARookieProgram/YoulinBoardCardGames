"""配置加载：把命令行给的配置文件当作 Python 模块导入。

对应 `server/utils/config.py`。用法与 Node 版一一对应：

    python -m game_server.app ../configs_mac.py

相对路径按**调用方所在目录**解析（Node 版是 `__dirname`），因此
`game_server/app.py` 里的 `../configs_mac.py` 指向 `server-python/configs_mac.py`，
与 `dist/game_server/app.js ../configs_mac.js` 的相对语义完全一致。
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType
from typing import Any


def _load_module(path: pathlib.Path) -> ModuleType:
    """按文件路径导入一个 Python 模块（不写 `__pycache__`，模块名带前缀避免冲突）。"""
    spec = importlib.util.spec_from_file_location("_scmj_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载配置文件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_configs(config_path: str | None, base_dir: str) -> ModuleType:
    """载入命令行传入的配置文件。

    :param config_path: 命令行参数（`sys.argv[1]`），相对路径或绝对路径。
    :param base_dir: 调用方所在目录（传 `os.path.dirname(__file__)`），相对路径按它解析。
    :return: 配置模块本身，其 `mysql()` / `account_server()` / `hall_server()` /
             `game_server()` 四个函数返回各自进程的配置。
    """
    if not config_path:
        raise SystemExit(
            "缺少配置文件参数。用法：python -m <进程>.app ../configs_mac.py"
            "（见 server-python/AGENTS.md）"
        )

    resolved = (pathlib.Path(base_dir) / config_path).resolve()
    if not resolved.is_file():
        raise SystemExit(f"配置文件不存在：{resolved}")

    return _load_module(resolved)


def config_function(module: ModuleType, name: str) -> Any:
    """取配置模块里的一个配置函数，并做一次"必须存在且可调用"的自检。

    这是 Python 相对于 TypeScript 少掉的那一层编译期约束：Node 版靠
    `ServerConfigs` 接口在编译期校验导出面，Python 只能在运行期检查。
    """
    function = getattr(module, name, None)
    if function is None or not callable(function):
        raise SystemExit(f"配置文件缺少必需的配置函数：{name}()")
    return function
