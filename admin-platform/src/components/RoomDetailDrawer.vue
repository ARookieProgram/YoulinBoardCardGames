<script setup lang="ts">
/**
 * 房间详情抽屉。
 *
 * 展示的是一个**存活房间**的完整快照：
 *  1. 房间本身（房间号 / uuid / 玩法 / 状态 / 已打局数 / 所在游戏服 / 创建时间）；
 *  2. 房间配置（底分、番数上限、局数上限、自摸、点杠花与四个玩法开关）；
 *  3. 四个座位（谁在座、多少分）。
 *
 * 外加**预留的运维入口**：强制解散。本期后端只返回 `reserved: true`
 * （见 `apps/rooms/views.py` 的 `RoomDissolveView`），所以这里把说明摆在明面上，
 * 按钮点了也只会得到一句"入口已预留"——接入游戏服接口后这一层不用改。
 *
 * 抽屉本身**只读**，解散由本组件直接调接口（不像玩家封禁那样抛给父组件），
 * 因为它不改变列表里的任何字段——真解散成功时房间行会消失，
 * 那时再补"通知父组件刷新"也不迟。
 */

import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { dissolveRoom, getRoom } from '@/api/rooms'
import { ApiError } from '@/api/errors'
import type { RoomDetail, RoomSeat } from '@/api/types'
import {
  confFlags,
  dianganghuaLabel,
  roomStateLabel,
  roomStateTagType,
  roomTypeLabel,
  seatName,
  turnUsage,
  zimoLabel,
} from '@/utils/room'

const props = defineProps<{
  /** 抽屉是否可见（v-model）。 */
  modelValue: boolean
  /** 要展示的房间号或 uuid；为空时不请求。 */
  roomRef: string | null
  /** 当前登录者是否有运维权限（管理员及以上）——与后端 `IsAdminOrAbove` 一致。 */
  canManage: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
}>()

/** 抽屉可见性。 */
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

/** 详情数据。 */
const detail = ref<RoomDetail | null>(null)
const loading = ref(false)
const loadError = ref('')
const dissolving = ref(false)

/** 拉详情。 */
async function loadDetail(): Promise<void> {
  const roomRef = props.roomRef
  if (roomRef === null || roomRef === '') return

  loading.value = true
  loadError.value = ''
  try {
    detail.value = await getRoom(roomRef)
  } catch (error) {
    detail.value = null
    loadError.value = error instanceof ApiError ? error.message : '房间详情加载失败'
  } finally {
    loading.value = false
  }
}

/**
 * 强制解散（**预留入口**）。
 *
 * 走的是和后端约定好的完整调用链，只是后端现在不做实事：
 * 点击 → 说明 + 二次确认 → 调接口 → 提示"入口已预留"。
 */
async function handleDissolve(): Promise<void> {
  const room = detail.value
  if (room === null) return

  const action = room.actions.dissolve
  try {
    await ElMessageBox.confirm(
      `${action.message}\n\n${action.source}`,
      `强制解散房间 ${room.room_id}`,
      {
        confirmButtonText: '调用该入口',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  dissolving.value = true
  try {
    const result = await dissolveRoom(room.room_id)
    ElMessage.warning(result.message)
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '调用解散入口失败')
  } finally {
    dissolving.value = false
  }
}

/** 房间配置的展示行。 */
const confRows = computed(() => {
  const conf = detail.value?.conf
  if (!conf) return []
  return [
    { label: '底分', value: `${conf.base_score} 分` },
    { label: '最大番数', value: `${conf.max_fan} 番` },
    { label: '局数上限', value: `${conf.max_games} 局` },
    { label: '自摸加成', value: zimoLabel(conf.zimo) },
    { label: '点杠花', value: dianganghuaLabel(conf.dianganghua) },
    { label: '玩法开关', value: confFlags(conf).join('、') || '全部关闭' },
  ]
})

/** 打开抽屉时重置并加载。 */
watch(
  () => [props.modelValue, props.roomRef] as const,
  ([open]) => {
    if (!open) return
    detail.value = null
    loadError.value = ''
    void loadDetail()
  },
  { immediate: true },
)

/** 供父组件在需要时刷新（抽屉没开时不必发请求）。 */
async function reload(): Promise<void> {
  if (!props.modelValue) return
  await loadDetail()
}

defineExpose({ reload })
</script>

<template>
  <el-drawer v-model="visible" :title="`房间详情 ${roomRef ?? ''}`" size="52%" destroy-on-close>
    <el-skeleton v-if="loading" :rows="8" animated />

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
        type="info"
        show-icon
        :closable="false"
        title="只读快照"
        description="数据来自玩家库 t_rooms（只执行 SELECT）。房间在打完或被解散后，游戏服会删掉这一行，届时这里会显示“房间不存在或已结束”。"
      />

      <div class="room-status">
        <el-tag :type="roomStateTagType(detail.state)" effect="dark" size="small">
          {{ roomStateLabel(detail.state) }}
        </el-tag>
        <el-tag type="info" effect="plain" size="small">{{ roomTypeLabel(detail) }}</el-tag>
        <el-text size="small" type="info">
          已打 {{ turnUsage(detail) }} 局 · 座位 {{ detail.occupied_seats }}/{{ detail.seat_count }}
        </el-text>
      </div>

      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="房间号">{{ detail.room_id }}</el-descriptions-item>
        <el-descriptions-item label="房间 uuid">{{ detail.uuid }}</el-descriptions-item>
        <el-descriptions-item label="创建者">#{{ detail.conf.creator }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ detail.created_at || '—' }}</el-descriptions-item>
        <el-descriptions-item label="游戏服">
          {{ detail.ip ? `${detail.ip}:${detail.port}` : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="下一局庄家">{{ detail.next_button }}</el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">房间配置</el-divider>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item v-for="row in confRows" :key="row.label" :label="row.label">
          {{ row.value }}
        </el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">座位</el-divider>
      <el-table :data="detail.seats" size="small" border>
        <el-table-column prop="seat_index" label="座位" width="70" />
        <el-table-column label="玩家" min-width="140">
          <template #default="{ row }: { row: RoomSeat }">
            <el-tag v-if="row.occupied" size="small" effect="light">{{ seatName(row) }}</el-tag>
            <el-text v-else size="small" type="info">空座</el-text>
          </template>
        </el-table-column>
        <el-table-column label="玩家ID" width="100">
          <template #default="{ row }: { row: RoomSeat }">
            {{ row.occupied ? row.player_id : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="score" label="本局得分" width="100" />
      </el-table>

      <el-divider content-position="left">运维操作（预留）</el-divider>
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        :title="detail.actions.dissolve.message"
        :description="detail.actions.dissolve.source"
      />
      <div class="room-actions">
        <el-button
          v-if="canManage"
          type="danger"
          size="small"
          :loading="dissolving"
          @click="handleDissolve"
        >
          强制解散房间
        </el-button>
        <el-text v-else size="small" type="info">
          当前角色只能查看，强制解散需要管理员及以上权限
        </el-text>
      </div>
    </template>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button :loading="loading" @click="loadDetail">刷新</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.room-status {
  display: flex;
  gap: 10px;
  align-items: center;
  margin: 12px 0;
}

.room-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 12px;
}
</style>
