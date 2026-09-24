/**
 * 时间展示的小工具。
 *
 * 后端返回的时间是 `YYYY-MM-DD HH:mm:ss`（`settings.REST_FRAMEWORK` 里
 * 指定了 `DATETIME_FORMAT`），已经是本地时区（`Asia/Shanghai`），
 * 所以这里**不做时区转换**，只做空值兜底。
 */

/** 展示时间；空值或非法值时返回占位符。 */
export function formatDateTime(value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback
  const text = value.trim()
  if (text === '') return fallback
  return text
}

/** 展示 IP；为空时返回占位符。 */
export function formatIp(value: string | null | undefined, fallback = '—'): string {
  if (!value) return fallback
  return value
}
