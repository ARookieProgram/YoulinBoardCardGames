"""`rooms` 应用路由，挂在 `/api/rooms/` 下。

与游戏侧的房间 HTTP 接口（大厅服 `/create_private_room`、游戏服内部
`/create_room` / `/enter_room`）没有任何重叠：那些跑在 9001 / 9003 上，
这里是管理平台的 8000，而且**只有读**。
"""

from __future__ import annotations

from django.urls import path

from .views import (
    RoomDetailView,
    RoomDissolveView,
    RoomListView,
    RoomOverviewView,
)

app_name = "rooms"

urlpatterns = [
    path("", RoomListView.as_view(), name="list"),
    # 放在 `<str:room_id>/` 之前：`overview` 也会被 `<str:...>` 匹配，
    # 顺序反了就会走到详情视图里去。
    path("overview/", RoomOverviewView.as_view(), name="overview"),
    path("<str:room_id>/", RoomDetailView.as_view(), name="detail"),
    # 预留入口：契约与权限已就绪，动作待游戏服提供内部接口后接入。
    path("<str:room_id>/dissolve/", RoomDissolveView.as_view(), name="dissolve"),
]
