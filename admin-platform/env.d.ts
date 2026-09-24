/// <reference types="vite/client" />

/**
 * 本项目用到的环境变量类型声明。
 *
 * 变量定义在 `.env` / `.env.local` / `.env.<mode>` 里，
 * 键名必须以 `VITE_` 开头才会被 Vite 注入到客户端。
 */
interface ImportMetaEnv {
  /** 接口前缀，默认 `/api`（开发期由 Vite 代理到后端）。 */
  readonly VITE_API_BASE_URL?: string
  /** Vite dev server 把 `/api` 代理到哪个后端。 */
  readonly VITE_API_PROXY_TARGET?: string
  /** 页面标题（浏览器标签与登录页共用）。 */
  readonly VITE_APP_TITLE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
