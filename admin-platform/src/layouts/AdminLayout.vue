<script setup lang="ts">
/**
 * 后台骨架：左侧菜单 + 顶栏 + 内容区。
 *
 * 只有登录后的页面会套这个布局（登录页在路由表里是独立顶层路由）。
 * 菜单由 `utils/menu.ts` 从路由表派生，角色不足的项自动隐藏。
 *
 * 顶栏的账号下拉里有两件事：**改自己的口令**（任何角色都能用，走
 * `ChangePasswordDialog` → `POST /api/admins/me/password/`）与退出登录。
 */

import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useAuthStore } from '@/stores/auth'
import { buildMenuItems } from '@/utils/menu'
import { LOGIN_PATH } from '@/router/routes'
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** 侧边栏折叠状态（窄屏时手动收起）。 */
const collapsed = ref(false)

/** 「修改密码」弹窗。 */
const passwordVisible = ref(false)

/** 当前高亮的菜单项：用路由名，避免 `system/admins` 这类多级路径的匹配问题。 */
const activeMenu = computed(() => String(route.name ?? ''))

/** 菜单项，按当前角色过滤。 */
const menuItems = computed(() => buildMenuItems(auth.isSuperAdmin))

/** 顶栏展示的角色标签颜色（按权限口径的角色上色）。 */
const roleTagType = computed(() => {
  switch (auth.effectiveRole) {
    case 'super_admin':
      return 'danger'
    case 'admin':
      return 'warning'
    default:
      return 'info'
  }
})

/** 退出登录。 */
async function handleLogout(): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    // 用户点了取消。
    return
  }

  await auth.logout()
  ElMessage.success('已退出登录')
  await router.replace({ path: LOGIN_PATH })
}

/** 顶部下拉菜单的点击项。 */
async function handleCommand(command: string): Promise<void> {
  if (command === 'logout') {
    await handleLogout()
    return
  }
  if (command === 'password') {
    passwordVisible.value = true
  }
}
</script>

<template>
  <el-container class="admin-layout">
    <!-- 侧边栏 -->
    <el-aside class="admin-aside" :width="collapsed ? '64px' : '220px'">
      <div class="admin-logo">
        <span class="admin-logo__mark">麒</span>
        <span v-show="!collapsed" class="admin-logo__text">麻将管理平台</span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        class="admin-menu"
        router
      >
        <el-menu-item v-for="item in menuItems" :key="item.name" :index="item.name" :route="{ path: item.path }">
          <el-icon v-if="item.icon">
            <component :is="item.icon" />
          </el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <!-- 顶栏 -->
      <el-header class="admin-header">
        <div class="admin-header__left">
          <el-button text :aria-label="collapsed ? '展开菜单' : '收起菜单'" @click="collapsed = !collapsed">
            <el-icon><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.meta.title">{{ route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="admin-header__right">
          <el-tag :type="roleTagType" size="small" effect="light">
            {{ auth.roleDisplay }}
          </el-tag>

          <el-dropdown @command="handleCommand">
            <span class="admin-user">
              <el-avatar :size="28" class="admin-user__avatar">
                {{ auth.displayName.slice(0, 1) }}
              </el-avatar>
              <span class="admin-user__name">{{ auth.displayName }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ auth.admin?.username ?? '' }}
                </el-dropdown-item>
                <el-dropdown-item command="password">
                  <el-icon><Lock /></el-icon>
                  修改密码
                </el-dropdown-item>
                <el-dropdown-item divided command="logout">
                  <el-icon><SwitchButton /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 内容区 -->
      <el-main class="admin-main">
        <RouterView />
      </el-main>
    </el-container>

    <!-- 「修改密码」弹窗（任何角色都能改自己的口令） -->
    <ChangePasswordDialog v-model="passwordVisible" />
  </el-container>
</template>

<style scoped>
.admin-layout {
  height: 100%;
}

.admin-aside {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: #ffffff;
  border-right: 1px solid var(--admin-border);
  transition: width 0.2s ease;
}

.admin-logo {
  display: flex;
  flex-shrink: 0;
  gap: 10px;
  align-items: center;
  height: var(--admin-header-height);
  padding: 0 16px;
  overflow: hidden;
  border-bottom: 1px solid var(--admin-border);
}

.admin-logo__mark {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
  background: linear-gradient(135deg, #409eff, #2f7fd8);
  border-radius: 8px;
}

.admin-logo__text {
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
}

.admin-menu {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  border-right: none;
}

.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--admin-header-height);
  padding: 0 16px;
  background-color: #ffffff;
  border-bottom: 1px solid var(--admin-border);
}

.admin-header__left,
.admin-header__right {
  display: flex;
  gap: 12px;
  align-items: center;
}

.admin-user {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 4px;
  outline: none;
  transition: background-color 0.2s;
}

.admin-user:hover {
  background-color: var(--admin-bg);
}

.admin-user__avatar {
  color: #ffffff;
  background-color: var(--admin-primary);
}

.admin-user__name {
  font-size: 14px;
  color: var(--admin-text);
}

.admin-main {
  padding: 0;
  overflow-y: auto;
  background-color: var(--admin-bg);
}
</style>
