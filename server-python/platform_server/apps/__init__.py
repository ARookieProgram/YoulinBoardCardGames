"""管理平台后端。

各子包职责：

* `config/` —— Django 工程配置（settings / urls / wsgi / asgi）；
* `apps/common/` —— 跨模块的响应格式、异常处理、分页等公共设施；
* `apps/accounts/` —— **管理平台自己的账号体系**（管理员、角色、登录、JWT）；
* `apps/players/` —— 玩家管理（**只读**玩家库 `db_scmj` 的 `t_users`，
  封禁记录只落本平台的 `players_playerban`）。

注意：这里的一切都只服务于后台管理端，与 `server-python/` 三进程的玩家账号
（`t_accounts` / `t_users`）没有共用代码、共用表或共用连接池——
玩家库在 `apps/players/player_source.py` 里只有**只读**入口。
"""
