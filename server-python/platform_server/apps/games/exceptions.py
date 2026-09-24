"""对局记录相关的业务异常。

业务码都挂在**异常类型**上（与 `apps/rooms/exceptions.py` 同一理由）：
DRF 的 `ValidationError` 走到统一异常处理器时只剩 `detail`，自定义业务码会被
压成通用的 `ERR_BAD_REQUEST`。数字定义在 `apps/common/error_codes.py`。
"""

from __future__ import annotations

from rest_framework import status

from apps.common import error_codes
from apps.common.exceptions import PlatformError


class GameNotFound(PlatformError):
    """查不到对局记录（`14001`）。

    对局记录**只读归档表** `t_games_archive`：游戏服在房间结束（打完 / 被解散）时
    才把整批在局行搬过去，所以"查不到"的常见原因是"房间还在打、对局还没归档"，
    其次才是"这个房间从没开打过"。文案要把这一点说清楚，运营看到的
    多半不是"输错了"。
    """

    def __init__(self, room_ref: object, game_index: int | None = None) -> None:
        where = f"房间 {room_ref}" if game_index is None else f"房间 {room_ref} 的第 {game_index + 1} 局"
        super().__init__(
            f"{where} 没有对局记录（对局记录只读归档表：房间打完 / 被解散后，"
            "游戏服才会把对局归档；房间里还在打或从未开局时查不到）",
            code=error_codes.ERR_GAME_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )
