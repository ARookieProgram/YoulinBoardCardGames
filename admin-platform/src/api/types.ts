/**
 * 后端契约类型。
 *
 * 与 `server-python/platform_server` 一一对应，改动时两边同时改：
 *  - 统一响应外壳 `ApiEnvelope` 由 `apps/common/response.py` 产出；
 *  - 业务错误码 `ErrorCode` 定义在 `apps/common/error_codes.py`；
 *  - 管理员字段由 `apps/accounts/serializers.py` 的 `AdminUserSerializer` 输出。
 */

/** 统一响应外壳：`code === 0` 表示成功。 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

/** 业务错误码（与后端 `apps/common/error_codes.py` 保持一致）。 */
export const ErrorCode = {
  /** 成功。 */
  OK: 0,
  /** 参数不合法。 */
  BAD_REQUEST: 10001,
  /** 未登录或令牌失效 —— 前端据此跳登录页。 */
  UNAUTHORIZED: 10002,
  /** 已登录但无权限。 */
  FORBIDDEN: 10003,
  /** 资源不存在。 */
  NOT_FOUND: 10004,
  /** 请求过于频繁。 */
  TOO_MANY_REQUESTS: 10005,
  /** 服务端内部错误。 */
  SERVER_ERROR: 10500,
  /** 账号或密码错误。 */
  LOGIN_FAILED: 11001,
  /** 账号已被禁用。 */
  ACCOUNT_DISABLED: 11002,
  /** 刷新令牌无效或过期。 */
  TOKEN_INVALID: 11003,
} as const

export type ErrorCodeValue = (typeof ErrorCode)[keyof typeof ErrorCode]

/** 管理员角色。 */
export type AdminRole = 'operator' | 'admin' | 'super_admin'

/** 管理员账号状态。 */
export type AdminStatus = 'active' | 'disabled'

/** 当前登录的管理员。 */
export interface AdminUser {
  id: number
  username: string
  nickname: string
  /** 优先昵称、否则用户名（后端 `display_name`）。 */
  display_name: string
  email: string
  role: AdminRole
  /** 角色的中文名，直接用于展示。 */
  role_display: string
  status: AdminStatus
  status_display: string
  is_superuser: boolean
  /** `YYYY-MM-DD HH:mm:ss`，从未登录时为 `null`。 */
  last_login: string | null
  last_login_ip: string | null
  created_at: string
}

/** 登录/刷新的入参。 */
export interface LoginPayload {
  username: string
  password: string
}

/** 登录成功的返回。 */
export interface LoginResult {
  access: string
  refresh: string
  /** access 的过期时间（Unix 秒）。 */
  access_expires_at: number
  user: AdminUser
}

/** 刷新令牌的返回（`refresh` 因轮换而存在）。 */
export interface RefreshResult {
  access: string
  refresh?: string
  access_expires_at?: number
  refresh_expires_at?: number
  user: AdminUser
}

/** 退出登录的返回。 */
export interface LogoutResult {
  /** 服务端是否成功吊销了 refresh 令牌。 */
  revoked: boolean
}
