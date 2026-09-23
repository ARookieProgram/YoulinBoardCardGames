# 项目技能（`.dsh/skills/`）

本目录是 DeepSeek Harness 的**项目级技能包**。每个子目录是一个技能，
Harness 读取 `SKILL.md` 的 YAML frontmatter，按 `description` 判断何时加载，因此
`description` 要写清"什么时候该用它"。

## 加载规则（必须遵守，否则技能会被静默忽略）

1. 项目根由 `.git` 标记 —— 技能**必须**放在本目录，放在 `client/` 或 `server/` 下不会被发现。
2. 每个技能是 `<name>/SKILL.md`，frontmatter 必须含**非空**的 `name` 与 `description`。
3. **`name` 必须与目录名完全一致**（`verify-gate/SKILL.md` 的 `name` 必须是 `verify-gate`）。
4. 正文里可引用其他文件：用反引号包裹、以 `repo:` 开头（例如 `repo:server/utils/db.ts`），
   `npm run check:harness` 会校验这些路径真实存在。
5. 正文过短（< 200 字符）或 `description` 过短（< 20 字符）会被门禁判为无效。
6. **不要在 `.dsh/skills/` 根下放 `README.md` 之类的散装 `.md` 文件**：技能提供方会把根目录下
   每个 `.md` 都当成一个技能候选，没有 frontmatter 就会被静默忽略。本文档因此放在
   `docs/ai-native/` 而不是技能目录里；`npm run check:harness` 会拦下这类文件。

改完任何技能后跑：

```bash
npm run check:harness
```

## 现有技能

| 技能 | 什么时候加载 |
| --- | --- |
| `verify-gate` | 跑/读/扩展验证门禁；门禁报红时；新增检查或断言时 |
| `server-architecture` | 改服务端代码、加 HTTP 接口、加或改 Socket.IO 推送事件 |
| `game-rules` | 改听牌/胡牌/番型、动作流程、两份 `gamemgr_*` 的同步 |
| `client-integration` | 改客户端组件、加事件处理器、改场景流程、判断哪些文件不能手改 |
| `data-layer` | 改持久化、加 `db.ts` 函数、改 SQL schema、排查数据问题 |

## 新增一个技能

```bash
mkdir -p .dsh/skills/<name>
$EDITOR .dsh/skills/<name>/SKILL.md
npm run check:harness     # 必须通过
```

`SKILL.md` 模板：

```markdown
---
name: <与目录名一致>
description: <一句话说明"做什么"以及"什么时候该加载"，会被模型用来决定是否加载>
---

# 标题

## 什么时候用
...

## 正文
...（引用文件请写 `repo:相对路径`）
```

## 写作原则

- 技能是**给下一次会话的操作手册**，不是百科。写"改哪里、按什么顺序、怎么验证"，
  而不是复制源码。
- 把**容易搞错的地方**写清楚：两份并行实现、不能手改的文件、
  静默失败的模式（frontmatter 不匹配、事件名不一致）。
- 只写**已经核实过**的事实。不确定的写"待确认"，不要编造。
- 与 `AGENTS.md` 的分工：`AGENTS.md` 是每次必读的短契约；技能是按需加载的长知识。
  不要把长知识塞进 `AGENTS.md`，也不要把必读红线只写在技能里。
