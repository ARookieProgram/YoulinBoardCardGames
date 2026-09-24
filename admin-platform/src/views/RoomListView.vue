<script setup lang="ts">
/**
 * 房间管理。
 *
 * 页面能力（对应本期需求）：
 *  1. **查看存活房间**——按房间号 / uuid / 座位玩家搜索，按玩法与座位占用过滤，分页；
 *  2. **概览**——房间总数、已满座、未满座、最近 24 小时新建；
 *  3. **房间详情**——配置、四个座位、所在游戏服（抽屉里展示，含座位分数）；
 *  4. **预留运维入口**——"强制解散"：契约、权限与前端调用链都已就绪，
 *     后端目前恒返回 `reserved: true`（需要游戏服先提供内部接口）。
 *
 * 数据来源：后端对**玩家库 `db_scmj` 的 `t_rooms`** 的只读查询。
 * 这张表里只有**尚未销毁**的房间——游戏服销毁房间时会删掉整行，
 * 所以"房间里的人打完了"会在下一次刷新时自然从列表消失。
 */

import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getRoomsOverview, listRooms } from '@/api/rooms'
import { ApiError } from '@/api/errors'
import { ErrorCode } from '@/api/types'
import type { PageResult, RoomState, RoomSummary, RoomsOverview } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import {
  ROOM_ORDERING_OPTIONS,
  ROOM_STATE_OPTIONS,
  ROOM_TYPE_OPTIONS,
  roomStateLabel,
  roomStateTagType,
  roomTypeLabel,
  seatSummary,
  seatUsage,
  serverAddr,
  turnUsage,
} from '@/utils/room'
import RoomDetailDrawer from '@/components/RoomDetailDrawer.vue'

const auth = useAuthStore()

/** 运维操作需要管理员及以上（与后端 `IsAdminOrAbove` 一致）。 */
const canManage = computed(() => auth.isAdminOrAbove)

/** 查询条件。 */
const query = reactive({
  keyword: '',
  room_type: '',
  state: 'all' as RoomState | 'all',
  ordering: '-create_time',
})

const page = ref(1)
const pageSize = ref(20)

/** 列表结果。 */
const result = ref<PageResult<RoomSummary>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  pages: 0,
})
const loading = ref(false)

/** 概览数字；玩家库不可用时保持 `null` 并给出提示。 */
const overview = ref<RoomsOverview | null>(null)
const sourceError = ref('')

/** 详情抽屉。 */
const drawerVisible = ref(false)
const drawerRoomRef = ref<string | null>(null)
const drawerRef = ref<InstanceType<typeof RoomDetailDrawer> | null>(null)

/** 概览卡片。 */
const overviewCards = computed(() => [
  {
    label: '存活房间',
    value: overview.value ? String(overview.value.total_rooms) : '—',
    tip: '来自玩家库 t_rooms（房间销毁后行会被删除）',
  },
  {
    label: '已满座',
    value: overview.value ? String(overview.value.playing_rooms) : '—',
    tip: '四个座位都有人',
  },
  {
    label: '未满座',
    value: overview.value ? String(overview.value.waiting_rooms) : '—',
    tip: '还有空位，正在等人',
  },
  {
    label: '24 小时新建',
    value: overview.value ? String(overview.value.created_last_24h) : '—',
    tip: '按 t_rooms.create_time 统计',
  },
])

/** 统一错误提示。 */
function reportError(error: unknown, fallback: string): void {
  if (error instanceof ApiError) {
    ElMessage.error(error.message)
    // 房间数据与玩家数据走**同一条**只读数据源，所以后端复用 12004 报"玩家库连不上"。
    if (error.code === ErrorCode.PLAYER_SOURCE_UNAVAILABLE) {
      sourceError.value = error.message
    }
    return
  }
  ElMessage.error(fallback)
}

/** 拉列表。 */
async function loadRooms(): Promise<void> {
  loading.value = true
  try {
    result.value = await listRooms({
      keyword: query.keyword.trim(),
      room_type: query.room_type,
      state: query.state,
      ordering: query.ordering,
      page: page.value,
      page_size: pageSize.value,
    })
    sourceError.value = ''
  } catch (error) {
    result.value = { items: [], total: 0, page: page.value, page_size: pageSize.value, pages: 0 }
    reportError(error, '房间列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 拉概览（失败不阻塞列表）。 */
async function loadOverview(): Promise<void> {
  try {
    overview.value = await getRoomsOverview()
  } catch (error) {
    overview.value = null
    reportError(error, '概览数据加载失败')
  }
}

/** 条件变化后回到第一页再查。 */
function handleSearch(): void {
  page.value = 1
  void loadRooms()
}

/** 重置查询条件。 */
function handleReset(): void {
  query.keyword = ''
  query.room_type = ''
  query.state = 'all'
  query.ordering = '-create_time'
  page.value = 1
  pageSize.value = 20
  void loadRooms()
}

/** 打开详情抽屉。 */
function openDrawer(room: RoomSummary): void {
  drawerRoomRef.value = room.room_id
  drawerVisible.value = true
}

onMounted(async () => {
  await Promise.all([loadRooms(), loadOverview()])
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
      title="房间数据源不可用"
      :description="`${sourceError}（请检查管理平台到玩家库 db_scmj 的连接配置）`"
    />

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="只读监控"
      description="列表里只有“还活着”的房间：游戏服销毁房间时会删掉 t_rooms 里的一行，所以打完 / 被解散的房间不会留在这里。强制解散等写操作本期只预留入口。"
    />

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
          <el-select v-model="query.room_type" style="width: 140px">
            <el-option label="全部" value="" />
            <el-option
              v-for="item in ROOM_TYPE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.state" style="width: 130px">
            <el-option
              v-for="item in ROOM_STATE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-select v-model="query.ordering" style="width: 190px">
            <el-option
              v-for="item in ROOM_ORDERING_OPTIONS"
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
        <el-table-column prop="room_id" label="房间号" width="100" />
        <el-table-column label="玩法" width="110">
          <template #default="{ row }: { row: RoomSummary }">
            <el-tag type="info" effect="plain" size="small">{{ roomTypeLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }: { row: RoomSummary }">
            <el-tag :type="roomStateTagType(row.state)" size="small" effect="light">
              {{ roomStateLabel(row.state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="座位" width="90">
          <template #default="{ row }: { row: RoomSummary }">
            <el-tag :type="row.occupied_seats > 0 ? 'success' : 'info'" size="small" effect="light">
              {{ seatUsage(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="座位玩家" min-width="220" show-overflow-tooltip>
          <template #default="{ row }: { row: RoomSummary }">
            {{ seatSummary(row) }}
          </template>
        </el-table-column>
        <el-table-column label="底分" width="80">
          <template #default="{ row }: { row: RoomSummary }">{{ row.conf.base_score }} 分</template>
        </el-table-column>
        <el-table-column label="局数" width="90">
          <template #default="{ row }: { row: RoomSummary }">{{ turnUsage(row) }}</template>
        </el-table-column>
        <el-table-column label="房主" width="90">
          <template #default="{ row }: { row: RoomSummary }">#{{ row.conf.creator }}</template>
        </el-table-column>
        <el-table-column label="游戏服" width="150">
          <template #default="{ row }: { row: RoomSummary }">{{ serverAddr(row) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }: { row: RoomSummary }">{{ row.created_at || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }: { row: RoomSummary }">
            <el-button link type="primary" size="small" @click="openDrawer(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="没有符合条件的房间（房间里可能刚打完）" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="room-pagination"
        :total="result.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadRooms"
        @size-change="handleSearch"
      />
    </el-card>

    <!-- 详情 / 预留运维入口 -->
    <RoomDetailDrawer
      ref="drawerRef"
      v-model="drawerVisible"
      :room-ref="drawerRoomRef"
      :can-manage="canManage"
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
  font-size: 24px;
  font-weight: 600;
  color: var(--admin-text);
}

.overview-card__tip {
  margin-top: 4px;
  font-size: 12px;
  color: var(--admin-text-secondary);
}

.room-pagination {
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
