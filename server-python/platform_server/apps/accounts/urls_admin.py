"""管理员账号管理路由，挂在 `/api/admins/` 下。

与 `/api/auth/`（**登录**这件事）刻意分开：

* `/api/auth/` 回答"我能不能进来"——登录、刷新、退出、当前身份；
* `/api/admins/` 回答"进来之后谁能管账号"——除 `me/password/` 外全部只对
  超级管理员开放。

两者都只认 `accounts_adminuser` 这一张表，与玩家表无关。
"""

from __future__ import annotations

from django.urls import path

from .views_admin import (
    AdminDetailView,
    AdminListView,
    AdminOverviewView,
    AdminPasswordView,
    AdminStatusView,
    MyPasswordView,
)

app_name = "admins"

urlpatterns = [
    path("", AdminListView.as_view(), name="list"),
    # 放在 `<int:admin_id>/` 之前：路径转换器不会匹配 `overview`，
    # 但显式排在前面读起来更清楚（与 `apps/players/urls.py` 同一写法）。
    path("overview/", AdminOverviewView.as_view(), name="overview"),
    # 改自己的口令：任意登录管理员都能用，所以必须排在 `<int:admin_id>/` 前面
    # ——`me` 不是整数，其实不会撞上，但语义上它属于"不针对某个 id"的端点。
    path("me/password/", MyPasswordView.as_view(), name="my-password"),
    path("<int:admin_id>/", AdminDetailView.as_view(), name="detail"),
    path("<int:admin_id>/status/", AdminStatusView.as_view(), name="status"),
    path("<int:admin_id>/password/", AdminPasswordView.as_view(), name="password"),
]
