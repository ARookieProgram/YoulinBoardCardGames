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
  /** 玩家不存在。 */
  PLAYER_NOT_FOUND: 12001,
  /** 该玩家已在封禁中。 */
  PLAYER_ALREADY_BANNED: 12002,
  /** 该玩家当前不在封禁中。 */
  PLAYER_NOT_BANNED: 12003,
  /** 玩家数据源不可用（玩家库连不上）。 */
  PLAYER_SOURCE_UNAVAILABLE: 12004,
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

// ---------------------------------------------------------------- 分页

/**
 * 列表接口的统一分页形状。
 *
 * 与后端 `apps/common/pagination.py` 的 `page_payload()` 一一对应：
 * 玩家列表（只读 SQL 自己分页）与预留端点（空列表）都返回这几个键。
 */
export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ---------------------------------------------------------------- 玩家管理

/** 列表页的封禁状态过滤（与后端 `BAN_STATE_*` 常量一致）。 */
export type PlayerBanState = 'all' | 'banned' | 'normal'

/** 封禁流水的操作类型。 */
export type PlayerBanAction = 'ban' | 'unban'

/** 一条封禁 / 解封流水（后端 `PlayerBan.as_payload()`）。 */
export interface PlayerBanRecord {
  id: number
  action: PlayerBanAction
  /** 操作的中文名，直接用于展示。 */
  action_display: string
  reason: string
  /** 操作人账号快照（管理员被删后依然可读）。 */
  operator_name: string
  /** `YYYY-MM-DD HH:mm:ss`。 */
  created_at: string
  /** 自动解封时间；`null` 表示永久封禁。 */
  expires_at: string | null
}

/** 列表页的一行：玩家只读字段 + 当前封禁状态。 */
export interface PlayerSummary {
  player_id: number
  account: string
  /** 昵称（后端已从 Base64 解码）。 */
  name: string
  headimg: string | null
  lv: number
  exp: number
  /** 金币。 */
  coins: number
  /** 房卡（游戏里扣的就是这个字段）。 */
  gems: number
  /** 当前所在房间号，空串表示不在房间中。 */
  roomid: string
  /** 此刻是否处于封禁中（限时封禁到期后自动为 false）。 */
  banned: boolean
  /** 最新一条流水；从未封禁过时为 `null`。 */
  ban: PlayerBanRecord | null
}

/** 玩家详情：在列表行的基础上多了性别与完整流水。 */
export interface PlayerDetail extends PlayerSummary {
  sex: number | null
  ban_records: PlayerBanRecord[]
}

/** 封禁入参。 */
export interface PlayerBanPayload {
  reason?: string
  /** 封禁时长（小时）；不传或 `null` 表示永久封禁。 */
  duration_hours?: number | null
}

/** 解封入参。 */
export interface PlayerUnbanPayload {
  reason?: string
}

/** 封禁 / 解封的返回。 */
export interface PlayerBanResult {
  player_id: number
  banned: boolean
  ban: PlayerBanRecord
}

/** 列表页顶部的概览数字。 */
export interface PlayersOverview {
  total_players: number
  banned_players: number
}

/**
 * 预留查询入口（对局记录 / 充值记录）的返回。
 *
 * 形状与 `PageResult` 完全一致，只是目前 `items` 恒为空、多了 `reserved` 标记。
 * 后端接上真实数据源后这几个键不变，前端不需要改契约。
 */
export interface PlayerReservedResult extends PageResult<never> {
  /** 恒为 `true`，表示数据源尚未接入。 */
  reserved: true
  player_id: number
  /** 功能标识：`games` / `recharges`。 */
  feature: string
  /** 计划的数据来源说明。 */
  source: string
  /** 给运营看的一句话说明。 */
  message: string
}

