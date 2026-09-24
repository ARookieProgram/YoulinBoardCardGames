"""管理平台根路由。

| 前缀 | 归属 |
| --- | --- |
| `/api/auth/` | 管理平台登录（本工程） |
| `/api/health/` | 健康检查（给负载均衡/运维用，不需要登录） |
| `/admin/` | Django 自带的数据库管理站点（**不是**本平台的前端） |

前端（`admin-platform/`）走 Vite dev server，通过代理把 `/api` 转发到这里，
所以浏览器侧不涉及跨域；`settings.CORS_ALLOWED_ORIGINS` 是直连时的兜底。
"""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpRequest
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.response import ok

# Django 自带 admin 站点的标题（它管的是数据库表，与 Vue 前端是两回事）。
admin.site.site_header = "幼麟麻将 · 数据库管理"
admin.site.site_title = "幼麟麻将数据库管理"
admin.site.index_title = "数据表"


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request: HttpRequest) -> Response:
    """健康检查：进程活着且能响应 HTTP 就返回 ok。

    用 `@api_view` 而不是裸 Django 视图：这里返回的是 DRF 的 `Response`，
    它必须经过 DRF 的渲染流程才会被赋值 `accepted_renderer`，
    否则 Django 在 `response.render()` 阶段直接抛
    `AssertionError: .accepted_renderer not set on Response`。

    另外刻意**不查数据库**——数据库挂了也要能报告"Web 进程还活着"，
    否则运维分不清是进程死了还是库连不上。
    """
    return ok({"service": "platform_server", "status": "up"})


urlpatterns = [
    path("api/auth/", include("apps.accounts.urls")),
    path("api/health/", health, name="health"),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    # 开发期静态文件（本平台暂无上传功能，保留以免后续加头像时踩坑）。
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
