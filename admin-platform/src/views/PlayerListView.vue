<script setup lang="ts">
/**
 * 玩家管理。
 *
 * 页面能力（对应本期的需求）：
 *  1. **查询玩家**——按账号 / 昵称 / 玩家ID 搜索，按封禁状态过滤，分页；
 *  2. **展示房卡剩余数量**——`t_users.gems`，单独一列并用醒目的标签标出；
 *  3. **封禁 / 解封**——管理员及以上可操作，必须填原因（写进流水，可追溯）；
 *  4. **预留查询入口**——对局记录 / 充值记录：列表的"更多"与详情抽屉的 Tab
 *     都已经接上接口，后端目前返回 `reserved: true`（数据源待接入）。
 *
 * 数据来源说明：玩家字段来自后端对**玩家库的只读数据源**，
 * 封禁状态来自管理平台自己的库（`db_scmj_admin.players_playerban`）。
 */

import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'

import {
  banPlayer,
  getPlayersOverview,
  listPlayers,
  unbanPlayer,
} from '@/api/players'
import { ApiError } from '@/api/errors'
import { ErrorCode } from '@/api/types'
import type {
  PageResult,
  PlayerBanState,
  PlayerDetail,
  PlayerSummary,
  PlayersOverview,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import PlayerDetailDrawer from '@/components/PlayerDetailDrawer.vue'

const auth = useAuthStore()

/** 封禁 / 解封需要管理员及以上（与后端 `IsAdminOrAbove` 一致）。 */
const canManage = computed(() => auth.isAdminOrAbove)

/** 查询条件。 */
const query = reactive({
  keyword: '',
  ban_state: 'all' as PlayerBanState,
  ordering: '-userid',
})

const page = ref(1)
const pageSize = ref(20)

/** 列表结果。 */
const result = ref<PageResult<PlayerSummary>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  pages: 0,
})
const loading = ref(false)

/** 概览数字；玩家库不可用时保持 `null` 并给出提示。 */
const overview = ref<PlayersOverview | null>(null)
const sourceError = ref('')

/** 详情抽屉。 */
const drawerVisible = ref(false)
const drawerPlayerId = ref<number | null>(null)
const drawerTab = ref('basic')
const drawerRef = ref<InstanceType<typeof PlayerDetailDrawer> | null>(null)

/** 封禁弹窗。 */
const banDialogVisible = ref(false)
const banTarget = ref<PlayerSummary | null>(null)
const banFormRef = ref<FormInstance>()
const banSubmitting = ref(false)
const banForm = reactive({
  /** `permanent` 永久，`hours` 限时。 */
  mode: 'permanent' as 'permanent' | 'hours',
  durationHours: 24,
  reason: '',
})

const banRules: FormRules<typeof banForm> = {
  reason: [
    { required: true, message: '请填写封禁原因（会写进流水）', trigger: 'blur' },
    { max: 200, message: '原因不能超过 200 个字符', trigger: 'blur' },
  ],
  durationHours: [{ required: true, message: '请填写封禁时长', trigger: 'blur' }],
}

/** 概览卡片。 */
const overviewCards = computed(() => [
  {
    label: '玩家总数',
    value: overview.value ? String(overview.value.total_players) : '—',
    tip: '来自玩家库 t_users 的实时计数',
  },
  {
    label: '封禁中',
    value: overview.value ? String(overview.value.banned_players) : '—',
    tip: '来自管理平台库 players_playerban 的最新状态',
  },
  {
    label: '当前页房卡合计',
    value: String(result.value.items.reduce((sum, item) => sum + item.gems, 0)),
    tip: '仅统计当前页，用于快速核对',
  },
])

/** 统一错误提示。 */
function reportError(error: unknown, fallback: string): void {
  if (error instanceof ApiError) {
    ElMessage.error(error.message)
    if (error.code === ErrorCode.PLAYER_SOURCE_UNAVAILABLE) {
      sourceError.value = error.message
    }
    return
  }
  ElMessage.error(fallback)
}

/** 拉列表。 */
async function loadPlayers(): Promise<void> {
  loading.value = true
  try {
    result.value = await listPlayers({
      keyword: query.keyword.trim(),
      ban_state: query.ban_state,
      ordering: query.ordering,
      page: page.value,
      page_size: pageSize.value,
    })
    sourceError.value = ''
  } catch (error) {
    result.value = { items: [], total: 0, page: page.value, page_size: pageSize.value, pages: 0 }
    reportError(error, '玩家列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 拉概览（失败不阻塞列表）。 */
async function loadOverview(): Promise<void> {
  try {
    overview.value = await getPlayersOverview()
  } catch (error) {
    overview.value = null
    reportError(error, '概览数据加载失败')
  }
}

/** 条件变化后回到第一页再查。 */
function handleSearch(): void {
  page.value = 1
  void loadPlayers()
}

/** 重置查询条件。 */
function handleReset(): void {
  query.keyword = ''
  query.ban_state = 'all'
  query.ordering = '-userid'
  page.value = 1
  pageSize.value = 20
  void loadPlayers()
}

/** 打开详情抽屉（`tab` 用于直接落到"对局记录 / 充值记录"这类预留入口）。 */
function openDrawer(player: PlayerSummary, tab = 'basic'): void {
  drawerPlayerId.value = player.player_id
  drawerTab.value = tab
  drawerVisible.value = true
}

/** 打开封禁弹窗。 */
function openBanDialog(player: PlayerSummary | PlayerDetail): void {
  banTarget.value = player as PlayerSummary
  banForm.mode = 'permanent'
  banForm.durationHours = 24
  banForm.reason = ''
  banDialogVisible.value = true
}

/** 提交封禁。 */
async function submitBan(): Promise<void> {
  const target = banTarget.value
  if (!target) return
  const form = banFormRef.value
  if (form) {
    const valid = await form.validate().catch(() => false)
    if (!valid) return
  }

  banSubmitting.value = true
  try {
    await banPlayer(target.player_id, {
      reason: banForm.reason.trim(),
      duration_hours: banForm.mode === 'permanent' ? null : banForm.durationHours,
    })
    ElMessage.success(`已封禁 ${target.name || target.account}`)
    banDialogVisible.value = false
    await Promise.all([loadPlayers(), loadOverview()])
    await drawerRef.value?.reload()
  } catch (error) {
    reportError(error, '封禁失败')
  } finally {
    banSubmitting.value = false
  }
}

/** 解封（二次确认 + 可选原因）。 */
async function handleUnban(player: PlayerSummary | PlayerDetail): Promise<void> {
  let reason = ''
  try {
    const input = await ElMessageBox.prompt(
      `确定解封「${player.name || player.account}」吗？可填写解封原因。`,
      '解封确认',
      {
        confirmButtonText: '解封',
        cancelButtonText: '取消',
        inputPlaceholder: '解封原因（可留空）',
        inputValidator: (value: string) => (value ?? '').length <= 200 || '原因不能超过 200 个字符',
        type: 'warning',
      },
    )
    reason = (input.value ?? '').trim()
  } catch {
    return
  }

  try {
    await unbanPlayer(player.player_id, { reason })
    ElMessage.success(`已解封 ${player.name || player.account}`)
    await Promise.all([loadPlayers(), loadOverview()])
    await drawerRef.value?.reload()
  } catch (error) {
    reportError(error, '解封失败')
  }
}

/** 表格"更多"下拉：打开预留查询入口。 */
function handleMoreCommand(command: string, player: PlayerSummary): void {
  openDrawer(player, command)
}

/**
 * 给某一行生成"更多"下拉的处理函数。
 *
 * 写成返回函数的工厂，而不是在模板里写内联箭头：Element Plus 的 `command`
 * 事件没有参数类型（`...args: any[]`），内联箭头会让 `command` 变成隐式 any，
 * 在 `strict` 下过不了 `vue-tsc`。
 */
function moreCommandHandler(
  player: PlayerSummary,
): (command: string | number | object) => void {
  return (command) => handleMoreCommand(String(command), player)
}

onMounted(async () => {
  await Promise.all([loadPlayers(), loadOverview()])
})
</script>

<template>
  <div class="page-container">
    <!-- 概览 -->
    <el-row :gutter="16">
      <el-col v-for="card in overviewCards" :key="card.label" :xs="24" :sm="8">
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
      title="玩家数据源不可用"
      :description="`${sourceError}（请检查管理平台到玩家库 db_scmj 的连接配置）`"
    />

    <!-- 查询条件 -->
    <el-card shadow="never">
      <el-form :inline="true" @submit.prevent="handleSearch">
        <el-form-item label="关键字">
          <el-input
            v-model="query.keyword"
            placeholder="账号 / 昵称 / 玩家ID"
            clearable
            style="width: 220px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="封禁状态">
          <el-select v-model="query.ban_state" style="width: 130px">
            <el-option label="全部" value="all" />
            <el-option label="封禁中" value="banned" />
            <el-option label="正常" value="normal" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-select v-model="query.ordering" style="width: 150px">
            <el-option label="ID 从大到小" value="-userid" />
            <el-option label="ID 从小到大" value="userid" />
            <el-option label="房卡从多到少" value="-gems" />
            <el-option label="金币从多到少" value="-coins" />
            <el-option label="等级从高到低" value="-lv" />
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
        <el-table-column prop="player_id" label="玩家ID" width="100" />
        <el-table-column prop="account" label="账号" min-width="150" show-overflow-tooltip />
        <el-table-column prop="name" label="昵称" min-width="120" show-overflow-tooltip />
        <el-table-column prop="lv" label="等级" width="70" />
        <el-table-column prop="coins" label="金币" width="90" />
        <el-table-column label="房卡" width="100">
          <template #default="{ row }: { row: PlayerSummary }">
            <el-tag :type="row.gems > 0 ? 'warning' : 'info'" effect="light" size="small">
              {{ row.gems }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="房间" width="100">
          <template #default="{ row }: { row: PlayerSummary }">
            {{ row.roomid || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="150">
          <template #default="{ row }: { row: PlayerSummary }">
            <el-tag v-if="row.banned" type="danger" size="small" effect="dark">
              {{ row.ban?.expires_at ? '限时封禁' : '永久封禁' }}
            </el-tag>
            <el-tag v-else type="success" size="small" effect="light">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }: { row: PlayerSummary }">
            <el-button link type="primary" size="small" @click="openDrawer(row)">详情</el-button>
            <el-button
              v-if="canManage && !row.banned"
              link
              type="danger"
              size="small"
              @click="openBanDialog(row)"
            >
              封禁
            </el-button>
            <el-button
              v-if="canManage && row.banned"
              link
              type="success"
              size="small"
              @click="handleUnban(row)"
            >
              解封
            </el-button>
            <el-dropdown trigger="click" @command="moreCommandHandler(row)">
              <el-button link type="primary" size="small">
                更多<el-icon><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="games">对局记录</el-dropdown-item>
                  <el-dropdown-item command="recharges">充值记录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="没有符合条件的玩家" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="player-pagination"
        :total="result.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadPlayers"
        @size-change="handleSearch"
      />
    </el-card>

    <!-- 详情 / 预留入口 -->
    <PlayerDetailDrawer
      ref="drawerRef"
      v-model="drawerVisible"
      :player-id="drawerPlayerId"
      :initial-tab="drawerTab"
      :can-manage="canManage"
      @ban="openBanDialog"
      @unban="handleUnban"
    />

    <!-- 封禁弹窗 -->
    <el-dialog v-model="banDialogVisible" title="封禁玩家" width="460px">
      <el-form ref="banFormRef" :model="banForm" :rules="banRules" label-width="90px">
        <el-form-item label="玩家">
          <span>
            {{ banTarget?.name || '—' }}
            <el-text size="small" type="info">（{{ banTarget?.account }} / ID {{ banTarget?.player_id }}）</el-text>
          </span>
        </el-form-item>
        <el-form-item label="封禁时长">
          <el-radio-group v-model="banForm.mode">
            <el-radio value="permanent">永久</el-radio>
            <el-radio value="hours">限时</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="banForm.mode === 'hours'" label="小时数" prop="durationHours">
          <el-input-number v-model="banForm.durationHours" :min="1" :max="8760" />
        </el-form-item>
        <el-form-item label="封禁原因" prop="reason">
          <el-input
            v-model="banForm.reason"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="例如：使用外挂 / 恶意挂机"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="banDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="banSubmitting" @click="submitBan">确认封禁</el-button>
      </template>
    </el-dialog>
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

.player-pagination {
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
