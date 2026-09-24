<script setup lang="ts">
/**
 * 玩家对局表 —— 某个玩家的**房间级战绩**（可复用在两处）。
 *
 * 数据来源是玩家库 `t_users.history`：游戏服在房间打完后给四家各写一条
 * `{uuid, id, time, seats[{userid, name, score}]}` 的快照，**每人只保留最近 10 场**
 * （`gamemgr.store_single_history` 的裁剪口径，后端会把这句话放在 `note` 里返回）。
 *
 * 所以这里能看到的是"最近玩过哪些房间、那局四个人各多少分"，
 * **逐局明细（谁打了哪张牌）要点进房间再看**——本组件只把事件抛给父组件，
 * 不自己开抽屉（玩家详情抽屉里再套一层抽屉会很难用）。
 *
 * 两个使用场景：
 *  1. 玩家详情抽屉的「对局记录」Tab；
 *  2. 对局记录页带上 `?player_id=` 时的"该玩家最近对局"面板。
 */

import { ref, watch } from 'vue'

import { listPlayerGames } from '@/api/games'
import { ApiError } from '@/api/errors'
import type { PlayerGameRecord, PlayerGamesResult } from '@/api/types'
import { seatDisplayName } from '@/utils/game'

const props = defineProps<{
  /** 要看哪个玩家；为空时不请求。 */
  playerId: number | null
  /** 是否在数据变化时自动加载（玩家详情抽屉里用 `true`）。 */
  autoLoad?: boolean
  /** 是否显示"在「对局记录」页打开"的提示（对局记录页里用 `false`）。 */
  showHint?: boolean
}>()

const emit = defineEmits<{
  /** 请求父组件打开某个房间的对局列表。 */
  (event: 'open-room', payload: { roomUuid: string; roomRef: string }): void
}>()

/** 数据。 */
const data = ref<PlayerGamesResult | null>(null)
const loading = ref(false)
const loadError = ref('')

/** 拉数据。 */
async function load(): Promise<void> {
  const playerId = props.playerId
  if (playerId === null) return

  loading.value = true
  loadError.value = ''
  try {
    data.value = await listPlayerGames(playerId)
  } catch (error) {
    data.value = null
    loadError.value = error instanceof ApiError ? error.message : '玩家对局加载失败'
  } finally {
    loading.value = false
  }
}

/** 玩家 ID 变化时自动加载（对局记录页由父组件手动触发）。 */
watch(
  () => props.playerId,
  (playerId) => {
    if (!props.autoLoad) return
    if (playerId === null) {
      data.value = null
      return
    }
    void load()
  },
  { immediate: true },
)

/** 打开某个房间的对局列表。 */
function openRoom(record: PlayerGameRecord): void {
  emit('open-room', { roomUuid: record.room_uuid, roomRef: record.room_id || record.room_uuid })
}

/** 名次展示：`第 1 名` / `未知`。 */
function rankText(record: PlayerGameRecord): string {
  return record.my_rank === null ? '未知' : `第 ${record.my_rank} 名`
}

/** 我的得分（带正负号）。 */
function myScoreText(record: PlayerGameRecord): string {
  return record.my_score > 0 ? `+${record.my_score}` : String(record.my_score)
}

defineExpose({ reload: load })
</script>

<template>
  <div class="player-games">
    <el-skeleton v-if="loading" :rows="4" animated />

    <el-alert
      v-else-if="loadError"
      type="error"
      show-icon
      :closable="false"
      title="加载失败"
      :description="loadError"
    />

    <template v-else-if="data">
      <el-alert
        v-if="showHint !== false"
        type="info"
        show-icon
        :closable="false"
        title="玩家的战绩快照"
        :description="data.note"
      />

      <el-table :data="data.items" size="small" border class="player-games__table">
        <el-table-column label="房间号" width="100">
          <template #default="{ row }: { row: PlayerGameRecord }">
            {{ row.room_id || row.room_uuid }}
          </template>
        </el-table-column>
        <el-table-column label="结束时间" width="160">
          <template #default="{ row }: { row: PlayerGameRecord }">
            {{ row.created_at || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="我的座位/得分" width="140">
          <template #default="{ row }: { row: PlayerGameRecord }">
            {{ row.my_seat === null ? '—' : `${row.my_seat} 号位` }} ·
            <span :class="row.my_score > 0 ? 'score score--up' : 'score'">{{ myScoreText(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="名次" width="90">
          <template #default="{ row }: { row: PlayerGameRecord }">{{ rankText(row) }}</template>
        </el-table-column>
        <el-table-column label="四家总分" min-width="220" show-overflow-tooltip>
          <template #default="{ row }: { row: PlayerGameRecord }">
            <span v-for="seat in row.seats" :key="seat.seat_index" class="seat-score">
              <el-tag v-if="seat.is_me" size="small" type="primary" effect="dark">
                {{ seatDisplayName(seat) }} {{ seat.score }}
              </el-tag>
              <el-text v-else size="small">{{ seatDisplayName(seat) }} {{ seat.score }}</el-text>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="局数" width="80">
          <template #default="{ row }: { row: PlayerGameRecord }">
            {{ row.game_count > 0 ? `${row.game_count} 局` : '无记录' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }: { row: PlayerGameRecord }">
            <el-button link type="primary" size="small" @click="openRoom(row)">本房间对局</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="这位玩家没有战绩快照（游戏服只在打完一整局后写入，且只保留最近 10 场）" />
        </template>
      </el-table>

      <el-text size="small" type="info" class="player-games__tip">
        共 {{ data.total }} 场（上限 {{ data.max_entries }} 场）
      </el-text>
    </template>
  </div>
</template>

<style scoped>
.player-games__table {
  margin-top: 12px;
}

.player-games__tip {
  display: block;
  margin-top: 8px;
}

.score--up {
  color: var(--el-color-success);
  font-weight: 600;
}

.seat-score {
  margin-right: 10px;
}
</style>
