"""管理平台后端。

各子包职责：

* `config/` —— Django 工程配置（settings / urls / wsgi / asgi）；
* `apps/common/` —— 跨模块的响应格式、异常处理、分页等公共设施；
* `apps/accounts/` —— **管理平台自己的账号体系**（管理员、角色、登录、JWT）。

注意：这里的一切都只服务于后台管理端，与 `server-python/` 三进程的玩家账号
（`t_accounts` / `t_users`）没有任何共用代码或共用表。
"""
