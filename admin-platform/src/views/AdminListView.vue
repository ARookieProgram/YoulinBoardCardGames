<script setup lang="ts">
/**
 * 管理员账号管理。
 *
 * 页面能力：
 *  1. **查询**——按账号 / 昵称 / 邮箱搜索，按角色与状态过滤，分页；
 *  2. **新建**——账号名 / 昵称 / 邮箱 / 口令 / 角色 / 备注，新建后即为启用状态；
 *  3. **改资料与角色**——账号名不可改（登录日志与令牌里有它的快照）；
 *  4. **启用 / 停用**——停用后该账号立刻登不进来（后端同步 `is_active`）；
 *  5. **重置口令**——超级管理员给他人重置；改完目标账号需要重新登录；
 *  6. **删除**——物理删除（只想禁用请用状态开关）。
 *
 * 权限：本页在路由里已标 `requiresSuperAdmin`，后端 `/api/admins/` 也只对
 * 超级管理员开放。**前端置灰不是防线**：两条自锁护栏（不能对自己动手、
 * 不能动最后一个启用中的超级管理员）都在服务端实现，见 `views_admin.py`。
 */

import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'

import {
  ADMIN_ORDERING_OPTIONS,
  ADMIN_ROLE_OPTIONS,
  createAdmin,
  deleteAdmin,
  getAdminsOverview,
  listAdmins,
  resetAdminPassword,
  setAdminStatus,
  updateAdmin,
} from '@/api/admins'
import { ApiError } from '@/api/errors'
import { ErrorCode } from '@/api/types'
import type {
  AdminRoleFilter,
  AdminStatusFilter,
  AdminUser,
  AdminsOverview,
  PageResult,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

/** 当前登录管理员的 id：用来标记"本人"并置灰危险操作。 */
const selfId = computed(() => auth.admin?.id ?? null)

/** 查询条件。 */
const query = reactive({
  keyword: '',
  role: 'all' as AdminRoleFilter,
  status: 'all' as AdminStatusFilter,
  ordering: '-created_at',
})

const page = ref(1)
const pageSize = ref(20)

/** 列表结果。 */
const result = ref<PageResult<AdminUser>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  pages: 0,
})
const loading = ref(false)

/** 概览数字。 */
const overview = ref<AdminsOverview | null>(null)

/** 提交中标记（防止连点）。 */
const submitting = ref(false)

/** 新建弹窗。 */
const createVisible = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({
  username: '',
  nickname: '',
  email: '',
  password: '',
  role: 'operator' as AdminUser['role'],
  remark: '',
})

const createRules: FormRules<typeof createForm> = {
  username: [
    { required: true, message: '请输入账号', trigger: 'blur' },
    { max: 150, message: '账号最长 150 个字符', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    {
      min: 8,
      message: '密码至少 8 位，且不能是纯数字或与账号太像',
      trigger: 'blur',
    },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

/** 编辑弹窗。 */
const editVisible = ref(false)
const editFormRef = ref<FormInstance>()
const editTarget = ref<AdminUser | null>(null)
const editForm = reactive({
  nickname: '',
  email: '',
  role: 'operator' as AdminUser['role'],
  remark: '',
})

const editRules: FormRules<typeof editForm> = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

/** 重置口令弹窗。 */
const passwordVisible = ref(false)
const passwordFormRef = ref<FormInstance>()
const passwordTarget = ref<AdminUser | null>(null)
const passwordForm = reactive({
  newPassword: '',
  confirmPassword: '',
})

const passwordRules: FormRules<typeof passwordForm> = {
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位，且不能是纯数字或与账号太像', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback: (error?: Error) => void) => {
        if (value !== passwordForm.newPassword) {
          callback(new Error('两次输入的密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

/** 概览卡片。 */
const overviewCards = computed(() => [
  {
    label: '管理员总数',
    value: overview.value ? String(overview.value.total_admins) : '—',
    tip: 'accounts_adminuser 表的实时计数',
  },
  {
    label: '启用中',
    value: overview.value ? String(overview.value.active_admins) : '—',
    tip: '被停用的账号立刻登不进来',
  },
  {
    label: '已停用',
    value: overview.value ? String(overview.value.disabled_admins) : '—',
    tip: '停用只挡登录，不删除任何记录',
  },
  {
    label: '超级管理员',
    value: overview.value ? String(overview.value.super_admins) : '—',
    tip: '按 effective_role 口径统计（含 is_superuser 的历史行）',
  },
])

/** 角色展示名：按 `effective_role` 取值。 */
function roleLabel(admin: AdminUser): string {
  return ADMIN_ROLE_OPTIONS.find((item) => item.value === admin.effective_role)?.label ?? admin.role_display
}

/**
 * 是否是"角色字段与权限口径不一致"的历史行。
 *
 * `is_superuser=true` 但 `role` 还停在旧值的账号，权限按超级管理员算，
 * 列表上标出来，避免运营以为它只是个运营号。
 */
function isLegacyRole(admin: AdminUser): boolean {
  return admin.effective_role !== admin.role
}

/** 是不是自己。 */
function isSelf(admin: AdminUser): boolean {
  return selfId.value !== null && admin.id === selfId.value
}

/** 统一错误提示。 */
function reportError(error: unknown, fallback: string): void {
  if (error instanceof ApiError) {
    ElMessage.error(error.message)
    return
  }
  ElMessage.error(fallback)
}

/** 拉列表。 */
async function loadAdmins(): Promise<void> {
  loading.value = true
  try {
    result.value = await listAdmins({
      keyword: query.keyword.trim(),
      role: query.role,
      status: query.status,
      ordering: query.ordering,
      page: page.value,
      page_size: pageSize.value,
    })
  } catch (error) {
    result.value = { items: [], total: 0, page: page.value, page_size: pageSize.value, pages: 0 }
    reportError(error, '管理员列表加载失败')
  } finally {
    loading.value = false
  }
}

/** 拉概览（失败不阻塞列表）。 */
async function loadOverview(): Promise<void> {
  try {
    overview.value = await getAdminsOverview()
  } catch (error) {
    overview.value = null
    reportError(error, '概览数据加载失败')
  }
}

/** 条件变化后回到第一页再查。 */
function handleSearch(): void {
  page.value = 1
  void loadAdmins()
}

/** 重置查询条件。 */
function handleReset(): void {
  query.keyword = ''
  query.role = 'all'
  query.status = 'all'
  query.ordering = '-created_at'
  page.value = 1
  pageSize.value = 20
  void loadAdmins()
}

// ---------------------------------------------------------------- 新建

/** 打开新建弹窗。 */
function openCreate(): void {
  createForm.username = ''
  createForm.nickname = ''
  createForm.email = ''
  createForm.password = ''
  createForm.role = 'operator'
  createForm.remark = ''
  createVisible.value = true
}

/** 提交新建。 */
async function submitCreate(): Promise<void> {
  const form = createFormRef.value
  if (form) {
    const valid = await form.validate().catch(() => false)
    if (!valid) return
  }

  submitting.value = true
  try {
    const created = await createAdmin({
      username: createForm.username.trim(),
      nickname: createForm.nickname.trim(),
      email: createForm.email.trim(),
      password: createForm.password,
      role: createForm.role,
      remark: createForm.remark.trim(),
    })
    ElMessage.success(`已创建 ${created.username}（${roleLabel(created)}）`)
    createVisible.value = false
    await Promise.all([loadAdmins(), loadOverview()])
  } catch (error) {
    reportError(error, '创建失败')
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 编辑

/** 打开编辑弹窗。 */
function openEdit(admin: AdminUser): void {
  editTarget.value = admin
  editForm.nickname = admin.nickname
  editForm.email = admin.email
  editForm.role = admin.role
  editForm.remark = admin.remark
  editVisible.value = true
}

/** 提交编辑。 */
async function submitEdit(): Promise<void> {
  const target = editTarget.value
  if (!target) return
  const form = editFormRef.value
  if (form) {
    const valid = await form.validate().catch(() => false)
    if (!valid) return
  }

  submitting.value = true
  try {
    await updateAdmin(target.id, {
      nickname: editForm.nickname.trim(),
      email: editForm.email.trim(),
      role: editForm.role,
      remark: editForm.remark.trim(),
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await Promise.all([loadAdmins(), loadOverview()])
  } catch (error) {
    reportError(error, '保存失败')
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 启用 / 停用

/** 切换启用状态（二次确认）。 */
async function toggleStatus(admin: AdminUser): Promise<void> {
  const disabling = admin.status === 'active'
  const action = disabling ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(
      disabling
        ? `确定停用「${admin.display_name}」吗？该账号将立刻无法登录管理平台。`
        : `确定启用「${admin.display_name}」吗？`,
      `${action}确认`,
      { confirmButtonText: action, cancelButtonText: '取消', type: disabling ? 'warning' : 'info' },
    )
  } catch {
    return
  }

  try {
    await setAdminStatus(admin.id, { status: disabling ? 'disabled' : 'active' })
    ElMessage.success(`已${action} ${admin.username}`)
    await Promise.all([loadAdmins(), loadOverview()])
  } catch (error) {
    reportError(error, `${action}失败`)
  }
}

// ---------------------------------------------------------------- 重置口令

/** 打开重置口令弹窗。 */
function openResetPassword(admin: AdminUser): void {
  passwordTarget.value = admin
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
  passwordVisible.value = true
}

/** 提交重置口令。 */
async function submitResetPassword(): Promise<void> {
  const target = passwordTarget.value
  if (!target) return
  const form = passwordFormRef.value
  if (form) {
    const valid = await form.validate().catch(() => false)
    if (!valid) return
  }

  submitting.value = true
  try {
    const data = await resetAdminPassword(target.id, { new_password: passwordForm.newPassword })
    ElMessage.success(
      `已重置 ${target.username} 的密码` +
        (data.revoked_tokens > 0 ? `，该账号 ${data.revoked_tokens} 个登录态已失效` : ''),
    )
    passwordVisible.value = false
  } catch (error) {
    reportError(error, '重置密码失败')
  } finally {
    submitting.value = false
  }
}

// ---------------------------------------------------------------- 删除

/** 删除（二次确认 + 明确说明是物理删除）。 */
async function handleDelete(admin: AdminUser): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除「${admin.display_name}（${admin.username}）」吗？` +
        '删除后该账号无法登录、也不能再恢复（只想禁用请用状态开关）。' +
        '历史上由他执行的玩家封禁记录会保留，操作人显示为账号名快照。',
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'error' },
    )
  } catch {
    return
  }

  try {
    await deleteAdmin(admin.id)
    ElMessage.success(`已删除 ${admin.username}`)
    // 删掉的可能就是当前页最后一行，回到第一页更稳妥。
    page.value = 1
    await Promise.all([loadAdmins(), loadOverview()])
  } catch (error) {
    reportError(error, '删除失败')
  }
}

onMounted(async () => {
  await Promise.all([loadAdmins(), loadOverview()])
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
      type="info"
      show-icon
      :closable="false"
      title="管理员账号与玩家账号是两套体系"
      description="这里管理的是管理平台账号（accounts_adminuser），玩家账号在游戏账号服，两边无法互相登录。"
    />

    <!-- 查询条件 -->
    <el-card shadow="never">
      <el-form :inline="true" @submit.prevent="handleSearch">
        <el-form-item label="关键字">
          <el-input
            v-model="query.keyword"
            placeholder="账号 / 昵称 / 邮箱"
            clearable
            style="width: 200px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="query.role" style="width: 140px">
            <el-option label="全部" value="all" />
            <el-option v-for="item in ADMIN_ROLE_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" style="width: 120px">
            <el-option label="全部" value="all" />
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序">
          <el-select v-model="query.ordering" style="width: 170px">
            <el-option
              v-for="item in ADMIN_ORDERING_OPTIONS"
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
      <div class="table-toolbar">
        <el-button type="primary" @click="openCreate">新建管理员</el-button>
        <el-text size="small" type="info">
          新建的账号默认启用；口令强度由后端按 Django 的口令校验器判定。
        </el-text>
      </div>

      <el-table v-loading="loading" :data="result.items" border stripe>
        <el-table-column prop="username" label="账号" min-width="140" show-overflow-tooltip>
          <template #default="{ row }: { row: AdminUser }">
            <span>{{ row.username }}</span>
            <el-tag v-if="isSelf(row)" type="primary" size="small" effect="plain" class="row-tag">本人</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="nickname" label="昵称" min-width="110" show-overflow-tooltip>
          <template #default="{ row }: { row: AdminUser }">
            {{ row.nickname || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="角色" width="170">
          <template #default="{ row }: { row: AdminUser }">
            <el-tag
              :type="row.effective_role === 'super_admin' ? 'danger' : row.effective_role === 'admin' ? 'warning' : 'info'"
              size="small"
              effect="light"
            >
              {{ roleLabel(row) }}
            </el-tag>
            <el-tooltip
              v-if="isLegacyRole(row)"
              content="该行的 role 字段还是旧值，但 is_superuser 为真，权限按 effective_role（超级管理员）计算"
            >
              <el-tag type="warning" size="small" effect="plain" class="row-tag">按权限口径</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }: { row: AdminUser }">
            <el-tag v-if="row.status === 'active'" type="success" size="small" effect="light">启用</el-tag>
            <el-tag v-else type="danger" size="small" effect="dark">停用</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column prop="remark" label="备注" min-width="130" show-overflow-tooltip>
          <template #default="{ row }: { row: AdminUser }">
            {{ row.remark || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="最后登录" width="160">
          <template #default="{ row }: { row: AdminUser }">
            {{ row.last_login || '从未登录' }}
          </template>
        </el-table-column>
        <el-table-column label="最后登录IP" width="130">
          <template #default="{ row }: { row: AdminUser }">
            {{ row.last_login_ip || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }: { row: AdminUser }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" size="small" @click="openResetPassword(row)">重置密码</el-button>
            <el-tooltip
              v-if="isSelf(row)"
              content="不能停用或删除自己的账号（避免把自己锁在门外）"
              placement="top"
            >
              <span>
                <el-button link type="warning" size="small" disabled>停用</el-button>
              </span>
            </el-tooltip>
            <el-button
              v-else-if="row.status === 'active'"
              link
              type="warning"
              size="small"
              @click="toggleStatus(row)"
            >
              停用
            </el-button>
            <el-button v-else link type="success" size="small" @click="toggleStatus(row)">启用</el-button>
            <el-tooltip v-if="isSelf(row)" content="不能删除自己的账号" placement="top">
              <span>
                <el-button link type="danger" size="small" disabled>删除</el-button>
              </span>
            </el-tooltip>
            <el-button v-else link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="没有符合条件的管理员" />
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="admin-pagination"
        :total="result.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        background
        @current-change="loadAdmins"
        @size-change="handleSearch"
      />
    </el-card>

    <!-- 新建 -->
    <el-dialog v-model="createVisible" title="新建管理员" width="520px">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="90px">
        <el-form-item label="账号" prop="username">
          <el-input v-model="createForm.username" placeholder="登录用的账号，创建后不可修改" />
        </el-form-item>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="createForm.nickname" placeholder="展示名，可留空" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="createForm.email" placeholder="唯一，用于找回账号" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="createForm.password"
            type="password"
            show-password
            placeholder="至少 8 位，不能是纯数字或与账号太像"
          />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option
              v-for="item in ADMIN_ROLE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注" prop="remark">
          <el-input
            v-model="createForm.remark"
            type="textarea"
            :rows="2"
            maxlength="200"
            show-word-limit
            placeholder="例如：客服组小王，2025-03 入职"
          />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="createForm.role === 'super_admin'"
        type="warning"
        show-icon
        :closable="false"
        title="超级管理员可以管理其它管理员账号，请谨慎授予。"
      />

      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 -->
    <el-dialog v-model="editVisible" title="编辑管理员" width="520px">
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="90px">
        <el-form-item label="账号">
          <el-text>{{ editTarget?.username }}</el-text>
          <el-text size="small" type="info" class="form-hint">（账号名不可修改）</el-text>
        </el-form-item>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="editForm.nickname" placeholder="展示名，可留空" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="editForm.email" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="editForm.role" :disabled="editTarget ? isSelf(editTarget) : false" style="width: 100%">
            <el-option
              v-for="item in ADMIN_ROLE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
          <el-text v-if="editTarget && isSelf(editTarget)" size="small" type="info">
            不能给自己降级（避免把最后一个超级管理员降掉）
          </el-text>
        </el-form-item>
        <el-form-item label="备注" prop="remark">
          <el-input v-model="editForm.remark" type="textarea" :rows="2" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置口令 -->
    <el-dialog v-model="passwordVisible" title="重置密码" width="460px">
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-width="100px">
        <el-form-item label="管理员">
          <span>{{ passwordTarget?.display_name }}<el-text size="small" type="info">（{{ passwordTarget?.username }}）</el-text></span>
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirmPassword">
          <el-input v-model="passwordForm.confirmPassword" type="password" show-password />
        </el-form-item>
      </el-form>
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        title="重置后该账号已登录的设备会立刻失去续期能力，需要用新密码重新登录。"
      />

      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitResetPassword">确认重置</el-button>
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

.table-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.row-tag {
  margin-left: 6px;
}

.form-hint {
  margin-left: 6px;
}

.admin-pagination {
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
