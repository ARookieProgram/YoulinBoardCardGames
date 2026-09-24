<script setup lang="ts">
/**
 * 单局详情抽屉 —— **这一局每个玩家打了什么**。
 *
 * 三个 Tab：
 *  1. **出牌记录**（默认）——全局时间线：第几步、谁、什么动作、哪张牌、
 *     这张打出的牌后来被谁碰/杠/胡（后端从流水里推出来，标在 `taken_by`）；
 *  2. **分座位**——同一个流水按玩家重新分组：他打出的牌、摸到的牌、碰杠胡，
 *     也就是"某个玩家的出牌记录"；
 *  3. **开局快照**——`t_games.base_info`：四家起手牌与牌墙消耗
 *     （洗好的 108 张、发出 53 张、被摸走多少、还剩多少）。
 *
 * 数据来自 `t_games` / `t_games_archive` 的只读查询；牌面与动作名的中文口径
 * 全部由后端 `apps/games/decoding.py` 给出（`tile_label` / `action_label`），
 * 前端只负责排版与配色。
 *
 * 抽屉是只读的：对局是历史数据，本模块没有任何写入口。
 */

import { computed, ref, watch } from 'vue'

import { getGameDetail } from '@/api/games'
import { ApiError } from '@/api/errors'
import type { GameAction, GameDetail, GameSeatActions } from '@/api/types'
import {
  actionSummaryText,
  actionTagType,
  roomRefText,
  roundText,
  seatDisplayName,
  tileSuitClass,
} from '@/utils/game'

const props = defineProps<{
  /** 抽屉是否可见（v-model）。 */
  modelValue: boolean
  /** 房间 uuid（或房间号）；为空时不请求。 */
  roomRef: string | null
  /** 游戏服的局号（从 0 开始）；为空时不请求。 */
  gameIndex: number | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
}>()

/** 抽屉可见性。 */
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

/** 当前 Tab。 */
const activeTab = ref('timeline')

/** 详情数据。 */
const detail = ref<GameDetail | null>(null)
const loading = ref(false)
const loadError = ref('')

/** 拉详情。 */
async function loadDetail(): Promise<void> {
  const roomRef = props.roomRef
  const gameIndex = props.gameIndex
  if (roomRef === null || roomRef === '' || gameIndex === null) return

  loading.value = true
  loadError.value = ''
  try {
    detail.value = await getGameDetail(roomRef, gameIndex)
  } catch (error) {
    detail.value = null
    loadError.value = error instanceof ApiError ? error.message : '对局详情加载失败'
  } finally {
    loading.value = false
  }
}

/** 打开抽屉时重置并加载。 */
watch(
  () => [props.modelValue, props.roomRef, props.gameIndex] as const,
  ([open]) => {
    if (!open) return
    activeTab.value = 'timeline'
    detail.value = null
    loadError.value = ''
    void loadDetail()
  },
  { immediate: true },
)

/** 抽屉标题。 */
const title = computed(() => {
  const game = detail.value
  const ref = props.roomRef ?? ''
  if (!game) return `对局详情 ${ref}`
  return `房间 ${roomRefText(game)} · ${roundText(game)}`
})

/** 概要行。 */
const summaryRows = computed(() => {
  const game = detail.value
  if (!game) return []
  return [
    { label: '房间号', value: roomRefText(game) },
    { label: '房间 uuid', value: game.room_uuid },
    { label: '局号', value: `${roundText(game)}（game_index=${game.game_index}）` },
    { label: '玩法', value: game.type_label || game.type || '—' },
    { label: '对局来源', value: game.source_label },
    { label: '开局时间', value: game.created_at || '—' },
    { label: '本局庄家', value: `座位 ${game.button}` },
    {
      label: '玩家身份',
      value: game.identity_note || '—',
    },
  ]
})

/** 牌墙摘要。 */
const wallText = computed(() => {
  const wall = detail.value?.wall
  if (!wall) return '—'
  return `${wall.size} 张 · 已发 ${wall.dealt} · 已摸 ${wall.drawn} · 剩余 ${wall.remaining}`
})

/** 座位动作卡片的标题。 */
function seatActionsTitle(seat: GameSeatActions): string {
  const role = seat.is_banker ? '庄家' : roleText(seat)
  const result = seat.score > 0 ? `+${seat.score}` : String(seat.score)
  return `${seat.seat_index} 号位 · ${seatDisplayName(seat)} · ${role} · ${result} 分`
}

/** 座位角色说明（谁胡了 / 谁点炮，一眼能看出来）。 */
function roleText(seat: GameSeatActions): string {
  if (seat.zimo) return '自摸'
  if (seat.hued) return '胡牌'
  return '未胡'
}

/** 时间线里"这一张牌被谁拿走"的说明。 */
function takenText(action: GameAction): string {
  if (!action.taken_by) return ''
  return `被 ${action.taken_by.name} ${action.taken_by.action_label}`
}

defineExpose({ reload: loadDetail })
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="title"
    size="58%"
    destroy-on-close
    append-to-body
  >
    <el-skeleton v-if="loading" :rows="10" animated />

    <el-alert
      v-else-if="loadError"
      type="error"
      show-icon
      :closable="false"
      title="加载失败"
      :description="loadError"
    />

    <template v-else-if="detail">
      <el-alert
        v-if="detail.warnings.length > 0"
        type="warning"
        show-icon
        :closable="false"
        title="流水里有脏数据（不影响其它内容）"
      >
        <ul class="warning-list">
          <li v-for="(item, index) in detail.warnings" :key="index">{{ item }}</li>
        </ul>
      </el-alert>

      <el-descriptions :column="2" border size="small">
        <el-descriptions-item v-for="row in summaryRows" :key="row.label" :label="row.label">
          {{ row.value }}
        </el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">四家得分（本局 / 房间累计）</el-divider>
      <el-table :data="detail.seats" size="small" border>
        <el-table-column prop="seat_index" label="座位" width="70" />
        <el-table-column label="玩家" min-width="140">
          <template #default="{ row }">
            <el-tag size="small" effect="light">{{ seatDisplayName(row) }}</el-tag>
            <el-tag v-if="row.is_banker" class="seat-tag" size="small" type="warning" effect="dark">
              庄
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="玩家ID" width="90">
          <template #default="{ row }">
            {{ row.player_id > 0 ? row.player_id : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="本局得分" width="100">
          <template #default="{ row }">
            <span :class="row.score > 0 ? 'score score--up' : 'score'">{{ row.score }}</span>
          </template>
        </el-table-column>
        <el-table-column label="房间累计" width="100">
          <template #default="{ row }">
            {{ row.room_score === null || row.room_score === undefined ? '未知' : row.room_score }}
          </template>
        </el-table-column>
      </el-table>

      <el-tabs v-model="activeTab" class="game-tabs">
        <!-- 出牌记录（全局时间线） -->
        <el-tab-pane :label="`出牌记录（${detail.timeline.length} 步）`" name="timeline">
          <el-empty v-if="detail.timeline.length === 0" description="这一局没有操作流水" />
          <el-table v-else :data="detail.timeline" size="small" border max-height="480">
            <el-table-column prop="seq" label="步" width="60" />
            <el-table-column label="座位" width="90">
              <template #default="{ row }: { row: GameAction }">
                {{ row.seat_label ?? `座位${row.seat_index}` }}
              </template>
            </el-table-column>
            <el-table-column label="玩家" min-width="110">
              <template #default="{ row }: { row: GameAction }">
                {{ row.seat_name ?? '—' }}
              </template>
            </el-table-column>
            <el-table-column label="动作" width="90">
              <template #default="{ row }: { row: GameAction }">
                <el-tag :type="actionTagType(row.action)" size="small" effect="light">
                  {{ row.action_label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="牌" width="90">
              <template #default="{ row }: { row: GameAction }">
                <span :class="tileSuitClass(row.tile_suit)">{{ row.tile_label }}</span>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="140">
              <template #default="{ row }: { row: GameAction }">
                <el-text v-if="takenText(row)" size="small" type="warning">{{ takenText(row) }}</el-text>
                <el-text v-else size="small" type="info">—</el-text>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 分座位：每个玩家自己的出牌记录 -->
        <el-tab-pane label="分座位（每个玩家的出牌）" name="seats">
          <el-collapse>
            <el-collapse-item
              v-for="seat in detail.seat_actions"
              :key="seat.seat_index"
              :name="String(seat.seat_index)"
            >
              <template #title>
                <span class="seat-title">{{ seatActionsTitle(seat) }}</span>
              </template>

              <div class="seat-block">
                <div class="seat-line">
                  <span class="seat-label">打出（{{ seat.folds.length }}）</span>
                  <span v-if="seat.folds.length === 0" class="seat-empty">无</span>
                  <span v-for="item in seat.folds" :key="item.seq" class="tile-chip">
                    <span :class="tileSuitClass(item.tile_suit)">{{ item.tile_label }}</span>
                    <el-text v-if="item.taken_by" size="small" type="warning" class="tile-note">
                      被{{ item.taken_by.action_label }}
                    </el-text>
                  </span>
                </div>

                <div class="seat-line">
                  <span class="seat-label">摸到（{{ seat.drawn.length }}）</span>
                  <span v-if="seat.drawn.length === 0" class="seat-empty">无</span>
                  <span v-for="item in seat.drawn" :key="item.seq" class="tile-chip">
                    <span :class="tileSuitClass(item.tile_suit)">{{ item.tile_label }}</span>
                  </span>
                </div>

                <div class="seat-line">
                  <span class="seat-label">碰 / 杠</span>
                  <span v-if="seat.pengs.length + seat.gangs.length === 0" class="seat-empty">无</span>
                  <el-tag v-for="item in seat.pengs" :key="`p${item.seq}`" size="small" effect="plain">
                    碰 {{ item.tile_label }}
                  </el-tag>
                  <el-tag
                    v-for="item in seat.gangs"
                    :key="`g${item.seq}`"
                    size="small"
                    type="primary"
                    effect="plain"
                  >
                    杠 {{ item.tile_label }}
                  </el-tag>
                </div>

                <div class="seat-line">
                  <span class="seat-label">胡牌</span>
                  <span v-if="seat.win_tiles.length === 0" class="seat-empty">未胡</span>
                  <el-tag v-for="item in seat.win_tiles" :key="item.seq" size="small" type="danger">
                    {{ item.action_label }} {{ item.tile_label }}
                  </el-tag>
                </div>

                <div class="seat-line">
                  <span class="seat-label">动作统计</span>
                  <el-text size="small" type="info">{{ actionSummaryText(seat.summary) }}</el-text>
                </div>

                <el-table :data="seat.actions" size="small" border class="seat-table">
                  <el-table-column prop="seq" label="步" width="60" />
                  <el-table-column prop="action_label" label="动作" width="80" />
                  <el-table-column prop="tile_label" label="牌" width="80" />
                  <el-table-column label="说明">
                    <template #default="{ row }: { row: GameAction }">
                      {{ takenText(row) || '—' }}
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>

        <!-- 开局快照 -->
        <el-tab-pane label="开局快照（起手牌 / 牌墙）" name="snapshot">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="牌墙消耗">{{ wallText }}</el-descriptions-item>
            <el-descriptions-item label="流水条数">
              {{ detail.action_count }} 步（{{ actionSummaryText(detail.action_summary) }}）
            </el-descriptions-item>
          </el-descriptions>

          <el-table :data="detail.initial_hands" size="small" border class="hand-table">
            <el-table-column prop="seat_index" label="座位" width="70" />
            <el-table-column prop="name" label="玩家" width="130" />
            <el-table-column prop="tile_count" label="张数" width="70" />
            <el-table-column label="起手牌" min-width="260">
              <template #default="{ row }">
                <span v-for="item in row.tiles" :key="`${row.seat_index}-${item.tile}`" class="tile-chip">
                  <span :class="tileSuitClass(item.tile_suit)">{{ item.tile_label }}</span>
                </span>
              </template>
            </el-table-column>
          </el-table>

          <el-alert
            class="snapshot-tip"
            type="info"
            show-icon
            :closable="false"
            title="关于开局快照"
            description="起手牌来自 t_games.base_info.game_seats，牌墙来自同一行的 mahjongs（洗好的 108 张）。这份快照足够还原整局，客户端回放用的就是它 + 上面的出牌流水。"
          />
        </el-tab-pane>
      </el-tabs>
    </template>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button :loading="loading" @click="loadDetail">刷新</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.warning-list {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
}

.game-tabs {
  margin-top: 12px;
}

.seat-tag {
  margin-left: 6px;
}

.score--up {
  color: var(--el-color-success);
  font-weight: 600;
}

.seat-title {
  font-size: 13px;
}

.seat-block {
  padding: 4px 0 12px;
}

.seat-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.seat-label {
  min-width: 96px;
  font-size: 12px;
  color: var(--admin-text-secondary);
}

.seat-empty {
  font-size: 12px;
  color: var(--admin-text-secondary);
}

.tile-chip {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  margin-right: 4px;
}

.tile-note {
  font-size: 11px;
}

.tile {
  display: inline-block;
  padding: 1px 6px;
  font-size: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
}

.tile--dot {
  color: #2b7fd4;
  background: #f0f7ff;
}

.tile--bamboo {
  color: #1f9d55;
  background: #f0fbf5;
}

.tile--character {
  color: #c0392b;
  background: #fff4f2;
}

.tile--unknown {
  color: var(--admin-text-secondary);
  background: #f5f5f5;
}

.seat-table {
  margin-top: 8px;
}

.hand-table {
  margin-top: 12px;
}

.snapshot-tip {
  margin-top: 12px;
}
</style>
