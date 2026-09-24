/**
 * axios 实例与拦截器。
 *
 * 拦截器做两件事，业务代码因此只需要关心 `data`：
 *
 *  1. **拆外壳**：后端统一返回 `{code, message, data}`。`code !== 0` 一律抛
 *     `ApiError`；成功则把 `data` 直接返回，调用方写 `const user = await getMe()`。
 *  2. **自动续期**：`access` 过期时后端返回 401。此时用 `refresh` 换一对新令牌
 *     并**重放原请求**，调用方无感。并发的多个 401 只会触发一次刷新
 *     （见下方的 `refreshPromise`），其余请求排队等结果。
 *
 * 刷新用的 HTTP 调用直接走 `axios.post` 而不是本实例：本实例的拦截器会把
 * 失败翻译成 `ApiError`，而刷新逻辑需要看**原始响应**来决定怎么处理。
 */

import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'

import { ApiError, NetworkError } from './errors'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  isAccessExpired,
  setTokens,
} from './token'
import type { ApiEnvelope, RefreshResult } from './types'

/** 接口前缀，默认走 Vite 代理。 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || '/api'

/** 请求超时（毫秒）。管理后台的接口都是轻查询，30 秒足够。 */
const TIMEOUT_MS = 30_000

/** 刷新令牌的接口路径（相对 `API_BASE_URL`，且不带前导斜杠）。 */
const REFRESH_PATH = 'auth/refresh/'

/** 登录态彻底失效时派发的事件名，由 router 监听后跳登录页。 */
export const AUTH_EXPIRED_EVENT = 'auth:expired'

/** 带重试标记的请求配置。 */
interface RetryableConfig extends InternalAxiosRequestConfig {
  /** 已经重放过一次就不再重放，避免死循环。 */
  __isRetry?: boolean
  /** 标记这是刷新令牌的请求，避免刷新失败时再触发刷新。 */
  __skipAuthRefresh?: boolean
}

export const http: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
})

/** 登录态失效时通知外部（router）。 */
function notifyAuthExpired(): void {
  clearTokens()
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT))
}

// ---------------------------------------------------------------- 请求拦截

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// ---------------------------------------------------------------- 响应拦截

/**
 * 正在进行中的刷新请求。
 *
 * 多个并发请求同时收到 401 时，只发一次刷新，其余共享同一个 Promise ——
 * 否则每个 401 都会去刷新，而 refresh 是**一次性**的（会轮换），
 * 后到的刷新全会失败并把用户踢下线。
 */
let refreshPromise: Promise<string> | null = null

/** 调用刷新接口，返回新的 access 令牌。 */
async function requestNewAccessToken(): Promise<string> {
  const refresh = getRefreshToken()
  if (!refresh) {
    throw new ApiError(11003, '登录已过期，请重新登录', 401)
  }

  const response = await axios.post<ApiEnvelope<RefreshResult>>(
    `${API_BASE_URL}/${REFRESH_PATH}`,
    { refresh },
    { timeout: TIMEOUT_MS, headers: { 'Content-Type': 'application/json' } },
  )

  const body = response.data
  if (body.code !== 0 || !body.data?.access) {
    throw new ApiError(body.code || 11003, body.message || '登录已过期，请重新登录', 401)
  }

  // 轮换后的 refresh 必须覆盖本地那一个，否则下一次刷新会失败。
  setTokens(body.data.access, body.data.refresh, body.data.access_expires_at)
  return body.data.access
}

/** 确保拿到一个可用的 access，必要时刷新。 */
function ensureFreshToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = requestNewAccessToken().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

http.interceptors.response.use(
  (response) => {
    const body = response.data as ApiEnvelope<unknown> | undefined

    // 非统一外壳（例如 Django 调试页返回 HTML）时原样返回，交给调用方判断。
    if (body === undefined || typeof body !== 'object' || !('code' in body)) {
      return response
    }

    if (body.code !== 0) {
      throw new ApiError(body.code, body.message || '请求失败', response.status, body.data)
    }

    // 拆掉外壳：调用方直接拿 data。
    response.data = body.data
    return response
  },
  async (error: AxiosError<ApiEnvelope<unknown>>) => {
    const config = error.config as RetryableConfig | undefined

    // 没有响应 = 网络层问题（后端没起、断网、超时）。
    if (!error.response) {
      if (error.code === 'ECONNABORTED') {
        return Promise.reject(new NetworkError('请求超时，请稍后重试'))
      }
      return Promise.reject(new NetworkError())
    }

    const { status, data } = error.response
    const body = data as ApiEnvelope<unknown> | undefined

    // 401：尝试用 refresh 续期后重放原请求。
    // 只重放一次，且刷新接口自身的 401 不再触发刷新。
    if (status === 401 && config && !config.__isRetry && !config.__skipAuthRefresh) {
      config.__isRetry = true
      try {
        const access = await ensureFreshToken()
        config.headers.set('Authorization', `Bearer ${access}`)
        return await http.request(config)
      } catch {
        notifyAuthExpired()
        return Promise.reject(
          new ApiError(body?.code ?? 11003, '登录已过期，请重新登录', 401, body?.data),
        )
      }
    }

    // 401 且已经重试过（或没有 refresh）：直接登出。
    if (status === 401) {
      notifyAuthExpired()
    }

    const code = body?.code ?? status
    const message = body?.message ?? `请求失败（HTTP ${status}）`
    return Promise.reject(new ApiError(code, message, status, body?.data))
  },
)

/**
 * 主动判断令牌是否即将过期，用于路由守卫。
 *
 * 只是"提前刷新"的优化；真正的过期判定仍然由服务端的 401 兜底。
 */
export function shouldRefreshBeforeNavigation(): boolean {
  return getAccessToken() !== null && isAccessExpired()
}

/**
 * 在进入受保护路由前把令牌换成新鲜的。
 *
 * 失败时不抛异常（由后续请求的 401 处理），返回是否成功。
 */
export async function refreshIfNeeded(): Promise<boolean> {
  if (!shouldRefreshBeforeNavigation()) return true
  try {
    await ensureFreshToken()
    return true
  } catch {
    return false
  }
}

/** GET 请求，直接拿到拆壳后的数据。 */
export async function get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const response = await http.get<T>(url, config)
  return response.data
}

/** POST 请求，直接拿到拆壳后的数据。 */
export async function post<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await http.post<T>(url, data, config)
  return response.data
}
