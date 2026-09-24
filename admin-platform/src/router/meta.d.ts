/**
 * `meta` 的类型扩展，让守卫与布局都能安全读取自定义字段。
 * 没有这段声明，`to.meta.title` 在 strict 模式下会是 `unknown`。
 */

import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    /** 是否无需登录即可访问（只有登录页）。 */
    public?: boolean
    /** 页面标题，用于侧边菜单与浏览器标签。 */
    title?: string
    /** Element Plus 图标组件名，用于侧边菜单。 */
    icon?: string
    /** 是否仅超级管理员可见/可进。 */
    requiresSuperAdmin?: boolean
  }
}

export {}
