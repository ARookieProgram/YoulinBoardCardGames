"""管理平台账号体系 —— 与玩家账号**完全隔离**。

隔离体现在四个层面，任何一条都不能破：

1. **独立的表**：`AdminUser` 建在 `accounts_adminuser` 表，玩家账号在
   `t_accounts` / `t_users`（`server/sql/db_babykylin.sql`）。两者没有外键、
   没有同名复用、也不做账号名同步。
2. **独立的库**：默认连 `db_scmj_admin`，与玩家库 `db_scmj` 物理分开
   （见 `config/settings.py` 的数据库段落）。
3. **独立的登录入口**：管理端走 `/api/auth/login/`，玩家走账号服的 `/login`。
   两边互不发放凭证。
4. **独立的令牌**：管理平台用 JWT（SimpleJWT），玩家侧用自研的
   `tokenmgr`（md5 签名）。管理端的 token 在玩家侧毫无意义，反之亦然。

**最重要的推论**：玩家表里的任何账号，无论叫什么名字、是不是管理员，
都**不能**登录管理平台；管理平台的账号也不能作为游戏账号使用。
"""
