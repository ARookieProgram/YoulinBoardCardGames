"""Socket.IO 协议的类型视图与事件名清单。

对应 `server/types/protocol.ts`。这里给的是**事件名与方向**，载荷刻意保持宽松：
跨进程协议的真实结构由 `repo:docs/ai-native/protocol.md` 的表格与客户端代码约束。

事件清单以 `repo:docs/ai-native/protocol.md` §1 为准，并由仓库根的门禁
`npm run check:protocol` 校验；本模块额外把两份清单固化成常量，
供 `server-python/tests/test_protocol.py` 与 Node 侧源码逐字比对。
"""

from typing import Literal

#: 服务端 → 客户端的事件名（protocol.md §1 的 39 个）。
ServerPushEvent = Literal[
    "chat_push",
    "dispress_push",
    "dissolve_cancel_push",
    "dissolve_notice_push",
    "emoji_push",
    "exit_notify_push",
    "exit_result",
    "game_action_push",
    "game_begin_push",
    "game_chupai_notify_push",
    "game_chupai_push",
    "game_dingque_finish_push",
    "game_dingque_notify_push",
    "game_dingque_push",
    "game_holds_push",
    "game_huanpai_over_push",
    "game_huanpai_push",
    "game_mopai_push",
    "game_num_push",
    "game_over_push",
    "game_playing_push",
    "game_pong",
    "game_sync_push",
    "gang_notify_push",
    "guo_notify_push",
    "guo_result",
    "guohu_push",
    "hangang_notify_push",
    "hu_push",
    "huanpai_notify",
    "login_finished",
    "login_result",
    "mj_count_push",
    "new_user_comes_push",
    "peng_notify_push",
    "quick_chat_push",
    "user_ready_push",
    "user_state_push",
    "voice_msg_push",
]

#: 上表的运行期形态，给测试与协议比对用（顺序与 protocol.md §1 一致）。
SERVER_PUSH_EVENTS: tuple[str, ...] = (
    "chat_push",
    "dispress_push",
    "dissolve_cancel_push",
    "dissolve_notice_push",
    "emoji_push",
    "exit_notify_push",
    "exit_result",
    "game_action_push",
    "game_begin_push",
    "game_chupai_notify_push",
    "game_chupai_push",
    "game_dingque_finish_push",
    "game_dingque_notify_push",
    "game_dingque_push",
    "game_holds_push",
    "game_huanpai_over_push",
    "game_huanpai_push",
    "game_mopai_push",
    "game_num_push",
    "game_over_push",
    "game_playing_push",
    "game_pong",
    "game_sync_push",
    "gang_notify_push",
    "guo_notify_push",
    "guo_result",
    "guohu_push",
    "hangang_notify_push",
    "hu_push",
    "huanpai_notify",
    "login_finished",
    "login_result",
    "mj_count_push",
    "new_user_comes_push",
    "peng_notify_push",
    "quick_chat_push",
    "user_ready_push",
    "user_state_push",
    "voice_msg_push",
)

#: 客户端 → 服务端的事件名（protocol.md §2；`socket_service.py` 里注册的全部 `socket.on`）。
#: 最后一项 `disconnect` 是 socket.io 内置事件，不是业务事件，但同样要在两侧注册。
CLIENT_TO_SERVER_EVENTS: tuple[str, ...] = (
    "login",
    "ready",
    "huanpai",
    "dingque",
    "chupai",
    "peng",
    "gang",
    "hu",
    "guo",
    "chat",
    "quick_chat",
    "voice_msg",
    "emoji",
    "exit",
    "dispress",
    "dissolve_request",
    "dissolve_agree",
    "dissolve_reject",
    "game_ping",
    # socket.io 内置的断开事件（服务端与客户端都会注册它）。
    "disconnect",
)
