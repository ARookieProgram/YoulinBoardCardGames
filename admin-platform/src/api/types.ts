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
  /** 对局记录不存在（每结束一局才写库；还没打完 / 从未开局时查不到）。 */
  GAME_NOT_FOUND: 14001,
  /** 管理员不存在（刚被另一位超级管理员删掉时会遇到）。 */
  ADMIN_NOT_FOUND: 15001,
  /** 管理员账号名已被占用（大小写不敏感判重）。 */
  ADMIN_USERNAME_TAKEN: 15002,
  /** 邮箱已被其他管理员占用。 */
  ADMIN_EMAIL_TAKEN: 15003,
  /** 不能对自己执行该操作（停用 / 删除 / 给自己降级）。 */
  ADMIN_SELF_OPERATION: 15004,
  /** 不能停用、删除或降级最后一个启用中的超级管理员。 */
  ADMIN_LAST_SUPER: 15005,
  /** 本人改口令时原密码不正确。 */
  ADMIN_OLD_PASSWORD: 15006,
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
  /**
   * **权限判断用的角色**（后端 `effective_role`）。
   *
   * 与 `role` 的区别：`is_superuser=true` 的历史行一律算超级管理员，
   * 这时 `effective_role` 是 `super_admin`，而 `role` 可能还停在旧值。
   * 前端判权限用这个字段，展示原始取值用 `role`。
   */
  effective_role: AdminRole
  status: AdminStatus
  status_display: string
  /** 备注（为什么给他开这个号）。 */
  remark: string
  is_superuser: boolean
  /** `YYYY-MM-DD HH:mm:ss`，从未登录时为 `null`。 */
  last_login: string | null
  last_login_ip: string | null
  created_at: string
  updated_at: string
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
 * 预留查询入口（充值记录）的返回。
 *
 * 形状与 `PageResult` 完全一致，只是目前 `items` 恒为空、多了 `reserved` 标记。
 * 后端接上真实数据源后这几个键不变，前端不需要改契约。
 *
 * 注意：**对局记录已经不是预留入口了**，它落地成了独立的 `/api/games/`
 * （见本文件下半部分与 `api/games.ts`）。
 */
export interface PlayerReservedResult extends PageResult<never> {
  /** 恒为 `true`，表示数据源尚未接入。 */
  reserved: true
  player_id: number
  /** 功能标识：目前只有 `recharges`。 */
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

// ---------------------------------------------------------------- 对局记录

/**
 * 对局来自哪张表。
 *
 * 游戏服每开一局就往 `t_games` 写一行，房间打完 / 被解散时整批搬进
 * `t_games_archive` 并删掉在局行（见 `player_source.GAME_TABLE_SOURCES`）。
 */
export type GameSource = 'archive' | 'live'

/** 对局里的玩家身份是从哪儿查到的（与后端 `GAME_IDENTITY_*` 一致）。 */
export type GameIdentitySource = 'rooms' | 'history' | 'unknown'

/**
 * 出牌流水的动作编号（与 `gamemgr` 顶部常量、客户端 `ReplayMgr` 逐字一致）。
 */
export const GameActionCode = {
  CHUPAI: 1,
  MOPAI: 2,
  PENG: 3,
  GANG: 4,
  HU: 5,
  ZIMO: 6,
} as const

/** 六个动作分类的计数（后端 `action_summary`）。 */
export interface GameActionSummary {
  chupai: number
  mopai: number
  peng: number
  gang: number
  hu: number
  zimo: number
}

/**
 * 一局里的一个座位。
 *
 * * `score` —— **本局**得分（来自 `t_games.result`，一定有）；
 * * `room_score` —— **房间累计**得分（存活房间来自 `t_rooms`，已销毁房间来自
 *   `t_users.history`）；身份查不到时是 `null`（不是 0，0 会被误读成"打平"）。
 */
export interface GameSeat {
  seat_index: number
  player_id: number
  name: string
  /** 昵称 → `玩家#ID` → `座位N`（后端算好的展示名）。 */
  display_name: string
  icon: string
  occupied: boolean
  /** 本局庄家（每局可能不同，来自 `base_info.button`）。 */
  is_banker: boolean
  score: number
  room_score?: number | null
}

/** 列表与详情共用的对局行（后端 `game_row_payload`）。 */
export interface GameSummary {
  /** 房间 uuid：**详情接口认的主键**（`t_games` 里没有房间号）。 */
  room_uuid: string
  /** 6 位房间号；由存活房间表、战绩快照或 uuid 反推得到。 */
  room_id: string
  /** 游戏服的局号，从 0 开始。 */
  game_index: number
  /** 给运营看的"第几局"（`game_index + 1`）。 */
  round: number
  source: GameSource
  /** 中文来源名（进行中 / 已结束）。 */
  source_label: string
  type: string
  /** 玩法名（与大厅一致，未知玩法回退成原始标识）。 */
  type_label: string
  /** 本局庄家的座位号。 */
  button: number
  create_time: number
  /** `YYYY-MM-DD HH:mm:ss`（后端已按 Asia/Shanghai 格式化）。 */
  created_at: string
  /** 四个座位的本局得分（与 `seats[].score` 同源）。 */
  result: number[]
  seats: GameSeat[]
  seat_count: number
  identity_source: GameIdentitySource
  /** 身份来源的中文说明（给运营看的）。 */
  identity_note: string
  /** 房间是否还在 `t_rooms` 里（没被销毁）。 */
  live: boolean
  has_action_records: boolean
  action_count: number
  action_summary: GameActionSummary
  /** 有开局快照或流水，可以点进详情。 */
  detail_available: boolean
}

/** 出牌时间线里的一个动作（后端 `timeline` 元素）。 */
export interface GameAction {
  /** 从 1 开始的序号（全局时间线里的第几个动作）。 */
  seq: number
  seat_index: number
  /** 动作编号，见 `GameActionCode`。 */
  action: number
  /** 中文动作名（出牌 / 摸牌 / 碰 / 杠 / 胡 / 自摸）。 */
  action_label: string
  /** 短动作名（打 / 摸 / 碰 / 杠 / 胡 / 自摸）。 */
  action_short: string
  /** 牌 id（0~8 筒 / 9~17 条 / 18~26 万）；未知是 -1。 */
  tile: number
  /** 中文牌面（`五筒` / `一万`）。 */
  tile_label: string
  /** 客户端图集名（`dot_5` / `character_1`）。 */
  tile_code: string
  tile_suit: number | null
  /** 详情时间线才有：`座位0`。 */
  seat_label?: string
  /** 详情时间线才有：座位上玩家的 ID / 展示名。 */
  player_id?: number
  seat_name?: string
  is_banker?: boolean
  /** 详情时间线才有：这张打出的牌被谁拿走（碰 / 杠 / 胡）。 */
  taken_by?: {
    seat_index: number
    name: string
    action: number
    action_label: string
  }
}

/** 单个玩家的动作视图（后端 `seat_actions`）——**他这一局打了什么**。 */
export interface GameSeatActions extends GameSeat {
  actions: GameAction[]
  action_count: number
  summary: GameActionSummary
  /** 打出的牌（按顺序，带"被谁拿走"标注）。 */
  folds: GameAction[]
  folds_text: string
  drawn: GameAction[]
  drawn_text: string
  pengs: GameAction[]
  pengs_text: string
  gangs: GameAction[]
  gangs_text: string
  hued: boolean
  /** 是否自摸胡。 */
  zimo: boolean
  win_tiles: GameAction[]
  win_text: string
}

/** 开局手牌（后端 `initial_hands`）。 */
export interface GameInitialHand {
  seat_index: number
  player_id: number
  name: string
  tiles: {
    tile: number
    tile_label: string
    tile_code: string
    tile_suit: number | null
  }[]
  tile_count: number
  tiles_text: string
}

/** 牌墙消耗（后端 `wall`）。 */
export interface GameWall {
  /** 洗好的张数（108）。 */
  size: number
  /** 已发出的张数（起手 53）。 */
  dealt: number
  /** 被摸走的张数（时间线里 `ACTION_MOPAI` 的条数）。 */
  drawn: number
  /** 还剩多少张没摸。 */
  remaining: number
  /** 洗好的牌墙（id 序列，排查问题时用）。 */
  tiles: number[]
}

/** 单局详情（后端 `game_detail_payload`）：在列表行的基础上多出出牌记录。 */
export interface GameDetail extends GameSummary {
  /** 解析流水时的警告（脏数据不报错，只提示）。 */
  warnings: string[]
  /** 全局动作时间线（按发生顺序）。 */
  timeline: GameAction[]
  /** 每个玩家自己的动作与出牌顺序。 */
  seat_actions: GameSeatActions[]
  initial_hands: GameInitialHand[]
  initial_hands_text: string[]
  wall: GameWall
}

/** 房间级座位：只有累计得分，没有本局得分。 */
export interface RoomGameSeat {
  seat_index: number
  player_id: number
  name: string
  display_name: string
  icon: string
  occupied: boolean
  is_banker: boolean
  room_score: number | null
}

/** 一个房间的全部对局（后端 `room_games_payload`）。 */
export interface RoomGameList {
  room_uuid: string
  room_id: string
  type: string
  type_label: string
  live: boolean
  identity_source: GameIdentitySource
  identity_note: string
  seats: RoomGameSeat[]
  game_count: number
  games: GameSummary[]
}

/** 玩家战绩里的座位：在普通座位之上标出"哪一位是我"。 */
export interface PlayerGameSeat extends GameSeat {
  is_me: boolean
}

/** 玩家的一条房间战绩（后端 `player_game_payload`，来自 `t_users.history`）。 */
export interface PlayerGameRecord {
  room_uuid: string
  room_id: string
  create_time: number
  created_at: string
  seats: PlayerGameSeat[]
  seat_count: number
  /** 该玩家坐在几号位；榜单里找不到时是 `null`。 */
  my_seat: number | null
  /** 该玩家在这局的房间累计得分。 */
  my_score: number
  /** 按房间累计得分排的名次（并列同名次）。 */
  my_rank: number | null
  /** 该房间在 `t_games` / `t_games_archive` 里的局数。 */
  game_count: number
  games_available: boolean
}

/** 玩家对局列表的返回：分页形状 + 一致性说明。 */
export interface PlayerGamesResult extends PageResult<PlayerGameRecord> {
  player_id: number
  /** 玩家侧战绩快照的上限（游戏服只保留最近 10 场）。 */
  max_entries: number
  /** 给运营看的说明（为什么只有最近这些场）。 */
  note: string
}

/** 对局记录列表页顶部的概览数字。 */
export interface GamesOverview {
  total_games: number
  archived_games: number
  live_games: number
  games_last_24h: number
  rooms_last_24h: number
}

// ---------------------------------------------------------------- 管理员账号管理

/** 列表页的角色过滤（`all` 来自后端 `ADMIN_ROLE_ALL`）。 */
export type AdminRoleFilter = 'all' | AdminRole

/** 列表页的状态过滤（`all` 来自后端 `ADMIN_STATUS_ALL`）。 */
export type AdminStatusFilter = 'all' | AdminStatus

/** 管理员列表页顶部的概览数字。 */
export interface AdminsOverview {
  total_admins: number
  active_admins: number
  disabled_admins: number
  /** 按 `effective_role` 口径统计（含 `is_superuser` 的历史行）。 */
  super_admins: number
}

/** 新建管理员的入参。新建的账号**一律启用**，所以没有 `status`。 */
export interface AdminCreatePayload {
  username: string
  nickname?: string
  email: string
  password: string
  role: AdminRole
  remark?: string
}

/**
 * 改资料的入参。
 *
 * 没有 `username`（账号名不可改）与 `password`（走重置口令接口）；
 * 状态也不在这里改，走 `setAdminStatus`。
 */
export interface AdminUpdatePayload {
  nickname?: string
  email?: string
  role?: AdminRole
  remark?: string
}

/** 启用 / 停用的入参。 */
export interface AdminStatusPayload {
  status: AdminStatus
}

/** 超级管理员重置他人口令的入参。 */
export interface AdminPasswordPayload {
  new_password: string
}

/** 本人改口令的入参（必须带原口令）。 */
export interface SelfPasswordPayload {
  old_password: string
  new_password: string
}

/** 重置口令 / 改口令的返回。 */
export interface AdminPasswordResult {
  id: number
  username: string
  /** 本次被吊销的 refresh 令牌数；大于 0 表示该账号其它设备需要重新登录。 */
  revoked_tokens: number
}

/** 删除管理员的返回。 */
export interface AdminDeleteResult {
  id: number
  username: string
}

