<script setup lang="ts">
/**
 * 玩家详情抽屉。
 *
 * 三个 Tab：
 *  1. **基础信息**——玩家只读字段（含房卡 `gems`）与封禁流水；
 *  2. **对局记录**——**真实数据**：从 `t_users.history` 读该玩家最近 10 场的
 *     房间战绩（房间号 / 时间 / 四家总分 / 我的得分与名次 / 该房间局数）；
 *     想看出牌明细就点"本房间对局"跳到「对局记录」页
 *     （`/games?player_id=…`，逐局出牌记录在那里）。
 *  3. **充值记录**——**预留入口**，后端返回 `reserved: true`，这里展示"待接入"。
 *
 * 抽屉本身**只读**：封禁 / 解封由 `PlayerListView` 统一处理（弹窗 + 二次确认），
 * 这里只把按钮事件抛给父组件，避免两处各写一套提交逻辑。
 *
 * 预留 Tab 的数据是**懒加载**的：不点开就不发请求。
 */

import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getPlayer, listPlayerRecharges } from '@/api/players'
import { ApiError } from '@/api/errors'
import type { PlayerBanRecord, PlayerDetail, PlayerReservedResult } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import PlayerGamesTable from '@/components/PlayerGamesTable.vue'

const props = defineProps<{
  /** 抽屉是否可见（v-model）。 */
  modelValue: boolean
  /** 要展示的玩家 ID；为空时不请求。 */
  playerId: number | null
  /** 打开时落在哪个 Tab（列表页的"对局记录/充值记录"入口会指定）。 */
  initialTab?: string
  /** 当前登录者是否有封禁 / 解封权限（管理员及以上）。 */
  canManage: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'ban', player: PlayerDetail): void
  (event: 'unban', player: PlayerDetail): void
}>()

const router = useRouter()

/** 抽屉可见性。 */
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

/** 当前 Tab。 */
const activeTab = ref<string>(props.initialTab ?? 'basic')

/** 详情数据。 */
const detail = ref<PlayerDetail | null>(null)
const loading = ref(false)
const loadError = ref('')

/** 预留 Tab 的返回（`null` = 还没加载过）。 */
const reserved = reactive<Record<'recharges', PlayerReservedResult | null>>({
  recharges: null,
})
const reservedLoading = reactive<Record<'recharges', boolean>>({
  recharges: false,
})

/** 当前封禁状态的展示文案。 */
const banText = computed(() => {
  const record = detail.value?.ban
  if (!record || !detail.value?.banned) return '正常'
  if (!record.expires_at) return '永久封禁'
  return `限时封禁至 ${formatDateTime(record.expires_at)}`
})

/** 状态标签颜色。 */
const banTagType = computed(() => (detail.value?.banned ? 'danger' : 'success'))

/** 拉详情。 */
async function loadDetail(): Promise<void> {
  const playerId = props.playerId
  if (playerId === null) return

  loading.value = true
  loadError.value = ''
  try {
    detail.value = await getPlayer(playerId)
  } catch (error) {
    detail.value = null
    loadError.value = error instanceof ApiError ? error.message : '玩家详情加载失败'
  } finally {
    loading.value = false
  }
}

/** 拉预留 Tab 的数据（每个 Tab 只拉一次）。 */
async function loadReserved(tab: 'recharges'): Promise<void> {
  const playerId = props.playerId
  if (playerId === null || reserved[tab] !== null || reservedLoading[tab]) return

  reservedLoading[tab] = true
  try {
    reserved[tab] = await listPlayerRecharges(playerId)
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '查询入口加载失败')
  } finally {
    reservedLoading[tab] = false
  }
}

/** 切 Tab 时按需加载（对局记录由 `PlayerGamesTable` 自己加载）。 */
watch(activeTab, (tab) => {
  if (tab === 'recharges') {
    void loadReserved(tab)
  }
})

/** 打开抽屉时重置并加载。 */
watch(
  () => [props.modelValue, props.playerId] as const,
  ([open]) => {
    if (!open) return
    activeTab.value = props.initialTab ?? 'basic'
    reserved.recharges = null
    detail.value = null
    void loadDetail()
    if (activeTab.value === 'recharges') {
      void loadReserved('recharges')
    }
  },
  { immediate: true },
)

/** 封禁按钮：交给父组件处理。 */
function handleBan(): void {
  if (detail.value) emit('ban', detail.value)
}

/** 解封按钮：交给父组件处理。 */
function handleUnban(): void {
  if (detail.value) emit('unban', detail.value)
}

/**
 * 到「对局记录」页看这位玩家的全部对局。
 *
 * 抽屉里的表格只能看到"房间级"的战绩快照（`t_users.history` 最多 10 场），
 * 逐局出牌记录要先定位到房间，所以这里带着 `player_id` 跳页。
 */
function goGamesPage(): void {
  const playerId = props.playerId
  if (playerId === null) return
  visible.value = false
  void router.push({ name: 'games', query: { player_id: String(playerId) } })
}

/** 打开某个房间的全部对局（同样跳到「对局记录」页，带上房间号）。 */
function handleOpenRoom(payload: { roomRef: string }): void {
  visible.value = false
  void router.push({ name: 'games', query: { room: payload.roomRef } })
}

/** 供父组件在封禁 / 解封后刷新详情（抽屉没开时不必发请求）。 */
async function reload(): Promise<void> {
  if (!props.modelValue) return
  await loadDetail()
}

defineExpose({ reload })
</script>

<template>
  <el-drawer v-model="visible" :title="`玩家详情 #${playerId ?? ''}`" size="46%" destroy-on-close>
    <el-skeleton v-if="loading" :rows="6" animated />

    <el-alert
      v-else-if="loadError"
      type="error"
      show-icon
      :closable="false"
      title="加载失败"
      :description="loadError"
    />

    <template v-else-if="detail">
      <el-tabs v-model="activeTab">
        <!-- 基础信息 -->
        <el-tab-pane label="基础信息" name="basic">
          <div class="player-status">
            <el-tag :type="banTagType" effect="dark" size="small">{{ banText }}</el-tag>
            <el-text v-if="detail.ban?.reason" size="small" type="info">
              最近原因：{{ detail.ban.reason }}
            </el-text>
          </div>

          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="玩家ID">{{ detail.player_id }}</el-descriptions-item>
            <el-descriptions-item label="账号">{{ detail.account || '—' }}</el-descriptions-item>
            <el-descriptions-item label="昵称">{{ detail.name || '—' }}</el-descriptions-item>
            <el-descriptions-item label="等级">{{ detail.lv }}</el-descriptions-item>
            <el-descriptions-item label="房卡">
              <el-tag type="warning" effect="light" size="small">{{ detail.gems }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="金币">{{ detail.coins }}</el-descriptions-item>
            <el-descriptions-item label="经验">{{ detail.exp }}</el-descriptions-item>
            <el-descriptions-item label="当前房间">
              {{ detail.roomid || '—' }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="player-actions">
            <el-button
              v-if="canManage && !detail.banned"
              type="danger"
              size="small"
              @click="handleBan"
            >
              封禁该玩家
            </el-button>
            <el-button
              v-if="canManage && detail.banned"
              type="success"
              size="small"
              @click="handleUnban"
            >
              解封该玩家
            </el-button>
            <el-text v-if="!canManage" size="small" type="info">
              当前角色只能查看，封禁 / 解封需要管理员及以上权限
            </el-text>
          </div>

          <el-divider content-position="left">封禁流水</el-divider>
          <el-table :data="detail.ban_records" size="small" border empty-text="暂无封禁 / 解封记录">
            <el-table-column prop="action_display" label="操作" width="80" />
            <el-table-column prop="reason" label="原因" min-width="140" show-overflow-tooltip />
            <el-table-column prop="operator_name" label="操作人" width="110" />
            <el-table-column label="操作时间" width="160">
              <template #default="{ row }: { row: PlayerBanRecord }">
                {{ formatDateTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="自动解封" width="160">
              <template #default="{ row }: { row: PlayerBanRecord }">
                {{ row.expires_at ? formatDateTime(row.expires_at) : '永久' }}
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 对局记录（真实数据：t_users.history 的房间级战绩快照） -->
        <el-tab-pane label="对局记录" name="games">
          <div class="player-games-head">
            <el-text size="small" type="info">
              游戏服在房间打完后给四家各写一条战绩快照，每人只保留最近 10 场；
              逐局出牌记录要点进房间看。
            </el-text>
            <el-button link type="primary" size="small" @click="goGamesPage">
              在「对局记录」页打开
            </el-button>
          </div>
          <PlayerGamesTable
            v-if="activeTab === 'games'"
            :player-id="playerId"
            :auto-load="true"
            @open-room="handleOpenRoom"
          />
        </el-tab-pane>

        <!-- 预留：充值记录 -->
        <el-tab-pane label="充值记录" name="recharges">
          <el-skeleton v-if="reservedLoading.recharges" :rows="4" animated />
          <el-empty v-else description="充值记录查询入口已预留，数据源待接入">
            <el-text size="small" type="info">
              {{ reserved.recharges?.message ?? '正在读取接口说明…' }}
            </el-text>
            <p v-if="reserved.recharges" class="reserved-source">
              计划数据来源：{{ reserved.recharges.source }}
            </p>
          </el-empty>
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
.player-status {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.player-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 16px;
}

.reserved-source {
  max-width: 420px;
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--admin-text-secondary);
}

.player-games-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
</style>
