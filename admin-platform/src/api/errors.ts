/**
 * 业务错误：请求已到达后端，后端明确返回了失败。
 *
 * 与"网络层错误"（`NetworkError`）区分开：
 *  - `ApiError` 的 `message` 是后端写好的中文文案，可以直接弹给用户；
 *  - `NetworkError` 只能是"网络异常"这类前端兜底文案。
 */
export class ApiError extends Error {
  /** 后端业务错误码，见 `types.ts` 的 `ErrorCode`。 */
  readonly code: number
  /** HTTP 状态码。 */
  readonly status: number
  /** 附加数据（字段级校验错误等）。 */
  readonly data: unknown

  constructor(code: number, message: string, status: number, data: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.data = data
  }

  /** 是否属于"登录态失效"，调用方据此决定是否跳登录页。 */
  get isUnauthorized(): boolean {
    return this.status === 401
  }
}

/** 网络层错误：请求没拿到响应（断网、后端没起、超时）。 */
export class NetworkError extends Error {
  constructor(message = '网络异常，请检查后端服务是否已启动') {
    super(message)
    this.name = 'NetworkError'
  }
}
