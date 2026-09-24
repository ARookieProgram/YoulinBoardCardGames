/**
 * 玩家管理接口。
 *
 * 对应后端 `apps/players/urls.py`：
 *
 * | 方法 | 路径 | 说明 |
 * | --- | --- | --- |
 * | GET  | `players/` | 列表：搜索 / 封禁状态过滤 / 分页 |
 * | GET  | `players/overview/` | 概览：玩家总数、封禁中人数 |
 * | GET  | `players/<id>/` | 详情 + 封禁流水 |
 * | POST | `players/<id>/ban/` | 封禁（需管理员及以上） |
 * | POST | `players/<id>/unban/` | 解封（需管理员及以上） |
 * | GET  | `players/<id>/games/` | **预留**：对局记录 |
 * | GET  | `players/<id>/recharges/` | **预留**：充值记录 |
 *
 * 玩家数据由后端通过只读数据源读玩家库，前端只认这里的属性名，
 * 不关心它是从哪张表来的。
 */

import { get, post } from './client'
import type {
  PageResult,
  PlayerBanPayload,
  PlayerBanResult,
  PlayerBanState,
  PlayerDetail,
  PlayerReservedResult,
  PlayerSummary,
  PlayerUnbanPayload,
  PlayersOverview,
} from './types'

/** 列表查询参数（全部可选，后端有默认值）。 */
export interface PlayerListQuery {
  /** 账号 / 昵称 / 玩家ID（纯数字时按 ID 精确匹配）。 */
  keyword?: string
  /** 封禁状态过滤，默认 `all`。 */
  ban_state?: PlayerBanState
  /** 排序键，如 `-userid`（默认）、`-gems`、`-coins`。 */
  ordering?: string
  page?: number
  page_size?: number
}

/** 预留入口的分页参数。 */
export interface ReservedQuery {
  page?: number
  page_size?: number
}

/** 玩家列表。 */
export function listPlayers(query: PlayerListQuery = {}): Promise<PageResult<PlayerSummary>> {
  return get<PageResult<PlayerSummary>>('players/', { params: query })
}

/** 概览数字。 */
export function getPlayersOverview(): Promise<PlayersOverview> {
  return get<PlayersOverview>('players/overview/')
}

/** 玩家详情（含封禁流水）。 */
export function getPlayer(playerId: number): Promise<PlayerDetail> {
  return get<PlayerDetail>(`players/${playerId}/`)
}

/** 封禁玩家。 */
export function banPlayer(playerId: number, payload: PlayerBanPayload = {}): Promise<PlayerBanResult> {
  return post<PlayerBanResult>(`players/${playerId}/ban/`, payload)
}

/** 解封玩家。 */
export function unbanPlayer(
  playerId: number,
  payload: PlayerUnbanPayload = {},
): Promise<PlayerBanResult> {
  return post<PlayerBanResult>(`players/${playerId}/unban/`, payload)
}

/**
 * 预留：玩家对局记录。
 *
 * 后端返回空列表 + `reserved: true`；接上数据源后同一个函数直接拿到真数据。
 */
export function listPlayerGames(
  playerId: number,
  query: ReservedQuery = {},
): Promise<PlayerReservedResult> {
  return get<PlayerReservedResult>(`players/${playerId}/games/`, { params: query })
}

/** 预留：玩家充值记录。 */
export function listPlayerRecharges(
  playerId: number,
  query: ReservedQuery = {},
): Promise<PlayerReservedResult> {
  return get<PlayerReservedResult>(`players/${playerId}/recharges/`, { params: query })
}
