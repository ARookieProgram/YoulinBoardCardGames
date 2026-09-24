/**
 * 房间管理里"展示口径"相关的小工具。
 *
 * 两层分工：
 *
 *  - **后端**给原始值（`conf.zimo` 是 `0/1/2`、`state` 是 `waiting/playing`），
 *    外加它自己拥有的展示名（`type_label`，与大厅里玩家看到的一致）；
 *  - **前端**负责把选项型枚举翻成中文（下表的 `ZIMO_LABELS` / `DIANGANGHUA_LABELS`）。
 *
 * 为什么不全放后端：这些字符串是**界面文案**，改文案不该动接口契约；
 * 为什么玩法名放后端：`type` 与大厅单选项的对应关系属于数据口径，
 * 后端已经在 `apps/players/player_source.py` 里注释了依据。
 */

import type { RoomConf, RoomSeat, RoomState, RoomSummary } from '@/api/types'

/** 玩法下拉项（与后端 `player_source.ROOM_TYPE_LABELS` 的键一致）。 */
export const ROOM_TYPE_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'xzdd', label: '血战到底' },
  { value: 'xlch', label: '血流成河' },
]

/** 状态下拉项（与后端 `ROOM_STATE_CHOICES` 一致）。 */
export const ROOM_STATE_OPTIONS: readonly { value: string; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'waiting', label: '未满座' },
  { value: 'playing', label: '已满座' },
]

/** 排序下拉项（与后端 `ROOM_ORDERING_CHOICES` 一致）。 */
export const ROOM_ORDERING_OPTIONS: readonly { value: string; label: string }[] = [
  { value: '-create_time', label: '创建时间（新→旧）' },
  { value: 'create_time', label: '创建时间（旧→新）' },
  { value: '-num_of_turns', label: '已打局数（多→少）' },
  { value: 'num_of_turns', label: '已打局数（少→多）' },
]

/**
 * 自摸加成的中文名。
 *
 * 口径来自服务端结算分支（`gamemgr_xzdd` 的 `if game.conf.zimo == 0` / `== 1`）
 * 与大厅单选项的顺序：`0` 加底、`1` 加番，`2` 不加（界面上没有这个选项）。
 */
const ZIMO_LABELS: Record<number, string> = {
  0: '自摸加底',
  1: '自摸加番',
  2: '不加',
}

/** 点杠花的中文名（`conf.dianganghua == 1` 表示算自摸）。 */
const DIANGANGHUA_LABELS: Record<number, string> = {
  0: '点杠花（点炮）',
  1: '点杠花（自摸）',
}

/** 自摸加成的展示名；不认识的取值按原样显示，不猜。 */
export function zimoLabel(value: number): string {
  return ZIMO_LABELS[value] ?? `未知（${value}）`
}

/** 点杠花的展示名；不认识的取值按原样显示。 */
export function dianganghuaLabel(value: number): string {
  return DIANGANGHUA_LABELS[value] ?? `未知（${value}）`
}

/** 状态展示名。 */
export function roomStateLabel(state: RoomState): string {
  return state === 'playing' ? '已满座' : '未满座'
}

/** 状态标签颜色。 */
export function roomStateTagType(state: RoomState): 'success' | 'warning' {
  return state === 'playing' ? 'success' : 'warning'
}

/** 玩法展示名：优先用后端的 `type_label`，未知玩法回退成原始标识。 */
export function roomTypeLabel(room: RoomSummary): string {
  return room.type_label || room.type || '—'
}

/** 单个座位的展示名（空座位给占位符，机器人也有昵称）。 */
export function seatName(seat: RoomSeat): string {
  if (!seat.occupied) return '空座'
  return seat.name || `#${seat.player_id}`
}

/** 四个座位的摘要（列表页挤在一列里展示）。 */
export function seatSummary(room: RoomSummary): string {
  const names = room.seats.filter((seat) => seat.occupied).map(seatName)
  return names.length > 0 ? names.join('、') : '—'
}

/** 座位占用：`已坐/总座位`。 */
export function seatUsage(room: RoomSummary): string {
  return `${room.occupied_seats}/${room.seat_count}`
}

/** 已打局数：`已打/上限`（上限来自房间配置）。 */
export function turnUsage(room: RoomSummary): string {
  const maxGames = room.conf.max_games
  return maxGames > 0 ? `${room.num_of_turns}/${maxGames}` : String(room.num_of_turns)
}

/** 房间所在游戏服的地址。 */
export function serverAddr(room: RoomSummary): string {
  if (!room.ip) return '—'
  return `${room.ip}:${room.port}`
}

/** 房间开启的玩法开关（列表页一眼看清开了哪些规则）。 */
export function confFlags(conf: RoomConf): string[] {
  const flags: string[] = []
  if (conf.hsz) flags.push('换三张')
  if (conf.jiangdui) flags.push('将对')
  if (conf.menqing) flags.push('门清中张')
  if (conf.tiandihu) flags.push('天地胡')
  return flags
}
