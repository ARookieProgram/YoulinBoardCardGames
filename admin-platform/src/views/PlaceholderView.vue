<script setup lang="ts">
/**
 * 未开发页面的占位视图。
 *
 * 侧边栏的"玩家管理 / 房间管理 / 对局记录 / 管理员账号"目前都指向这里，
 * 目的是先把**路由结构、登录守卫与布局**跑通；接口接入时把这些路由的
 * `component` 换成真实页面即可，不用动其它任何地方。
 */

import { useRoute } from 'vue-router'

const route = useRoute()

const title = String(route.meta.title ?? '该功能')
</script>

<template>
  <div class="page-container">
    <el-card shadow="never">
      <el-empty :description="`${title} 正在开发中`">
        <el-text size="small" type="info">
          该页面的路由与登录守卫已就绪，等待接入后端接口。
        </el-text>
      </el-empty>
    </el-card>
  </div>
</template>

<style scoped>
.page-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - var(--admin-header-height));
}
</style>
