/**
 * 路由表。
 *
 * 单独成模块（而不是写在 `router/index.ts` 里）的原因：侧边菜单
 * （`utils/menu.ts`）需要**读同一份路由表**来生成菜单项，
 * 如果路由定义和守卫写在一起，菜单就得反向 import 路由器，形成环形依赖。
 *
 * 新增页面时只改这里即可——菜单、标题、守卫都会自动跟上。
 */

import type { RouteRecordRaw } from 'vue-router'

import AdminLayout from '@/layouts/AdminLayout.vue'

/** 登录页路径。 */
export const LOGIN_PATH = '/login'

/** 登录后的默认落地页。 */
export const HOME_PATH = '/dashboard'

export const routes: RouteRecordRaw[] = [
  {
    path: LOGIN_PATH,
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: AdminLayout,
    redirect: HOME_PATH,
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '控制台', icon: 'HomeFilled' },
      },
      // 玩家管理已接入真实接口：查询 / 房卡展示 / 封禁解封，
      // 并预留了"对局记录""充值记录"两个查询入口（见 PlayerListView）。
      {
        path: 'players',
        name: 'players',
        component: () => import('@/views/PlayerListView.vue'),
        meta: { title: '玩家管理', icon: 'User' },
      },
      // 房间管理已接入真实接口：只读监控存活房间（列表 / 概览 / 详情），
      // 并预留了"强制解散"这个运维入口（见 RoomListView）。
      {
        path: 'rooms',
        name: 'rooms',
        component: () => import('@/views/RoomListView.vue'),
        meta: { title: '房间管理', icon: 'Grid' },
      },
      // 对局记录已接入真实接口：对局列表 / 概览 / 单个房间的全部对局 /
      // 单局出牌记录 / 某个玩家的最近战绩（见 GameListView 与 api/games.ts）。
      {
        path: 'games',
        name: 'games',
        component: () => import('@/views/GameListView.vue'),
        meta: { title: '对局记录', icon: 'Tickets' },
      },
      // 管理员账号管理已接入真实接口：查询 / 新建 / 改资料与角色 / 启用停用 /
      // 重置口令 / 删除（见 AdminListView 与 api/admins.ts）。
      // 该页**只对超级管理员开放**：前端靠 requiresSuperAdmin 隐藏菜单与挡路由，
      // 后端 `/api/admins/` 也只认 IsSuperAdmin（前端置灰不是防线）。
      {
        path: 'system/admins',
        name: 'admins',
        component: () => import('@/views/AdminListView.vue'),
        meta: { title: '管理员账号', icon: 'Setting', requiresSuperAdmin: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]
