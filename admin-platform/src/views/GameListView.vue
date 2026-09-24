<script setup lang="ts">
/**
 * 对局记录（管理平台的第三块只读业务）。
 *
 * 页面能力：
 *  1. **对局列表**——按关键字（房间 uuid / 房间号 / 玩家ID / 玩家昵称）、玩法、
 *     来源（进行中 / 已结束）、开局日期区间过滤，可排序、分页；
 *  2. **概览**——总局数、已结束、进行中、最近 24 小时的对局与房间数；
 *  3. **出牌记录**——点某一局的"出牌记录"，看**这一局每个玩家打了什么**：
 *     全局时间线（第几步、谁、什么动作、哪张牌、这张牌被谁碰/杠/胡）+
 *     分座位的出牌顺序 + 开局手牌与牌墙消耗；
 *  4. **房间维度**——点"本房间对局"看这个房间的全部对局（打完的房间照样能查）；
 *  5. **玩家维度**——玩家详情抽屉的「对局记录」会跳到本页并带上 `?player_id=`，
 *     这里展示该玩家最近 10 场的房间战绩。
 *
 * 数据来自玩家库 `db_scmj` 的 `t_games` / `t_games_archive`（只读）。三条口径：
 *
 *  * **每结束一局才写一行**：房间刚建、第一局还在打时查不到（`14001`）；
 *  * **对局表里没有玩家**：身份靠存活房间表或 `t_users.history` 反查，
 *    查不到时显示成 `座位N`（`identity_source === 'unknown'`）；
 *  * **对局表里也没有房间号**：后台从 uuid 反推（uuid = 13 位毫秒 + 6 位房间号），
 *    所以列表里一定看得到房间号。
 *
 * 本页**只有读**：对局是历史数据，没有任何写入口。
 */

import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getGamesOverview, listGames } from '@/api/games'
import { ApiError } from '@/api/errors'
import { ErrorCode } from '@/api/types'
import type {
  GameSource,
  GameSummary,
  GamesOverview,
  PageResult,
} from '@/api/types'
import {
  GAME_ORDERING_OPTIONS,
  GAME_SOURCE_OPTIONS,
  GAME_TYPE_OPTIONS,
  actionSummaryText,
  identityTagType,
  roundText,
  seatDisplayName,
  sourceTagType,
} from '@/utils/game'
import GameDetailDrawer from '@/components/GameDetailDrawer.vue'
import PlayerGamesTable from '@/components/PlayerGamesTable.vue'
import RoomGamesDrawer from '@/components/RoomGamesDrawer.vue'

const route = useRoute()
const router = useRouter()

/** 查询条件。 */
const query = reactive({
  keyword: '',
  game_type: '',
  source: 'all' as GameSource | 'all',
  ordering: '-create_time',
  /** `[起始, 结束]`，`null` 表示不限（Element Plus 的 daterange 形状，清空时会置 `null`）。 */
  dateRange: null as string[] | null,
})

const page = ref(1)
const pageSize = ref(20)

/** 列表结果。 */
const result = ref<PageResult<GameSummary>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  pages: 0,
})
const loading = ref(false)

/** 概览数字；玩家库不可用时保持 `null` 并给出提示。 */
const overview = ref<GamesOverview | null>(null)
const sourceError = ref('')

/** 玩家维度：`?player_id=` 时展示该玩家的房间战绩。 */
const playerId = ref<number | null>(null)

/** 两个抽屉。 */
const roomDrawerVisible = ref(false)
const roomDrawerRef = ref<string | null>(null)
const detailVisible = ref(false)
const detailRoomRef = ref<string | null>(null)
const detailGameIndex = ref<number | null>(null)

/** 概览卡片。 */
const overviewCards = computed(() => [
  {
    label: '对局总数',
    value: overview.value ? String(overview.value.total_games) : '—',
    tip: 't_games + t_games_archive（每结束一局一行）',
  },
  {
    label: '已结束',
    value: overview.value ? String(overview.value.archived_games) : '—',
    tip: 't_games_archive：房间已销毁，数据长期保留',
  },
  {
    label: '进行中',
    value: overview.value ? String(overview.value.live_games) : '—',
    tip: 't_games：房间还在玩家手里',
  },
  {
    label: '最近 24 小时',
    value: overview.value
      ? `${overview.value.games_last_24h} 局 / ${overview.value.rooms_last_24h} 房间`
      : '—',
    tip: '按本局开始时间统计',
  },
])

/** 统一错误提示。 */
function reportError(error: unknown, fallback: string): void {
  if (error instanceof ApiError) {
    ElMessage.error(error.message)
    // 对局数据与玩家 / 房间数据走**同一条**只读数据源，所以后端复用 12004。
    if (error.code === ErrorCode.PLAYER_SOURCE_UNAVAILABLE) {
      sourceError.value = error.message
    }
    return
  }
  ElMessage.error(fallback)
}

/** 拉列表。 */
async function loadGames(): Promise<void> {
  loading.value = true
  try {
    result.value = await listGames({
      keyword: query.keyword.trim(),
      game_type: query.game_type,
      source: query.source,
      date_from: query.dateRange?.[0] ?? '',
      date_to: query.dateRange?.[1] ?? '',
      ordering: query.ordering,
      page: page.value,
      page_size: pageSize.value,
    })
    sourceError.value = ''
  } catch (error) {
    result.value = { items: [], total: 0, page: page.value, page_size: pageSize.value, pages: 0 }
    reportError(error, '对局列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 拉概览（失败不阻塞列表）。 */
async function loadOverview(): Promise<void> {
  try {
    overview.value = await getGamesOverview()
  } catch (error) {
    overview.value = null
    reportError(error, '概览数据加载失败')
  }
}

/** 条件变化后回到第一页再查。 */
function handleSearch(): void {
  page.value = 1
  void loadGames()
}

/** 重置查询条件（保留玩家维度由"关闭玩家筛选"单独处理）。 */
function handleReset(): void {
  query.keyword = ''
  query.game_type = ''
  query.source = 'all'
  query.ordering = '-create_time'
  query.dateRange = null
  page.value = 1
  pageSize.value = 20
  void loadGames()
}

/** 打开"出牌记录"抽屉。 */
function openDetail(roomUuid: string, gameIndex: number): void {
  detailRoomRef.value = roomUuid
  detailGameIndex.value = gameIndex
  detailVisible.value = true
}

/** 打开"本房间对局"抽屉。 */
function openRoom(roomRef: string): void {
  roomDrawerRef.value = roomRef
  roomDrawerVisible.value = true
}

/** 从列表行打开出牌记录。 */
function handleRowDetail(game: GameSummary): void {
  openDetail(game.room_uuid, game.game_index)
}

/** 从"房间对局"抽屉里打开某一局的出牌记录（抽屉叠在它上面，关掉就回到房间列表）。 */
function handleOpenGame(payload: { roomUuid: string; gameIndex: number }): void {
  openDetail(payload.roomUuid, payload.gameIndex)
}

/** 从"玩家对局"面板打开某个房间的对局列表。 */
function handleOpenRoomFromPlayer(payload: { roomRef: string }): void {
  openRoom(payload.roomRef)
}

/** 关闭玩家维度（同时把 URL 上的 `player_id` 去掉，刷新后不会又冒出来）。 */
function clearPlayerFilter(): void {
  playerId.value = null
  const next = { ...route.query }
  delete next.player_id
  void router.replace({ query: next })
}

/** 从 URL 上取深链参数：`player_id` / `room` / `game`。 */
function applyQuery(): void {
  const rawPlayer = route.query.player_id
  const player = typeof rawPlayer === 'string' ? Number.parseInt(rawPlayer, 10) : Number.NaN
  playerId.value = Number.isFinite(player) && player > 0 ? player : null

  const rawRoom = route.query.room
  const room = typeof rawRoom === 'string' ? rawRoom : ''
  const rawGame = route.query.game
  const game = typeof rawGame === 'string' ? Number.parseInt(rawGame, 10) : Number.NaN

  if (room !== '') {
    if (Number.isFinite(game) && game >= 0) {
      openDetail(room, game)
    } else {
      openRoom(room)
    }
  }
  // 深链里带的房间号顺手填进搜索框，运营一眼知道自己在看哪个房间。
  if (room !== '' && query.keyword === '') {
    query.keyword = room
  }
}

/** URL 变化（例如从玩家页跳过来）时重新应用深链参数。 */
watch(() => route.query, applyQuery)

onMounted(async () => {
  applyQuery()
  await Promise.all([loadGames(), loadOverview()])
})
</script>

<template>
  <div class="page-container">
    <!-- 概览 -->
    <el-row :gutter="16">
      <el-col v-for="card in overviewCards" :key="card.label" :xs="12" :sm="6">
        <el-card shadow="never" class="overview-card">
          <div class="overview-card__label">{{ card.label }}</div>
          <div class="overview-card__value">{{ card.value }}</div>
          <div class="overview-card__tip">{{ card.tip }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      v-if="sourceError"
      type="error"
      show-icon
      :closable="false"
      title="对局数据源不可用"
      :description="`${sourceError}（请检查管理平台到玩家库 db_scmj 的连接配置）`"
    />

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="只读的历史对局"
      description="数据来自玩家库 t_games / t_games_archive：游戏服每结束一局写一行，房间打完或解散时整批归档。对局表里只有座位号，没有玩家与房间号——玩家身份靠存活房间表或玩家战绩快照反查，房间号由 uuid 反推。"
    />

    <!-- 玩家维度（从玩家详情跳过来时） -->
    <el-card v-if="playerId !== null" shadow="never">
      <template #header>
        <div class="card-header">
          <span>玩家 #{{ playerId }} 的最近对局</span>
          <el-button link type="primary" size="small" @click="clearPlayerFilter">
            关闭玩家筛选
          </el-button>
        </div>
      </template>
      <PlayerGamesTable
        :player-id="playerId"
        :auto-load="true"
        @open-room="handleOpenRoomFromPlayer"
      />
    </el-card>

    <!-- 查询条件 -->
    <el-card shadow="never">
      <el-form :inline="true" @submit.prevent="handleSearch">
        <el-form-item label="关键字">
          <el-input
            v-model="query.keyword"
            placeholder="房间号 / uuid / 玩家ID / 昵称"
            clearable
            style="width: 220px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="玩法">
          <el-select v-model="query.game_type" style="width: 140px">
            <el-option label="全部" value="" />
            <el-option
              v-for="item in GAME_TYPE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="query.source" style="width: 130px">
            <el-option
              v-for="item in GAME_SOURCE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="开局日期">
          <el-date-picker
            v-model="query.dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 260px"
          />
        </el-form-item>
        <el-form-item label="排序">
          <el-select v-model="query.ordering" style="width: 190px">
            <el-option
              v-for="item in GAME_ORDERING_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never">
      <el-table v-loading="loading" :data="result.items" border stripe>
        <el-table-column label="房间号" width="150">
          <template #default="{ row }: { row: GameSummary }">
            <div>{{ row.room_id || '—' }}</div>
            <el-text size="small" type="info">{{ row.room_uuid }}</el-text>
          </template>
        </el-table-column>
        <el-table-column label="局" width="70">
          <template #default="{ row }: { row: GameSummary }">{{ roundText(row) }}</template>
        </el-table-column>
        <el-table-column label="玩法" width="100">
          <template #default="{ row }: { row: GameSummary }">
            <el-tag type="info" effect="plain" size="small">{{ row.type_label || row.type || '—' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }: { row: GameSummary }">
            <el-tag :type="sourceTagType(row.source)" size="small" effect="light">
              {{ row.source_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="玩家身份" width="110">
          <template #default="{ row }: { row: GameSummary }">
            <el-tag :type="identityTagType(row.identity_source)" size="small" effect="plain">
              {{ row.identity_source }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="四家得分（本局）" min-width="250" show-overflow-tooltip>
          <template #default="{ row }: { row: GameSummary }">
            <span v-for="seat in row.seats" :key="seat.seat_index" class="seat-score">
              <el-text size="small">{{ seatDisplayName(seat) }}</el-text>
              <span :class="seat.score > 0 ? 'score score--up' : 'score'">{{ seat.score }}</span>
              <el-tag v-if="seat.is_banker" size="small" type="warning" effect="plain">庄</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="动作流水" width="190" show-overflow-tooltip>
          <template #default="{ row }: { row: GameSummary }">
            {{ actionSummaryText(row.action_summary) }}
          </template>
        </el-table-column>
        <el-table-column label="开局时间" width="160">
          <template #default="{ row }: { row: GameSummary }">{{ row.created_at || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }: { row: GameSummary }">
            <el-button link type="primary" size="small" @click="handleRowDetail(row)">
              出牌记录
            </el-button>
            <el-button link type="primary" size="small" @click="openRoom(row.room_uuid)">
              本房间对局
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="没有符合条件的对局（每结束一局才会写库；换个条件试试）" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="game-pagination"
        :total="result.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadGames"
        @size-change="handleSearch"
      />
    </el-card>

    <!-- 单局详情：出牌记录 -->
    <GameDetailDrawer
      v-model="detailVisible"
      :room-ref="detailRoomRef"
      :game-index="detailGameIndex"
    />

    <!-- 一个房间的全部对局 -->
    <RoomGamesDrawer
      v-model="roomDrawerVisible"
      :room-ref="roomDrawerRef"
      @open-game="handleOpenGame"
    />
  </div>
</template>

<style scoped>
.overview-card__label {
  font-size: 13px;
  color: var(--admin-text-secondary);
}

.overview-card__value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 600;
  color: var(--admin-text);
}

.overview-card__tip {
  margin-top: 4px;
  font-size: 12px;
  color: var(--admin-text-secondary);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.game-pagination {
  justify-content: flex-end;
  margin-top: 16px;
}

.seat-score {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  margin-right: 10px;
}

.score--up {
  color: var(--el-color-success);
  font-weight: 600;
}
</style>
