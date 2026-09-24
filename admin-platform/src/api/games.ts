/**
 * 对局记录接口。
 *
 * 对应后端 `apps/games/urls.py`：
 *
 * | 方法 | 路径 | 说明 |
 * | --- | --- | --- |
 * | GET | `games/` | 对局列表：关键字 / 玩法 / 来源 / 日期 / 排序 / 分页 |
 * | GET | `games/overview/` | 概览：总局数、已结束、进行中、最近 24 小时 |
 * | GET | `games/rooms/<房间号或uuid>/` | 一个房间的全部对局 + 四个座位 |
 * | GET | `games/rooms/<房间号或uuid>/<局号>/` | **单局详情：四家出牌记录** |
 * | GET | `games/players/<玩家ID>/` | 某个玩家的房间战绩（最多最近 10 场） |
 *
 * 数据由后端通过**只读数据源**读玩家库 `db_scmj` 的 `t_games` / `t_games_archive`。
 * 三条口径上的坑（后端 README §6.7 有完整说明）：
 *
 *  1. **每结束一局才写一行**：房间刚建好、第一局还在打时查不到，`14001` 就是这个意思；
 *  2. **对局表里没有玩家**：身份靠存活房间表或 `t_users.history` 反查，查不到时
 *     座位显示成 `座位N`（`identity_source === 'unknown'`）；
 *  3. **对局表里也没有房间号**：房间号由后端从 uuid 反推（uuid = 13 位毫秒 + 6 位房间号），
 *     所以列表里一定看得到房间号。
 *
 * `room_uuid` 是**唯一可靠的主键**：详情接口尽量都用它（房间号也能用，但后端要多查一次）。
 */

import { get } from './client'
import type {
  GameDetail,
  GameSource,
  GamesOverview,
  GameSummary,
  PageResult,
  PlayerGamesResult,
  RoomGameList,
} from './types'

/** 列表查询参数（全部可选，后端有默认值）。 */
export interface GameListQuery {
  /** 房间 uuid / 房间号 / 玩家ID / 玩家昵称。 */
  keyword?: string
  /** 玩法标识，空串表示全部。 */
  game_type?: string
  /** 来源：进行中 / 已结束 / 全部（默认 `all`）。 */
  source?: GameSource | 'all'
  /** 起始日期（`YYYY-MM-DD`，含）。 */
  date_from?: string
  /** 结束日期（`YYYY-MM-DD`，含）。 */
  date_to?: string
  /** 排序键，如 `-create_time`（默认）、`-game_index`。 */
  ordering?: string
  page?: number
  page_size?: number
}

/** 对局列表。 */
export function listGames(query: GameListQuery = {}): Promise<PageResult<GameSummary>> {
  return get<PageResult<GameSummary>>('games/', { params: query })
}

/** 概览数字。 */
export function getGamesOverview(): Promise<GamesOverview> {
  return get<GamesOverview>('games/overview/')
}

/**
 * 一个房间的全部对局。
 *
 * @param roomRef 6 位房间号或 `t_rooms.uuid`（uuid 更快、也一定找得到）。
 */
export function getRoomGames(roomRef: string): Promise<RoomGameList> {
  return get<RoomGameList>(`games/rooms/${encodeURIComponent(roomRef)}/`)
}

/**
 * 单局详情（**出牌记录**）。
 *
 * @param roomRef 6 位房间号或 uuid。
 * @param gameIndex 游戏服的局号（从 0 开始；界面上的"第 N 局"是它 +1）。
 */
export function getGameDetail(roomRef: string, gameIndex: number): Promise<GameDetail> {
  return get<GameDetail>(`games/rooms/${encodeURIComponent(roomRef)}/${gameIndex}/`)
}

/** 某个玩家的房间战绩（来自 `t_users.history`，最多最近 10 场）。 */
export function listPlayerGames(
  playerId: number,
  query: { page?: number; page_size?: number } = {},
): Promise<PlayerGamesResult> {
  return get<PlayerGamesResult>(`games/players/${playerId}/`, { params: query })
}
