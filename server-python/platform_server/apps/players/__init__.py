"""玩家管理。

本应用做两件事，边界刻意分得很清：

* **读玩家数据**（账号 / 昵称 / 房卡 `gems` / 金币）——通过 `player_source.py`
  的**只读数据源**直连玩家库 `db_scmj`，只执行 SELECT；
* **写封禁状态**——落在管理平台自己的库 `db_scmj_admin`（`PlayerBan` 表），
  不往玩家库写任何一行。

也就是说：玩家库在这个应用里**只有只读入口**，可写的东西全在本平台的库里。
这条边界由 `apps/players/player_source.py` 的 `_assert_read_only()` 与
`tests/test_players.py` 的隔离断言共同钉住。
"""
