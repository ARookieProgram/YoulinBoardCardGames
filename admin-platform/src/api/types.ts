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
  /** 房间不存在或已结束（房间打完 / 解散后会从库里删掉）。 */
  ROOM_NOT_FOUND: 13001,
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

// ---------------------------------------------------------------- 房间管理

/**
 * 房间状态（后端 `player_source` 由**座位占用**推导）。
 *
 * `playing` 只表示"四个座位都有人"——房间还在 `t_rooms` 里就意味着它还没被销毁。
 */
export type RoomState = 'waiting' | 'playing'

/** 房间里的一个座位（`t_rooms` 的 `user_idN` / `user_nameN` / `user_scoreN`）。 */
export interface RoomSeat {
  seat_index: number
  /** 空座位是 `0`。 */
  player_id: number
  /** 昵称（后端已从 Base64 解码）。 */
  name: string
  icon: string
  score: number
  /** `player_id > 0`。 */
  occupied: boolean
}

/** 房间配置：`t_rooms.base_info` 的 JSON，后端已转成固定键。 */
export interface RoomConf {
  /** 玩法标识（`conf.type` **没有**白名单，客户端传什么就是什么）。 */
  type: string
  /** 底分。 */
  base_score: number
  /** 最大番数。 */
  max_fan: number
  /** 局数上限。 */
  max_games: number
  /** 建房者的玩家 ID。 */
  creator: number
  /** 自摸加成：`0` 加底 / `1` 加番 / `2` 不加。 */
  zimo: number
  /** 点杠花：`0` 点炮 / `1` 自摸。 */
  dianganghua: number
  jiangdui: boolean
  /** 换三张。 */
  hsz: boolean
  menqing: boolean
  tiandihu: boolean
}

/** 列表与详情共用的房间形状（后端 `room_payload`）。 */
export interface RoomSummary {
  /** 6 位房间号（`t_rooms.id`）。 */
  room_id: string
  /** 房间 uuid（主键，排查问题时游戏服日志里是它）。 */
  uuid: string
  type: string
  /** 玩法名（与大厅里玩家看到的一致，未知玩法回退成原始标识）。 */
  type_label: string
  state: RoomState
  seat_count: number
  occupied_seats: number
  /** 创建时间（Unix 秒）。 */
  create_time: number
  /** `YYYY-MM-DD HH:mm:ss`（后端已按 Asia/Shanghai 格式化）。 */
  created_at: string
  /** 已打局数。 */
  num_of_turns: number
  next_button: number
  /** 房间所在游戏服的地址。 */
  ip: string
  port: number
  conf: RoomConf
  seats: RoomSeat[]
}

/**
 * 预留的运维入口说明。
 *
 * 后端用"同一份文案"同时给出详情里的 `actions` 与预留接口的返回，
 * 所以前端只认 `reserved` / `available` / `message` / `source` 这几个键。
 */
export interface RoomReservedAction {
  /** 恒为 `true`：该动作尚未接入。 */
  reserved: true
  /** 恒为 `false`：现在调用它不会真的动房间。 */
  available: boolean
  /** 功能标识：目前只有 `dissolve`。 */
  feature: string
  /** 计划怎么实现（含需要游戏服配合的说明）。 */
  source: string
  /** 给运营看的一句话说明。 */
  message: string
}

/** 房间详情：列表行 + 预留入口的可用性。 */
export interface RoomDetail extends RoomSummary {
  actions: {
    /** 强制解散（预留）。 */
    dissolve: RoomReservedAction
  }
}

/** 强制解散（预留）的返回。 */
export interface RoomDissolveResult extends RoomReservedAction {
  room_id: string
  uuid: string
}

/** 房间列表页顶部的概览数字。 */
export interface RoomsOverview {
  total_rooms: number
  /** 四个座位都有人。 */
  playing_rooms: number
  /** 还有空位。 */
  waiting_rooms: number
  created_last_24h: number
}

