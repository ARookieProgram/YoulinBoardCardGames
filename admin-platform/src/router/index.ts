/**
 * 路由与登录守卫。
 *
 * 路由表在 `./routes.ts`（菜单要读同一份），这里只负责创建实例与守卫。
 *
 * 守卫的判定顺序（每一步都必要）：
 *
 *  1. 目标路由 `meta.public`（登录页、404）→ 按登录状态处理；
 *  2. 本地没有任何令牌 → 跳登录页，并把原目标记进 `redirect`；
 *  3. 令牌可能快过期 → 先进后台前换一次，减少第一个请求撞 401 的概率；
 *  4. 有令牌但还没拉过 `/me/` → 拉一次（刷新页面后恢复登录态）；
 *  5. 拉不到（令牌失效）→ 跳登录页；
 *  6. 角色不足的页面 → 挡回控制台。
 *
 * 第 4 步是唯一会发请求的地方，且每个会话只发一次（store 里的 `resolved`）。
 */

import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'

import { AUTH_EXPIRED_EVENT, refreshIfNeeded } from '@/api/client'
import { hasTokens } from '@/api/token'
import { useAuthStore } from '@/stores/auth'

import { HOME_PATH, LOGIN_PATH, routes } from './routes'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

/** 把目标路径安全地转成 `redirect` 查询参数（只接受站内单斜杠路径）。 */
function safeRedirect(target: RouteLocationNormalized): string {
  const full = target.fullPath
  // 以 `//` 开头的是协议相对 URL，会把用户带去外站，必须挡掉。
  if (!full.startsWith('/') || full.startsWith('//')) return HOME_PATH
  return full
}

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 1. 公开页面：已登录时不再停留在登录页。
  if (to.meta.public === true) {
    if (to.name === 'login' && auth.isLoggedIn) {
      return { path: HOME_PATH, replace: true }
    }
    return true
  }

  // 2. 没有任何令牌，直接去登录页。
  if (!hasTokens()) {
    return { path: LOGIN_PATH, query: { redirect: safeRedirect(to) }, replace: true }
  }

  // 3. 令牌可能快过期了，先换一次。
  await refreshIfNeeded()

  // 4. 有令牌但还没确认身份（首次进入或刷新页面）→ 拉一次 /me/。
  if (!auth.resolved) {
    await auth.fetchCurrentAdmin()
    if (!auth.isLoggedIn) {
      return { path: LOGIN_PATH, query: { redirect: safeRedirect(to) }, replace: true }
    }
  }

  // 5. 角色不足的页面挡回控制台。
  if (to.meta.requiresSuperAdmin === true && !auth.isSuperAdmin) {
    return { path: HOME_PATH, replace: true }
  }

  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  const appTitle = import.meta.env.VITE_APP_TITLE || '管理平台'
  document.title = title ? `${title} · ${appTitle}` : appTitle
})

// 令牌在任何请求里失效时（拦截器派发的事件），立刻送回登录页。
window.addEventListener(AUTH_EXPIRED_EVENT, () => {
  const auth = useAuthStore()
  auth.reset()
  const current = router.currentRoute.value
  if (current.meta.public !== true) {
    void router.replace({ path: LOGIN_PATH, query: { redirect: safeRedirect(current) } })
  }
})

export { HOME_PATH, LOGIN_PATH }
export default router
