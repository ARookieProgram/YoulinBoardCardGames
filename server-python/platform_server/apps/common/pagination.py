"""统一分页。

列表接口的 `data` 形状固定为：

    {"items": [...], "total": 123, "page": 1, "page_size": 20, "pages": 7}

前端表格只需要认这几个键，不用管用的是 PageNumber 还是 LimitOffset。
`page_size` 由查询参数控制，并夹在 `PAGE_SIZE_MAX` 以内，防止一次拉全表。
"""

from __future__ import annotations

from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

#: 单页最大条数。
PAGE_SIZE_MAX = 200


class StandardPagination(PageNumberPagination):
    """按页码分页，返回 `items` / `total` 等固定键。"""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = PAGE_SIZE_MAX
    page_query_param = "page"

    def get_paginated_response(self, data: Any) -> Response:
        """包装分页结果。"""
        from .response import ok

        return ok(
            {
                "items": data,
                "total": self.page.paginator.count,
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "pages": self.page.paginator.num_pages,
            }
        )

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """给未来的 OpenAPI 文档用的形状描述。"""
        return {
            "type": "object",
            "properties": {
                "code": {"type": "integer"},
                "message": {"type": "string"},
                "data": {
                    "type": "object",
                    "properties": {
                        "items": schema,
                        "total": {"type": "integer"},
                        "page": {"type": "integer"},
                        "page_size": {"type": "integer"},
                        "pages": {"type": "integer"},
                    },
                },
            },
        }
