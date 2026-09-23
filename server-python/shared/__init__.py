"""跨进程共享的类型契约与域模型。

Node 版把这一层放在 `server/types/`；Python 版改名为 `shared/`，
**唯一原因是 `types` 会遮蔽标准库的 `types` 模块**（`dataclasses`、`enum` 等都会
`import types`，一旦 `server-python/` 出现在 `sys.path` 上就会把它们打坏）。
除目录名之外，文件划分与 Node 版一一对应：

    types/config.ts   -> shared/config.py
    types/domain.ts   -> shared/domain.py
    types/protocol.ts -> shared/protocol.py
    types/db_rows.ts  -> shared/db_rows.py
"""
