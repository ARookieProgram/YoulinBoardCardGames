"""`games` 应用路由，挂在 `/api/games/` 下。

与游戏侧的对局接口（大厅服 `/get_games_of_room`、`/get_detail_of_game`）没有任何重叠：
那些跑在 9001 上、给客户端回放用，这里是管理平台的 8000，而且**只有读**。

顺序说明：`overview/` 必须排在 `rooms/<str:room_ref>/` 之前吗？不必——两者第一段
就不同（`overview` vs `rooms`），不存在互相遮蔽。真正要小心的是
`rooms/<str:room_ref>/` 与 `rooms/<str:room_ref>/<int:game_index>/`：
Django 按路径段数匹配，短的不会吞掉长的，所以顺序无所谓，这里按"由浅入深"排。
"""

from __future__ import annotations

from django.urls import path

from .views import (
    GameDetailView,
    GameListView,
    GameOverviewView,
    PlayerGameListView,
    RoomGameListView,
)

app_name = "games"

urlpatterns = [
    path("", GameListView.as_view(), name="list"),
    path("overview/", GameOverviewView.as_view(), name="overview"),
    path("rooms/<str:room_ref>/", RoomGameListView.as_view(), name="room-games"),
    path(
        "rooms/<str:room_ref>/<int:game_index>/",
        GameDetailView.as_view(),
        name="game-detail",
    ),
    path("players/<int:player_id>/", PlayerGameListView.as_view(), name="player-games"),
]
