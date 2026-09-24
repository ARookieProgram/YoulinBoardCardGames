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


def page_payload(*, items: Any, total: int, page: int, page_size: int) -> dict[str, Any]:
    """构造列表接口的分页 `data` 形状。

    不是每个列表都能交给 DRF 的 `PageNumberPagination`：玩家列表的数据来自
    玩家库的**只读 SQL**（有自己的 LIMIT/OFFSET），DRF 的 paginator 拿到的是
    "已经切好的一页"，再包一层会把 total 算成当页条数。所以把形状抽成一个函数，
    两条路径共用同一份键集，前端不必区分接口是怎么分页的。

    :param items: 当前页数据。
    :param total: 过滤后的总条数。
    :param page: 当前页码（从 1 开始）。
    :param page_size: 每页条数。
    :return: `{"items", "total", "page", "page_size", "pages"}`。
    """
    pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


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
            page_payload(
                items=data,
                total=self.page.paginator.count,
                page=self.page.number,
                page_size=self.get_page_size(self.request),
            )
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
