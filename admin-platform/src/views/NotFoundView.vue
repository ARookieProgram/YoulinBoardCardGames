<script setup lang="ts">
/**
 * 404 页面。
 *
 * 标记为 `meta.public`，因为未登录用户输错地址时也应该看到"页面不存在"，
 * 而不是被守卫绕一圈丢到登录页（那样会让人以为是登录问题）。
 */

import { useRouter } from 'vue-router'
import { HOME_PATH } from '@/router/routes'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <el-result icon="warning" title="404" sub-title="抱歉，你访问的页面不存在">
      <template #extra>
        <el-button type="primary" @click="router.replace(HOME_PATH)">返回控制台</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100%;
}
</style>
