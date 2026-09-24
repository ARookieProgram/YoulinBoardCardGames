/**
 * 登录相关接口。
 *
 * 对应后端 `apps/accounts/urls.py` 的四个端点。参数与返回值类型见 `types.ts`。
 */

import { get, post } from './client'
import type { AdminUser, LoginPayload, LoginResult, LogoutResult, RefreshResult } from './types'

/**
 * 登录。
 *
 * 成功时由调用方（auth store）负责把令牌写进本地存储。
 *
 * @param payload 账号与口令。
 * @returns 令牌与管理员信息。
 */
export function login(payload: LoginPayload): Promise<LoginResult> {
  // 登录接口可能较慢（口令哈希比较），给足超时。
  return post<LoginResult>('auth/login/', payload, { timeout: 15_000 })
}

/**
 * 用 refresh 换新的 access（一般不需要手动调用，拦截器会自动续期）。
 */
export function refresh(refreshToken: string): Promise<RefreshResult> {
  return post<RefreshResult>('auth/refresh/', { refresh: refreshToken })
}

/**
 * 取当前登录的管理员信息。
 *
 * 前端每次刷新页面都靠它校验登录态是否仍然有效。
 */
export function getCurrentAdmin(): Promise<AdminUser> {
  return get<AdminUser>('auth/me/')
}

/**
 * 退出登录。
 *
 * @param refreshToken 本地存的 refresh；没有也要照常调用，
 *   服务端会按"已退出"处理。
 */
export function logout(refreshToken?: string | null): Promise<LogoutResult> {
  return post<LogoutResult>('auth/logout/', { refresh: refreshToken ?? '' })
}

/** 健康检查（排查"后端有没有起来"时用）。 */
export function health(): Promise<{ service: string; status: string }> {
  return get<{ service: string; status: string }>('health/')
}
