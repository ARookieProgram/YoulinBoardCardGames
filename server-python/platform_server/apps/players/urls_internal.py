"""内部接口路由，挂在 `/api/internal/players/` 下。

与 `/api/players/`（管理平台自己的前端用的 JWT 接口）分开一个前缀，是因为两者
**信任边界不同**：`/api/` 认 JWT、给后台浏览器用；`/api/internal/` 认共享密钥、
给游戏服进程用。分开之后反向代理可以只把 `/api/internal/` 限制在内网，
而不用去猜哪个具体路径是内部的。
"""

from __future__ import annotations

from django.urls import path

from .internal import BanCheckView

app_name = "players-internal"

urlpatterns = [
    path("ban-check/", BanCheckView.as_view(), name="ban-check"),
]
