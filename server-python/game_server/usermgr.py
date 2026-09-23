"""`userId -> socket` 映射与推送助手。

对应 `server/game_server/usermgr.ts`。对局内的推送**统一**走这里：

* `send_msg(user_id, event, data)`：发给单个玩家，不在线则静默丢弃；
* `broacast_in_room(event, data, sender, including_sender)`：广播给同房间座位
  （原函数名就是拼错的 `broacast`，Python 侧同样保留这个拼写，
  免得对着 Node 版读代码时找不到对应关系）；
* `kick_all_in_room(room_id)`：踢出房间内所有连接，不推送事件。

登录/连接阶段（此时还没有房间可广播）的那几处 `socket.emit` 是唯一例外，见 `socket_service.py`。

与 Node 版的差异：`send_msg` / `broacast_in_room` / `kick_all_in_room` 都是**协程**
（底层 aiohttp 的写操作要 await），调用方需要 `await`。
"""

from __future__ import annotations

from typing import Any

from game_server import robotmgr, roommgr
from game_server.sio_server import NO_DATA, Socket

#: userId -> 连接。断开后 delete，因此值可能不存在。
_user_list: dict[int, Socket] = {}
_user_online = 0


def bind(user_id: int, socket: Socket) -> None:
    """登记一个玩家的连接（登录成功时调用）。"""
    global _user_online
    _user_list[user_id] = socket
    _user_online += 1


def delete(user_id: int, socket: Socket | None = None) -> None:
    """移除一个玩家的连接（断开或踢出时调用）。

    `socket` 在原实现签名里有但从不使用，保留以维持调用点一致。
    计数与原实现一样**不做存在性判断**（重复删会减成负数），保持行为不变。
    """
    global _user_online
    _user_list.pop(user_id, None)
    _user_online -= 1


def get(user_id: int) -> Socket | None:
    """取某个玩家的连接；不在线则返回 None。"""
    return _user_list.get(user_id)


def is_online(user_id: int) -> bool:
    """玩家是否在线。

    单人模式里的机器人没有 socket，但在"牌局能不能开"这件事上必须算在线
    （`gamemgr.set_ready` 的四人齐判断查的就是这里），所以对它们恒返回 True。
    它们的推送仍然查不到连接、被 `send_msg` / `broacast_in_room` 静默丢弃。
    """
    if robotmgr.is_robot(user_id):
        return True
    return _user_list.get(user_id) is not None


def get_online_count() -> int:
    """当前在线连接数。"""
    return _user_online


async def send_msg(user_id: int, event: str, msgdata: Any = NO_DATA) -> None:
    """给单个玩家推送；不在线则静默丢弃。

    :param user_id: 目标玩家。
    :param event: 事件名（与客户端 addHandler 逐字一致）。
    :param msgdata: 载荷；**不传**与显式传 `None` 在线上是不同的包
        （`[event]` vs `[event,null]`），原实现两种写法都有，这里保持一致。
    """
    user_info = _user_list.get(user_id)
    if user_info is None:
        return
    await user_info.emit(event, msgdata)


async def kick_all_in_room(room_id: str | None) -> None:
    """踢出房间内所有连接（解散房间时用）。不推送任何事件。"""
    if room_id is None:
        return
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return

    for seat in room_info.seats:
        if seat.userId > 0:
            socket = _user_list.get(seat.userId)
            if socket is not None:
                delete(seat.userId)
                await socket.disconnect()


async def broacast_in_room(
    event: str,
    data: Any,
    sender: int,
    including_sender: bool = False,
) -> None:
    """把事件广播给同房间的所有座位。

    :param event: 事件名（与客户端 addHandler 逐字一致）。
    :param data: 载荷。
    :param sender: 发送者 userId。
    :param including_sender: 为 True 时也发给发送者自己。
    """
    room_id = roommgr.get_user_room(sender)
    if room_id is None:
        return
    room_info = roommgr.get_room(room_id)
    if room_info is None:
        return

    for seat in room_info.seats:
        # 如果不需要发给发送方，则跳过
        if seat.userId == sender and including_sender is not True:
            continue
        socket = _user_list.get(seat.userId)
        if socket is not None:
            await socket.emit(event, data)


def reset() -> None:
    """清空在线表（只给测试用；Node 版没有这个函数，它靠进程重启）。"""
    global _user_online
    _user_list.clear()
    _user_online = 0
