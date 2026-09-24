<script setup lang="ts">
/**
 * 控制台。
 *
 * 登录成功后的落地页。本期只展示"当前登录的是谁"与后续要接的模块清单，
 * 让登录闭环可验证；数据看板等业务内容在后续迭代里补。
 */

import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime, formatIp } from '@/utils/format'

const auth = useAuthStore()

/** 当前管理员的简要信息，用于信息卡片。 */
const profile = computed(() => [
  { label: '账号', value: auth.admin?.username ?? '—' },
  { label: '昵称', value: auth.admin?.nickname || '—' },
  { label: '邮箱', value: auth.admin?.email ?? '—' },
  { label: '角色', value: auth.admin?.role_display ?? '—' },
  { label: '账号状态', value: auth.admin?.status_display ?? '—' },
  { label: '最后登录', value: formatDateTime(auth.admin?.last_login) },
  { label: '登录 IP', value: formatIp(auth.admin?.last_login_ip) },
  { label: '创建时间', value: formatDateTime(auth.admin?.created_at) },
])

/** 后续要接的模块，标出本期是否已完成。 */
const roadmap = [
  { title: '登录与账号体系', description: '管理员登录、JWT 续期、退出、路由守卫', done: true },
  { title: '玩家管理', description: '查询玩家、展示房卡/金币、封禁解封，并预留对局与充值记录入口', done: true },
  { title: '房间管理', description: '查看在线房间、强制解散', done: false },
  { title: '对局记录', description: '战绩查询、异常对局审计', done: false },
  { title: '管理员账号', description: '增删改管理平台账号、分配角色（仅超级管理员）', done: false },
  { title: '运营配置', description: '公告、渠道、机器人策略', done: false },
]
</script>

<template>
  <div class="page-container">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>欢迎回来，{{ auth.displayName }}</span>
          <el-tag type="success" size="small" effect="light">已登录</el-tag>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item v-for="item in profile" :key="item.label" :label="item.label">
          {{ item.value }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>平台建设进度</span>
          <el-text size="small" type="info">本期交付登录闭环与玩家管理</el-text>
        </div>
      </template>

      <el-timeline>
        <el-timeline-item
          v-for="item in roadmap"
          :key="item.title"
          :type="item.done ? 'success' : 'info'"
          :hollow="!item.done"
        >
          <div class="roadmap-item">
            <span class="roadmap-item__title">{{ item.title }}</span>
            <el-tag v-if="item.done" type="success" size="small" effect="light">已完成</el-tag>
            <el-tag v-else size="small" effect="plain" type="info">待开发</el-tag>
          </div>
          <div class="roadmap-item__desc">{{ item.description }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.roadmap-item {
  display: flex;
  gap: 8px;
  align-items: center;
}

.roadmap-item__title {
  font-weight: 500;
}

.roadmap-item__desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--admin-text-secondary);
}
</style>
