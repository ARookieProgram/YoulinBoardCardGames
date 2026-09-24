"""WSGI 入口。

同步部署用这个（gunicorn / uwsgi / `manage.py runserver`）：

    gunicorn config.wsgi:application --bind 0.0.0.0:8000
"""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
