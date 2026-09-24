"""ASGI 入口。

异步部署用这个（uvicorn / daphne）：

    uvicorn config.asgi:application --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
