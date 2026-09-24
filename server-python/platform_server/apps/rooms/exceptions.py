"""房间管理相关的业务异常。

业务码都挂在**异常类型**上（与 `apps/players/exceptions.py` 同一理由）：
DRF 的 `ValidationError` 走到统一异常处理器时只剩 `detail`，自定义业务码会被
压成通用的 `ERR_BAD_REQUEST`。

数字定义在 `apps/common/error_codes.py`，这里不重复定义。
"""

from __future__ import annotations

from rest_framework import status

from apps.common import error_codes
from apps.common.exceptions import PlatformError


class RoomNotFound(PlatformError):
    """玩家库的 `t_rooms` 里没有这个房间。

    房间是瞬时的（打完 / 被解散就删行），所以文案里要提醒这一点，
    免得运营以为自己输错了房间号。
    """

    def __init__(self, room_ref: object) -> None:
        super().__init__(
            f"房间 {room_ref} 不存在或已结束（房间在解散 / 打完后就会从库里删除）",
            code=error_codes.ERR_ROOM_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )
