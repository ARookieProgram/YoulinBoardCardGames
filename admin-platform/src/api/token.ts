/**
 * 令牌的本地持久化。
 *
 * 单独成一个模块（而不是放进 Pinia store）是为了打破循环依赖：
 * `request.ts` 需要在拦截器里读令牌与刷新令牌，而 store 又依赖 request。
 * 这里不 import 任何本方模块，谁都能安全引用。
 *
 * 存储位置是 `localStorage`，因此**同一浏览器的多个标签页共享登录态**。
 * 安全边界：localStorage 对 XSS 不设防。管理平台是内部工具，这个取舍可以接受；
 * 若日后要收紧，改成后端下发的 HttpOnly Cookie（需要同时调整 DRF 的认证方式）。
 */

/** localStorage 的键名，加前缀避免与同域其他应用冲突。 */
const KEY_ACCESS = 'scmj_admin_access'
const KEY_REFRESH = 'scmj_admin_refresh'
/** access 过期时间（Unix 秒），用于提前刷新，避免总是撞 401。 */
const KEY_ACCESS_EXPIRES_AT = 'scmj_admin_access_exp'

/** 提前多少秒刷新令牌（避免"刚好在过期瞬间发请求"）。 */
const REFRESH_AHEAD_SECONDS = 60

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    // 隐私模式等场景下 localStorage 可能不可用，退化成"总是重新登录"。
    return null
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // 写入失败不致命（同上），内存里的 Pinia 状态仍然可用。
  }
}

function remove(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // 忽略。
  }
}

/** 读取 access 令牌。 */
export function getAccessToken(): string | null {
  return read(KEY_ACCESS)
}

/** 读取 refresh 令牌。 */
export function getRefreshToken(): string | null {
  return read(KEY_REFRESH)
}

/** 读取 access 过期时间（Unix 秒），缺失或非法时返回 `null`。 */
export function getAccessExpiresAt(): number | null {
  const raw = read(KEY_ACCESS_EXPIRES_AT)
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : null
}

/** 保存一对令牌。`expiresAt` 缺失时退化为不做过期预判。 */
export function setTokens(access: string, refresh?: string, expiresAt?: number): void {
  write(KEY_ACCESS, access)
  if (refresh) write(KEY_REFRESH, refresh)
  if (typeof expiresAt === 'number' && Number.isFinite(expiresAt)) {
    write(KEY_ACCESS_EXPIRES_AT, String(expiresAt))
  }
}

/** 只更新 access（刷新令牌未轮换时用）。 */
export function setAccessToken(access: string, expiresAt?: number): void {
  write(KEY_ACCESS, access)
  if (typeof expiresAt === 'number' && Number.isFinite(expiresAt)) {
    write(KEY_ACCESS_EXPIRES_AT, String(expiresAt))
  }
}

/** 清空全部令牌。 */
export function clearTokens(): void {
  remove(KEY_ACCESS)
  remove(KEY_REFRESH)
  remove(KEY_ACCESS_EXPIRES_AT)
}

/**
 * access 是否已过期（或即将过期）。
 *
 * 没有过期时间记录时返回 `false` —— 让请求照发，
 * 由服务端的 401 来兜底，而不是凭空把用户登出。
 */
export function isAccessExpired(): boolean {
  const expiresAt = getAccessExpiresAt()
  if (expiresAt === null) return false
  const nowSeconds = Math.floor(Date.now() / 1000)
  return expiresAt - REFRESH_AHEAD_SECONDS <= nowSeconds
}

/** 是否存有可用于登录的令牌。 */
export function hasTokens(): boolean {
  return getAccessToken() !== null || getRefreshToken() !== null
}
