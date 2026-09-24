/**
 * 侧边菜单的构建。
 *
 * 菜单**从路由表派生**，而不是单独维护一份列表：新增一个带 `meta.title`
 * 的子路由，侧边栏就自动多一项，不会出现"加了页面忘了加菜单"。
 * `meta.requiresSuperAdmin` 的项只对超级管理员显示（与路由守卫同一判据）。
 */

import { routes } from '@/router/routes'

/** 菜单项。 */
export interface MenuItem {
  /** 路由名（`name`），用作 `el-menu-item` 的 index。 */
  name: string
  /** 完整路径。 */
  path: string
  /** 展示文案。 */
  title: string
  /** Element Plus 图标组件名，侧边栏按名字渲染。 */
  icon?: string
}

/** 由路径片段拼出完整路径（父路由是 `/`，所以子路径补一个前导斜杠）。 */
function toAbsolutePath(path: string): string {
  return path.startsWith('/') ? path : `/${path}`
}

/**
 * 取全部菜单项。
 *
 * @param isSuperAdmin 当前用户是否超级管理员。
 * @returns 过滤并排序后的菜单项。
 */
export function buildMenuItems(isSuperAdmin: boolean): MenuItem[] {
  // 后台布局是唯一带 children 的顶层路由，子路由就是页面清单。
  const layout = routes.find((route) => (route.children?.length ?? 0) > 0)
  const children = layout?.children ?? []

  return children
    .filter((route) => typeof route.meta?.title === 'string')
    .filter((route) => route.meta?.requiresSuperAdmin !== true || isSuperAdmin)
    .map((route) => ({
      name: String(route.name ?? ''),
      path: toAbsolutePath(route.path),
      title: String(route.meta?.title ?? ''),
      icon: typeof route.meta?.icon === 'string' ? route.meta.icon : undefined,
    }))
}
