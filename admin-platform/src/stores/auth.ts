/**
 * 登录态 store。
 *
 * 只保存"当前管理员"，令牌本身存在 `api/token.ts`（localStorage），
 * 因为 axios 拦截器要在 store 之外读它们。这里的 getter 都从令牌与内存状态派生。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'
import { getRefreshToken, hasTokens, setTokens, clearTokens } from '@/api/token'
import type { AdminUser, LoginPayload } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  // ---------------------------------------------------------------- state

  /** 当前登录的管理员；`null` 表示未登录或尚未拉取。 */
  const admin = ref<AdminUser | null>(null)

  /**
   * 是否已经拿过一次 `/me/`。
   * 路由守卫靠它区分"还没拉取"和"拉取过但确实未登录"，
   * 避免每次跳转都重复请求。
   */
  const resolved = ref(false)

  /** 是否正在处理登录/登出，用于按钮 loading。 */
  const pending = ref(false)

  // ---------------------------------------------------------------- getters

  /** 是否已登录（有管理员信息）。 */
  const isLoggedIn = computed(() => admin.value !== null)

  /** 展示名：昵称优先，其次用户名。 */
  const displayName = computed(
    () => admin.value?.display_name || admin.value?.username || '未登录',
  )

  /**
   * **权限口径**的角色（后端 `effective_role`）。
   *
   * `is_superuser=true` 的历史行一律算超级管理员，这时 `effective_role` 是
   * `super_admin` 而原始 `role` 可能还停在旧值。权限判断必须用这个字段，
   * 否则会出现"后端放行、前端把菜单藏了"的不一致。
   */
  const effectiveRole = computed(() => admin.value?.effective_role ?? null)

  /** 原始角色字段，未登录时为 `null`（仅用于展示"这一行原本是什么"）。 */
  const role = computed(() => admin.value?.role ?? null)

  /** 角色展示名，按**权限口径**给出（列表页 / 顶栏 / 控制台共用）。 */
  const roleDisplay = computed(() => {
    const current = admin.value
    if (!current) return '未知角色'
    const labels: Record<AdminUser['effective_role'], string> = {
      operator: '运营',
      admin: '管理员',
      super_admin: '超级管理员',
    }
    return labels[current.effective_role] ?? current.role_display
  })

  /** 是否超级管理员（**权限口径**，与后端 `IsSuperAdmin` 一致）。 */
  const isSuperAdmin = computed(() => effectiveRole.value === 'super_admin')

  /** 是否管理员及以上（**权限口径**，与后端 `IsAdminOrAbove` 一致）。 */
  const isAdminOrAbove = computed(
    () => effectiveRole.value === 'admin' || effectiveRole.value === 'super_admin',
  )

  // ---------------------------------------------------------------- actions

  /**
   * 登录并把令牌落到本地存储。
   *
   * @param payload 账号与口令。
   * @throws {import('@/api/errors').ApiError} 账号或口令错误、账号被禁用等。
   */
  async function login(payload: LoginPayload): Promise<AdminUser> {
    pending.value = true
    try {
      const result = await authApi.login(payload)
      setTokens(result.access, result.refresh, result.access_expires_at)
      admin.value = result.user
      resolved.value = true
      return result.user
    } finally {
      pending.value = false
    }
  }

  /**
   * 拉取当前管理员信息，用于刷新页面后恢复登录态。
   *
   * 失败（令牌失效）时清掉本地状态并返回 `null`，**不抛异常**——
   * 调用方（路由守卫）只关心"有没有登录"。
   */
  async function fetchCurrentAdmin(): Promise<AdminUser | null> {
    if (!hasTokens()) {
      admin.value = null
      resolved.value = true
      return null
    }

    try {
      admin.value = await authApi.getCurrentAdmin()
      return admin.value
    } catch {
      // 令牌无效/过期且无法续期：当作未登录处理。
      clearTokens()
      admin.value = null
      return null
    } finally {
      resolved.value = true
    }
  }

  /**
   * 退出登录。
   *
   * 即使服务端吊销失败（例如令牌早已过期），本地也必须清干净，
   * 否则用户会卡在"看起来还登录着但什么都做不了"的状态。
   */
  async function logout(): Promise<void> {
    pending.value = true
    try {
      await authApi.logout(getRefreshToken())
    } catch {
      // 忽略：本地清理才是关键。
    } finally {
      clearTokens()
      admin.value = null
      resolved.value = true
      pending.value = false
    }
  }

  /** 强制清空本地登录态（令牌失效时由拦截器事件触发）。 */
  function reset(): void {
    clearTokens()
    admin.value = null
    resolved.value = true
  }

  return {
    // state
    admin,
    resolved,
    pending,
    // getters
    isLoggedIn,
    displayName,
    role,
    effectiveRole,
    roleDisplay,
    isSuperAdmin,
    isAdminOrAbove,
    // actions
    login,
    logout,
    fetchCurrentAdmin,
    reset,
  }
})
