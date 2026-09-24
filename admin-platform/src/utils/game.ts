/**
 * 对局记录里"展示口径"相关的小工具。
 *
 * 两层分工与房间管理一致：
 *
 *  - **后端**给原始值 + 它自己拥有的展示名（`action_label` / `tile_label` /
 *    `tile_code` / `type_label` / `identity_note`）；
 *  - **前端**只用这些字段做排版与配色，**不重新定义玩法口径**
 *    （牌面与动作名的权威实现是 `apps/games/decoding.py`）。
 *
 * 对局记录**只读归档表** `t_games_archive`，所以这里没有"来源（进行中 / 已结束）"
 * 这类选项：后台看到的每一局都是打完的终局。
 *
 * 这样改文案或换配色不会影响接口契约，而玩法口径只有一处定义。
 */

import type { GameAction, GameActionSummary, GameSeat, GameSummary } from '@/api/types'
import { ROOM_TYPE_OPTIONS } from '@/utils/room'

/** 玩法下拉项（与房间管理共用同一份口径）。 */
export const GAME_TYPE_OPTIONS = ROOM_TYPE_OPTIONS

/** 排序下拉项（与后端 `GAME_ORDERING_CHOICES` 一致）。 */
export const GAME_ORDERING_OPTIONS: readonly { value: string; label: string }[] = [
  { value: '-create_time', label: '开局时间（新→旧）' },
  { value: 'create_time', label: '开局时间（旧→新）' },
  { value: '-game_index', label: '局号（大→小）' },
  { value: 'game_index', label: '局号（小→大）' },
]

/** 身份来源 → 标签颜色（未知要显眼一点，运营才知道看不到昵称的原因）。 */
const IDENTITY_TAG_TYPES: Record<string, 'success' | 'info' | 'warning'> = {
  rooms: 'success',
  history: 'info',
  unknown: 'warning',
}

/** 身份来源 → 标签颜色。 */
export function identityTagType(source: string): 'success' | 'info' | 'warning' {
  return IDENTITY_TAG_TYPES[source] ?? 'info'
}

/** 动作编号 → 标签颜色（出牌/摸牌是中性，碰杠是蓝，胡是红）。 */
export function actionTagType(action: number): 'info' | 'primary' | 'warning' | 'success' | 'danger' {
  if (action === 1 || action === 2) return 'info'
  if (action === 3 || action === 4) return 'primary'
  if (action === 5) return 'danger'
  if (action === 6) return 'success'
  return 'info'
}

/** 牌面 → CSS 类名（按花色上色：筒 / 条 / 万）。 */
export function tileSuitClass(tileSuit: number | null | undefined): string {
  if (tileSuit === 0) return 'tile tile--dot'
  if (tileSuit === 1) return 'tile tile--bamboo'
  if (tileSuit === 2) return 'tile tile--character'
  return 'tile tile--unknown'
}

/** 一个座位的展示名（后端已经算过 `display_name`，这里只做兜底）。 */
export function seatDisplayName(seat: {
  display_name?: string
  name?: string
  seat_index: number
}): string {
  return seat.display_name || seat.name || `座位${seat.seat_index}`
}

/** 座位 + 本局得分（列表里挤在一格里展示，赢家标出来）。 */
export function seatScoreText(seat: GameSeat): string {
  const name = seatDisplayName(seat)
  const score = seat.score > 0 ? `+${seat.score}` : String(seat.score)
  const banker = seat.is_banker ? '(庄)' : ''
  return `${name}${banker} ${score}`
}

/** 四个座位的本局得分摘要（列表的"四家"一列）。 */
export function seatScoreSummary(game: GameSummary): string {
  return game.seats.map(seatScoreText).join('  ')
}

/** 动作统计摘要：`出牌 12 · 摸牌 13 · 碰 1 …`（只列出非 0 的项）。 */
export function actionSummaryText(summary: GameActionSummary): string {
  const items: [string, number][] = [
    ['出牌', summary.chupai],
    ['摸牌', summary.mopai],
    ['碰', summary.peng],
    ['杠', summary.gang],
    ['胡', summary.hu],
    ['自摸', summary.zimo],
  ]
  const parts = items.filter(([, value]) => value > 0).map(([label, value]) => `${label} ${value}`)
  return parts.length > 0 ? parts.join(' · ') : '无动作流水'
}

/** 一局的标题：`第 3 局`（游戏服的局号从 0 开始）。 */
export function roundText(game: { round: number; game_index: number }): string {
  return `第 ${game.round} 局`
}

/** 房间标识：房间号优先，缺失时回退 uuid（正常情况两个都有）。 */
export function roomRefText(game: { room_id: string; room_uuid: string }): string {
  return game.room_id || game.room_uuid
}

/** 谁胡了（从动作流水里推，用于列表一眼看结果）。 */
export function winnerText(game: GameSummary): string {
  return game.seats
    .filter((seat) => seat.score > 0)
    .map((seat) => `${seatDisplayName(seat)} ${seat.score > 0 ? '+' : ''}${seat.score}`)
    .join('、')
}

/** 动作 + 牌面 + "被谁拿走"的完整描述（时间线表格用）。 */
export function actionDetailText(action: GameAction): string {
  const taken = action.taken_by ? `（被 ${action.taken_by.name} ${action.taken_by.action_label}）` : ''
  return `${action.action_label} ${action.tile_label}${taken}`
}
