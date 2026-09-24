"""跨实现的协议一致性测试。

三件事都在这里钉住：

1. **推送事件名**：Python 服务端真正发出去的事件集合，必须与
   (a) `docs/ai-native/protocol.md` §1 的表格、
   (b) Node 服务端源码里的事件名集合
   完全一致。任何一侧改了名字而没同步，这里就红。
2. **登录/内部接口签名**：`md5(...)` 的拼接顺序与密钥。这里用的是**由 Node 实现算出来的
   参考向量**（常量），所以不是"自己跟自己比"——拼接顺序或密钥改一位就会失败。
3. **客户端事件表**：`shared/protocol.py` 里声明的客户端事件，与 `socket_service.py`
   里实际注册的 `socket.on` 一一对应。

本测试只读文本、不连网、不碰数据库。
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from shared.protocol import CLIENT_TO_SERVER_EVENTS, SERVER_PUSH_EVENTS  # noqa: E402
from utils import crypto  # noqa: E402

PY_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = PY_ROOT.parent
NODE_SERVER = REPO_ROOT / "server"
PROTOCOL_MD = REPO_ROOT / "docs" / "ai-native" / "protocol.md"
CLIENT_NETMGR = REPO_ROOT / "client" / "assets" / "scripts" / "GameNetMgr.ts"

#: 由 Node 实现算出来的参考签名向量（密钥与拼接顺序都来自 configs_mac.ts）。
ROOM_PRI_KEY = "~!@#$(*&^%$&"
ACCOUNT_PRI_KEY = "^&*#$%()@"

REFERENCE = {
    "login": "3de44be812437e7024d4202431c1a881",
    "create_room": "9b6b63a7ed18ca1a782ee4d415e3420e",
    "enter_room": "11c8fbadbd6c8f2acf505ee22e789f12",
    "is_room_runing": "59e824f1ad9c154848820c9bbad108c9",
    "get_server_info": "1d94edad3ac1dbd0b710c96def5ab160",
    "guest": "f802ce9e99b551b8a1c4f01fdac33119",
    # 游戏服 -> 管理平台 platform_server 的内部封禁校验接口
    # （/api/internal/players/ban-check/，三处实现共用同一条公式）。
    "ban_check_account": "72977b2a422916d846f1f8b9bb10528d",
    "ban_check_player_id": "e16efd54aaddb8fb2aada5912ca306cd",
    "ban_check_both": "d4cb51c910c644dc4b29a94a62dded4b",
}

#: 封禁校验的共享密钥（`configs_mac.py` 的 `BAN_CHECK_PRI_KEY`，也是开发默认值）。
BAN_CHECK_PRI_KEY = "scmj-ban-check-dev-key"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_pushed_events() -> set[str]:
    """用 AST 扫描 Python 源码，收集真正被推送出去的事件名。

    这里**不用正则**：正则会把注释与 docstring 里的占位示例（例如文档里写的
    `send_msg(uid, "event", ...)`）也当成真事件。走 AST 只看真正的调用点：
    `send_msg(uid, "ev", ...)` 的第 2 个实参、`broacast_in_room("ev", ...)` 与
    `xxx.emit("ev", ...)` 的第 1 个实参，且必须是字符串字面量。
    """
    names: set[str] = set()
    for path in sorted((PY_ROOT / "game_server").glob("*.py")):
        tree = ast.parse(_read(path), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                method = func.attr
            elif isinstance(func, ast.Name):
                method = func.id
            else:
                continue

            if method == "send_msg":
                index = 1
            elif method in ("broacast_in_room", "emit"):
                index = 0
            else:
                continue

            if len(node.args) <= index:
                continue
            literal = node.args[index]
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                names.add(literal.value)
    return names


def _node_pushed_events() -> set[str]:
    """扫描 Node 源码，收集真正被推送出去的事件名。"""
    names: set[str] = set()
    for path in sorted((NODE_SERVER / "game_server").glob("*.ts")):
        source = _read(path)
        names |= set(re.findall(r"sendMsg\(\s*[^,()]+,\s*'([a-z_]+)'", source))
        names |= set(re.findall(r"sendMsg\(\s*[^,()]+,\s*\"([a-z_]+)\"", source))
        names |= set(re.findall(r"broacastInRoom\(\s*'([a-z_]+)'", source))
        names |= set(re.findall(r"broacastInRoom\(\s*\"([a-z_]+)\"", source))
        names |= set(re.findall(r"\.emit\(\s*'([a-z_]+)'", source))
        names |= set(re.findall(r"\.emit\(\s*\"([a-z_]+)\"", source))
    return names


def _documented_events() -> set[str]:
    """从 protocol.md §1 的表格里取事件名。"""
    source = _read(PROTOCOL_MD)
    section = source.split("## 1. 服务端推送事件")[1].split("## 2.")[0]
    return set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", section, re.MULTILINE))


def _client_handlers() -> set[str]:
    """客户端 `cc.vv.net.addHandler("event", ...)` 注册的事件名。"""
    return set(re.findall(r'addHandler\(\s*"([a-z_]+)"', _read(CLIENT_NETMGR)))


class PushEventVocabularyTest(unittest.TestCase):
    def test_declared_list_is_unique(self) -> None:
        self.assertEqual(len(SERVER_PUSH_EVENTS), len(set(SERVER_PUSH_EVENTS)))

    def test_declared_list_matches_protocol_doc(self) -> None:
        documented = _documented_events()
        self.assertEqual(set(SERVER_PUSH_EVENTS), documented)

    def test_declared_list_matches_node_server(self) -> None:
        self.assertEqual(set(SERVER_PUSH_EVENTS), _node_pushed_events())

    def test_declared_list_matches_python_server(self) -> None:
        self.assertEqual(set(SERVER_PUSH_EVENTS), _python_pushed_events())

    def test_every_push_has_a_client_handler(self) -> None:
        # 客户端里 `game_pong` 由 Net.ts 直接 sio.on 处理，不在 GameNetMgr 里。
        missing = set(SERVER_PUSH_EVENTS) - _client_handlers() - {"game_pong"}
        self.assertEqual(missing, set())


class ClientEventVocabularyTest(unittest.TestCase):
    def test_declared_client_events_match_registrations(self) -> None:
        source = _read(PY_ROOT / "game_server" / "socket_service.py")
        registered = set(re.findall(r'socket\.on\(\s*"([a-z_]+)"', source))
        self.assertEqual(registered, set(CLIENT_TO_SERVER_EVENTS))

    def test_node_registers_the_same_set(self) -> None:
        source = _read(NODE_SERVER / "game_server" / "socket_service.ts")
        registered = set(re.findall(r"socket\.on\(\s*'([a-z_]+)'", source))
        self.assertEqual(registered, set(CLIENT_TO_SERVER_EVENTS))


class SignatureTest(unittest.TestCase):
    """签名拼接顺序与密钥（参考向量来自 Node 实现）。"""

    def test_room_login_signature(self) -> None:
        # 游戏服 socket_service 的校验 + 大厅服 client_service 的签发，两侧同源
        sign = crypto.md5("123456" + "tok" + str(1700000000000) + ROOM_PRI_KEY)
        self.assertEqual(sign, REFERENCE["login"])

    def test_create_room_signature(self) -> None:
        # 大厅服 room_service -> 游戏服 http_service：userId + conf + gems + KEY
        sign = crypto.md5("9" + '{"type":"xlch"}' + "21" + ROOM_PRI_KEY)
        self.assertEqual(sign, REFERENCE["create_room"])

    def test_enter_room_signature(self) -> None:
        # userId + name + roomId + KEY（name 允许是 null -> "null"）
        sign = crypto.md5("9" + "张三" + "123456" + ROOM_PRI_KEY)
        self.assertEqual(sign, REFERENCE["enter_room"])

    def test_is_room_runing_signature(self) -> None:
        self.assertEqual(crypto.md5("123456" + ROOM_PRI_KEY), REFERENCE["is_room_runing"])

    def test_get_server_info_signature(self) -> None:
        # 注意用的是 SERVER_ID 而不是 clientip:clientport
        self.assertEqual(crypto.md5("001" + ROOM_PRI_KEY), REFERENCE["get_server_info"])

    def test_guest_signature(self) -> None:
        # 账号服 /guest：account + req.ip + ACCOUNT_PRI_KEY，req.ip 是 IPv4-mapped 形态
        sign = crypto.md5("guest_123456" + "::ffff:127.0.0.1" + ACCOUNT_PRI_KEY)
        self.assertEqual(sign, REFERENCE["guest"])

    def test_ban_check_signature_by_account(self) -> None:
        # 游戏服 -> 管理平台：account / player_id 都参与拼接（缺席的按空串），
        # 且带字段标签，避免两个参数互相错位撞出同一个签名。
        sign = crypto.md5("account" + "guest_123456" + "player_id" + BAN_CHECK_PRI_KEY)
        self.assertEqual(sign, REFERENCE["ban_check_account"])

    def test_ban_check_signature_by_player_id(self) -> None:
        sign = crypto.md5("account" + "player_id" + "9" + BAN_CHECK_PRI_KEY)
        self.assertEqual(sign, REFERENCE["ban_check_player_id"])

    def test_ban_check_signature_with_both(self) -> None:
        sign = crypto.md5("account" + "guest_123456" + "player_id" + "9" + BAN_CHECK_PRI_KEY)
        self.assertEqual(sign, REFERENCE["ban_check_both"])

    def test_ban_check_module_matches_reference(self) -> None:
        """实现里的拼接必须与上面三条向量一致（而不是只有测试自己算得对）。"""
        from utils import bancheck  # noqa: PLC0415 —— 只在这个用例里用得到

        self.assertEqual(
            bancheck.build_sign(account="guest_123456", player_id=None, key=BAN_CHECK_PRI_KEY),
            REFERENCE["ban_check_account"],
        )
        self.assertEqual(
            bancheck.build_sign(account="", player_id=9, key=BAN_CHECK_PRI_KEY),
            REFERENCE["ban_check_player_id"],
        )


class ConfigContractTest(unittest.TestCase):
    """Python 没有 TypeScript 那样的编译期配置校验，这里补一条运行期自检。"""

    def test_mac_config_exposes_all_sections(self) -> None:
        from utils.config import load_configs

        configs = load_configs("configs_mac.py", str(PY_ROOT))
        for name in ("mysql", "account_server", "hall_server", "game_server", "ban_check"):
            function = getattr(configs, name, None)
            self.assertTrue(callable(function), f"configs_mac.py 缺少 {name}()")

    def test_win_config_matches_mac_keys(self) -> None:
        from utils.config import load_configs

        mac = load_configs("configs_mac.py", str(PY_ROOT))
        win = load_configs("configs_win.py", str(PY_ROOT))
        for name in ("mysql", "account_server", "hall_server", "game_server", "ban_check"):
            self.assertEqual(
                set(getattr(mac, name)()),
                set(getattr(win, name)()),
                f"{name}() 的字段集在两份配置里不一致",
            )

    def test_ports_are_the_documented_ones(self) -> None:
        from utils.config import load_configs

        configs = load_configs("configs_mac.py", str(PY_ROOT))
        account = configs.account_server()
        hall = configs.hall_server()
        game = configs.game_server()
        self.assertEqual(account["CLIENT_PORT"], 9000)
        self.assertEqual(account["DEALDER_API_PORT"], 12581)
        self.assertEqual(hall["CLEINT_PORT"], 9001)
        self.assertEqual(hall["ROOM_PORT"], 9002)
        self.assertEqual(game["HTTP_PORT"], 9003)
        self.assertEqual(game["CLIENT_PORT"], 10000)
        # 大厅服与游戏服必须共用同一个 ROOM_PRI_KEY，否则进房签名对不上
        self.assertEqual(hall["ROOM_PRI_KEY"], game["ROOM_PRI_KEY"])
        self.assertEqual(account["ACCOUNT_PRI_KEY"], hall["ACCOUNT_PRI_KEY"])


class GameManagerContractTest(unittest.TestCase):
    """两份 gamemgr 必须导出一组同名函数（`roommgr` 按 `conf.type` 二选一）。"""

    REQUIRED = (
        "set_ready",
        "begin",
        "huan_san_zhang",
        "ding_que",
        "chu_pai",
        "peng",
        "is_playing",
        "gang",
        "hu",
        "guo",
        "has_began",
        "do_dissolve",
        "dissolve_request",
        "dissolve_agree",
    )

    def test_both_modules_expose_the_same_api(self) -> None:
        import importlib

        for module_name in ("game_server.gamemgr_xlch", "game_server.gamemgr_xzdd"):
            module = importlib.import_module(module_name)
            missing = [name for name in self.REQUIRED if not callable(getattr(module, name, None))]
            self.assertEqual(missing, [], f"{module_name} 缺少 {missing}")

    def test_rule_constants_match(self) -> None:
        import importlib

        for module_name in ("game_server.gamemgr_xlch", "game_server.gamemgr_xzdd"):
            module = importlib.import_module(module_name)
            self.assertEqual(module.ACTION_CHUPAI, 1, module_name)
            self.assertEqual(module.ACTION_MOPAI, 2, module_name)
            self.assertEqual(module.ACTION_PENG, 3, module_name)
            self.assertEqual(module.ACTION_GANG, 4, module_name)
            self.assertEqual(module.ACTION_HU, 5, module_name)
            self.assertEqual(module.ACTION_ZIMO, 6, module_name)


if __name__ == "__main__":
    unittest.main()
