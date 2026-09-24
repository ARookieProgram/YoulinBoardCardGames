# admin-platform — 游戏管理平台前端

技术栈：**Vue 3（`<script setup>` + TypeScript）+ Element Plus + Pinia + Vue Router + Vite**。

配套后端是 `server-python/platform_server`（Django + DRF + SimpleJWT，默认 :8000）。

> 后台管理前端，与游戏客户端（`client/`，Cocos Creator）没有任何关系：
> 不共用代码、不共用构建、不共用接口。

---

## 1. 本期范围

已交付**登录闭环 + 后台骨架 + 玩家管理 + 房间管理**：

* 登录页（表单校验、错误提示、回车提交、后端可达性探测）；
* 登录态管理（Pinia store + localStorage 持久化）；
* 请求层（axios 拦截器：拆响应外壳 + **401 自动续期并重放原请求**）；
* 路由守卫（未登录跳登录页、刷新页面恢复登录态、角色不足挡回控制台）；
* 后台布局（侧边菜单 + 顶栏 + 退出登录）；
* **玩家管理**：查询 / 房卡展示 / 封禁解封，并预留"对局记录""充值记录"两个查询入口；
* **房间管理**：只读监控存活房间（列表 / 概览 / 详情：配置、四个座位、所在游戏服），
  并预留"强制解散"这个运维入口（后端恒返回 `reserved: true`，见
  `server-python/platform_server/README.md` §6.6）；
* 控制台与剩余占位页（对局记录 / 管理员账号）。

后续业务页面接进 `src/router/routes.ts` 的 `children` 即可，
菜单会**自动**多出一项（菜单由路由表派生，见 `src/utils/menu.ts`）。

> 两个已接入的页面都**只读**玩家数据：数据来自后端对玩家库 `db_scmj`
> 的只读数据源（`t_users` / `t_rooms`），前端不关心它从哪张表来，只认
> `src/api/` 里的契约类型。

---

## 2. 快速开始

```bash
# 1) 先起后端（见 server-python/platform_server/README.md）
cd ../server-python/platform_server
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py seed_admin          # 记下打印出来的账号口令
../.venv/bin/python manage.py runserver 127.0.0.1:8000

# 2) 起前端 dev server
cd admin-platform
npm install
npm run dev                                       # → http://127.0.0.1:5173
```

浏览器打开 <http://127.0.0.1:5173/>，用 `seed_admin` 输出的账号登录。

### 接口代理

前端**不直连**后端地址，而是请求同源的 `/api`，由 Vite 代理转发
（`vite.config.ts` 读 `VITE_API_PROXY_TARGET`，默认 `http://127.0.0.1:8000`）。
好处是开发期不涉及 CORS，生产换成网关/同域部署时前端代码一行都不用改。

环境变量见 `.env.example`：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8000` | dev server 代理目标 |
| `VITE_API_BASE_URL` | `/api` | 请求前缀 |
| `VITE_APP_TITLE` | `幼麟麻将管理平台` | 浏览器标签标题 |

### 其他命令

```bash
npm run type-check      # vue-tsc --build（strict，含 noUncheckedIndexedAccess）
npm run build           # type-check + 生产构建到 dist/
npm run preview         # 本地预览构建产物
```

> **本机 npm 缓存权限异常时**：若 `npm install` 报
> `EPERM ... Your cache folder contains root-owned files`，用项目内缓存兜底：
> `npm install --cache ./.npm-cache`（该目录已 gitignore）。
> 根治办法是 `sudo chown -R $(id -u):$(id -g) ~/.npm`。

---

## 3. 目录结构

```
src/
├─ main.ts                 入口：注册 Pinia / Router / Element Plus / 图标
├─ App.vue                 只有 <RouterView />（登录页不套后台布局）
├─ api/
│   ├─ types.ts            后端契约类型 + 业务错误码 ErrorCode
│   ├─ token.ts            令牌的 localStorage 读写（无依赖，避免循环引用）
│   ├─ errors.ts           ApiError（业务失败）/ NetworkError（网络层失败）
│   ├─ client.ts           axios 实例 + 拆外壳 + 401 自动续期
│   ├─ auth.ts             登录 / 刷新 / me / 退出 / 健康检查
│   ├─ players.ts          玩家管理接口（列表 / 详情 / 封禁解封 / 两个预留入口）
│   └─ rooms.ts            房间管理接口（列表 / 概览 / 详情 / 预留的强制解散）
├─ stores/auth.ts          登录态（当前管理员、登录、登出、拉取身份）
├─ router/
│   ├─ routes.ts           路由表（菜单也从这里派生）
│   ├─ meta.d.ts           RouteMeta 类型扩展
│   └─ index.ts            路由器 + 登录守卫 + 令牌失效监听
├─ layouts/AdminLayout.vue 后台骨架（侧边菜单 / 顶栏 / 内容区）
├─ views/                  LoginView / DashboardView / PlayerListView / RoomListView
│                          / PlaceholderView / NotFoundView
├─ components/             PlayerDetailDrawer.vue / RoomDetailDrawer.vue
├─ utils/                  menu.ts（由路由表生成菜单）、format.ts、
│                          room.ts（房间的展示口径：玩法/自摸/点杠花的中文名等）
└─ assets/main.css         全局样式
```

---

## 4. 请求层怎么用

拦截器已经把响应外壳拆掉了，所以业务代码直接拿数据，**不用**再写 `.data.data`：

```ts
import { get, post } from '@/api/client'
import type { AdminUser } from '@/api/types'

const me = await get<AdminUser>('auth/me/')          // 直接是 AdminUser
```

失败时抛的异常：

| 异常 | 含义 | 处理建议 |
| --- | --- | --- |
| `ApiError` | 请求到达后端且后端返回失败 | `error.message` 是后端写好的中文，直接 `ElMessage.error` |
| `NetworkError` | 没拿到响应（后端没起、断网、超时） | 提示"网络异常"，并考虑提示检查后端 |

`ApiError.code` 是业务码（`ErrorCode` 里有常量），`ApiError.status` 是 HTTP 状态码。

### 令牌自动续期

`access` 过期时后端返回 401，拦截器会：

1. 用 `refresh` 换一对新令牌（**响应里的新 refresh 会覆盖本地的**，
   因为后端开启了轮换，旧 refresh 一次性）；
2. **重放原请求**，调用方完全无感；
3. 并发的多个 401 只触发**一次**刷新，其余请求排队共享结果
   （否则后到的刷新会因旧 refresh 已进黑名单而失败，把用户误踢下线）；
4. 刷新也失败 → 派发 `auth:expired` 事件 → 路由守卫跳登录页。

> ⚠️ 后端只吊销 `refresh`；**已签发的 access 在过期前依然有效**。
> 这是 JWT 的固有限制，不是 bug。

---

## 5. 加一个新页面

1. 在 `src/views/` 新建 `<Name>View.vue`；
2. 在 `src/router/routes.ts` 的 `children` 里加一条（带 `meta.title`，可选 `meta.icon`）：

```ts
{
  path: 'orders',
  name: 'orders',
  component: () => import('@/views/OrdersView.vue'),
  meta: { title: '订单管理', icon: 'Tickets' },
}
```

菜单、页面标题、登录守卫都会自动生效。需要"仅超级管理员"就加
`meta.requiresSuperAdmin: true`（守卫与菜单用的是同一个判据）。
`meta.icon` 的取值来自 `@element-plus/icons-vue` 的组件名（已在 `main.ts` 全局注册）。

---

## 6. 约定

* **TypeScript strict**，且开了 `noUncheckedIndexedAccess`——
  数组下标访问返回 `T | undefined`，取值前要判空。
* Element Plus 与图标都是**全量引入**（见 `main.ts`）：这是内部管理系统，
  省掉按需引入的插件与类型声明维护成本。
* 组件样式写在各自的 `<style scoped>` 里；`assets/main.css` 只放全局的东西。
* 业务错误码在前端 `src/api/types.ts` 与后端
  `server-python/platform_server/apps/common/error_codes.py` 各有一份，
  **改一处要同步另一处**。
* 注释用中文（仓库既有约定）。
