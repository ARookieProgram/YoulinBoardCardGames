<script setup lang="ts">
/**
 * 房间对局抽屉 —— 一个房间的**全部对局**（含房间信息与四个座位）。
 *
 * 与「房间管理」的详情抽屉是两回事：
 *
 *  * 房间管理看的是 `t_rooms`，只有**还活着**的房间；
 *  * 这里看的是归档表 `t_games_archive`，**打完的房间照样能查**
 *    （这正是它的价值：玩家报"某局有问题"时，房间早就从 t_rooms 里删掉了）。
 *    房间还在打的对局没归档，这里就是空的——那是刻意口径，不是 bug。
 *
 * 座位身份由后端解析（存活房间表 → 战绩快照 → 未知），`identity_note` 会说明来源；
 * 点某一局的"出牌记录"把事件抛给父组件，由父组件打开单局详情抽屉
 * （抽屉套抽屉容易乱，所以这里不自己开新抽屉）。
 */

import { computed, ref, watch } from 'vue'

import { getRoomGames } from '@/api/games'
import { ApiError } from '@/api/errors'
import type { GameSummary, RoomGameList, RoomGameSeat } from '@/api/types'
import {
  actionSummaryText,
  identityTagType,
  roomRefText,
  roundText,
  seatDisplayName,
  winnerText,
} from '@/utils/game'

const props = defineProps<{
  /** 抽屉是否可见（v-model）。 */
  modelValue: boolean
  /** 房间号或 uuid；为空时不请求。 */
  roomRef: string | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  /** 请求父组件打开某一局的出牌记录。 */
  (event: 'open-game', payload: { roomUuid: string; gameIndex: number }): void
}>()

/** 抽屉可见性。 */
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

/** 房间数据。 */
const room = ref<RoomGameList | null>(null)
const loading = ref(false)
const loadError = ref('')

/** 拉数据。 */
async function loadRoom(): Promise<void> {
  const roomRef = props.roomRef
  if (roomRef === null || roomRef === '') return

  loading.value = true
  loadError.value = ''
  try {
    room.value = await getRoomGames(roomRef)
  } catch (error) {
    room.value = null
    loadError.value = error instanceof ApiError ? error.message : '房间对局加载失败'
  } finally {
    loading.value = false
  }
}

/** 打开抽屉时重置并加载。 */
watch(
  () => [props.modelValue, props.roomRef] as const,
  ([open]) => {
    if (!open) return
    room.value = null
    loadError.value = ''
    void loadRoom()
  },
  { immediate: true },
)

/** 打开某一局的出牌记录。 */
function openGame(game: GameSummary): void {
  emit('open-game', { roomUuid: game.room_uuid, gameIndex: game.game_index })
}

/** 座位累计分（没有身份时显示"未知"）。 */
function roomScoreText(seat: RoomGameSeat): string {
  return seat.room_score === null || seat.room_score === undefined ? '未知' : String(seat.room_score)
}

defineExpose({ reload: loadRoom })
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="room ? `房间对局 ${roomRefText(room)}` : `房间对局 ${roomRef ?? ''}`"
    size="56%"
    destroy-on-close
    append-to-body
  >
    <el-skeleton v-if="loading" :rows="8" animated />

    <el-alert
      v-else-if="loadError"
      type="error"
      show-icon
      :closable="false"
      title="加载失败"
      :description="loadError"
    />

    <template v-else-if="room">
      <div class="room-tags">
        <el-tag type="info" effect="dark" size="small">归档对局</el-tag>
        <el-tag v-if="room.live" type="warning" effect="plain" size="small">
          房间行仍在 t_rooms
        </el-tag>
        <el-tag type="info" effect="plain" size="small">{{ room.type_label || room.type || '—' }}</el-tag>
        <el-tag :type="identityTagType(room.identity_source)" effect="light" size="small">
          玩家身份：{{ room.identity_source }}
        </el-tag>
        <el-text size="small" type="info">共 {{ room.game_count }} 局</el-text>
      </div>

      <el-alert
        type="info"
        show-icon
        :closable="false"
        :title="room.identity_note"
        description="对局表里只有座位号，没有玩家；玩家身份由后端从存活房间表或玩家战绩快照反查得到。"
      />

      <el-descriptions :column="2" border size="small" class="room-desc">
        <el-descriptions-item label="房间号">{{ room.room_id || '—' }}</el-descriptions-item>
        <el-descriptions-item label="房间 uuid">{{ room.room_uuid }}</el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">座位（房间累计得分）</el-divider>
      <el-table :data="room.seats" size="small" border>
        <el-table-column prop="seat_index" label="座位" width="70" />
        <el-table-column label="玩家" min-width="140">
          <template #default="{ row }: { row: RoomGameSeat }">
            <el-tag size="small" effect="light">{{ seatDisplayName(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="玩家ID" width="90">
          <template #default="{ row }: { row: RoomGameSeat }">
            {{ row.player_id > 0 ? row.player_id : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="累计得分" width="100">
          <template #default="{ row }: { row: RoomGameSeat }">{{ roomScoreText(row) }}</template>
        </el-table-column>
      </el-table>

      <el-divider content-position="left">逐局</el-divider>
      <el-table :data="room.games" size="small" border>
        <el-table-column label="局" width="70">
          <template #default="{ row }: { row: GameSummary }">{{ roundText(row) }}</template>
        </el-table-column>
        <el-table-column label="开局时间" width="160">
          <template #default="{ row }: { row: GameSummary }">{{ row.created_at || '—' }}</template>
        </el-table-column>
        <el-table-column label="四家得分" min-width="240" show-overflow-tooltip>
          <template #default="{ row }: { row: GameSummary }">{{ winnerText(row) || '全部 0 分' }}</template>
        </el-table-column>
        <el-table-column label="动作" width="200" show-overflow-tooltip>
          <template #default="{ row }: { row: GameSummary }">
            {{ actionSummaryText(row.action_summary) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }: { row: GameSummary }">
            <el-button link type="primary" size="small" @click="openGame(row)">出牌记录</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty
            description="这个房间还没有归档对局（对局记录只读归档表：房间打完 / 被解散后才会归档）"
          />
        </template>
      </el-table>
    </template>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button :loading="loading" @click="loadRoom">刷新</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.room-tags {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.room-desc {
  margin-top: 12px;
}
</style>
