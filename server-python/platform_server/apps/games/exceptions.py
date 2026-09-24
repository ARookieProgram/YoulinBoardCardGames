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

    `t_games` 是**每开一局写一行**：房间刚建好、第一局还没结束时就一条记录都没有，
    所以"查不到"的文案要把这一点说清楚——运营看到的多半不是"输了错"，
    而是"这局还没打完 / 这个房间压根没开打"。
    """

    def __init__(self, room_ref: object, game_index: int | None = None) -> None:
        where = f"房间 {room_ref}" if game_index is None else f"房间 {room_ref} 的第 {game_index + 1} 局"
        super().__init__(
            f"{where} 没有对局记录（游戏服每结束一局才写库；"
            "房间里还没打完 / 从未开局时查不到）",
            code=error_codes.ERR_GAME_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )
