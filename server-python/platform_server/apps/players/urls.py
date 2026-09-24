"""`players` 应用路由，挂在 `/api/players/` 下。

与玩家侧的 HTTP 路由（账号服 `/guest`、大厅服 `/login` 等）没有任何前缀重叠——
那些是游戏客户端连的端口，这里是管理平台的 8000。
"""

from __future__ import annotations

from django.urls import path

from .views import (
    PlayerBanView,
    PlayerDetailView,
    PlayerListView,
    PlayerOverviewView,
    PlayerRechargesView,
    PlayerUnbanView,
)

app_name = "players"

urlpatterns = [
    path("", PlayerListView.as_view(), name="list"),
    # 放在 `<int:player_id>/` 之前：路径转换器不会匹配 `overview`，
    # 但显式排在前面读起来更清楚。
    path("overview/", PlayerOverviewView.as_view(), name="overview"),
    path("<int:player_id>/", PlayerDetailView.as_view(), name="detail"),
    path("<int:player_id>/ban/", PlayerBanView.as_view(), name="ban"),
    path("<int:player_id>/unban/", PlayerUnbanView.as_view(), name="unban"),
    # 预留入口：契约已定，数据源待接入（见 views.py 的 PlayerRechargesView）。
    # 对局记录已经落地到独立应用 `/api/games/players/<id>/`，不再在这里占位。
    path("<int:player_id>/recharges/", PlayerRechargesView.as_view(), name="recharges"),
]
