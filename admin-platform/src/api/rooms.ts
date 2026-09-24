/**
 * 房间管理接口。
 *
 * 对应后端 `apps/rooms/urls.py`：
 *
 * | 方法 | 路径 | 说明 |
 * | --- | --- | --- |
 * | GET  | `rooms/` | 存活房间列表：搜索 / 玩法 / 状态过滤 / 排序 / 分页 |
 * | GET  | `rooms/overview/` | 概览：总数、满座、未满座、24 小时新建 |
 * | GET  | `rooms/<room_id>/` | 详情：配置 + 四个座位 + 预留入口说明 |
 * | POST | `rooms/<room_id>/dissolve/` | **预留**：强制解散（需管理员及以上） |
 *
 * 数据由后端通过**只读数据源**读玩家库 `db_scmj` 的 `t_rooms`：
 * 这张表里只有**尚未销毁**的房间（游戏服销毁房间时会删行），
 * 所以"房间不存在"往往是"已经打完了"，而不是房间号写错了。
 */

import { get, post } from './client'
import type {
  PageResult,
  RoomDetail,
  RoomDissolveResult,
  RoomsOverview,
  RoomState,
  RoomSummary,
} from './types'

/** 列表查询参数（全部可选，后端有默认值）。 */
export interface RoomListQuery {
  /** 房间号 / uuid / 座位上的玩家ID（纯数字），或座位玩家昵称。 */
  keyword?: string
  /** 玩法标识，空串表示全部。 */
  room_type?: string
  /** 座位占用过滤，默认 `all`。 */
  state?: RoomState | 'all'
  /** 排序键，如 `-create_time`（默认）、`-num_of_turns`。 */
  ordering?: string
  page?: number
  page_size?: number
}

/** 房间列表。 */
export function listRooms(query: RoomListQuery = {}): Promise<PageResult<RoomSummary>> {
  return get<PageResult<RoomSummary>>('rooms/', { params: query })
}

/** 概览数字。 */
export function getRoomsOverview(): Promise<RoomsOverview> {
  return get<RoomsOverview>('rooms/overview/')
}

/**
 * 房间详情（房间号或 uuid 都可以）。
 *
 * @param roomRef 6 位房间号，或 `t_rooms.uuid`。
 */
export function getRoom(roomRef: string): Promise<RoomDetail> {
  return get<RoomDetail>(`rooms/${encodeURIComponent(roomRef)}/`)
}

/**
 * 强制解散房间 —— **预留入口**。
 *
 * 后端恒返回 `reserved: true` 与"计划怎么实现"，**不会**真的动房间；
 * 真正生效需要游戏服提供内部接口（见响应里的 `source`）。
 * 前端现在就把调用链走通，接入时后端换实现即可。
 */
export function dissolveRoom(roomRef: string): Promise<RoomDissolveResult> {
  return post<RoomDissolveResult>(`rooms/${encodeURIComponent(roomRef)}/dissolve/`, {})
}
