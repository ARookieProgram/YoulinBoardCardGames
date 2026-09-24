<script setup lang="ts">
/**
 * 登录页。
 *
 * 这是**管理平台唯一的登录入口**，认证对象是 `AdminUser`（管理平台自己的
 * 账号表），与游戏客户端的玩家账号体系完全隔离——玩家账号在这里一定登不进去。
 *
 * 交互要点：
 *  - 表单校验用 Element Plus 的 `FormRules`，账号/口令都必填且限长；
 *  - 提交中禁用按钮并显示 loading，避免重复提交；
 *  - 支持回车提交、Shift+Tab 等键盘操作（`@keyup.enter`）；
 *  - 登录成功后回到 `?redirect=` 指定的页面，没有则进控制台；
 *  - 失败时把后端的中文文案原样提示（后端已统一口径，不暴露账号是否存在）。
 */

import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'

import { ApiError, NetworkError } from '@/api/errors'
import { health } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { HOME_PATH } from '@/router/routes'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

/** 表单实例，用于触发校验与聚焦。 */
const formRef = ref<FormInstance>()

/** 登录表单数据。 */
const form = reactive({
  username: '',
  password: '',
})

/** 是否正在提交。 */
const submitting = ref(auth.pending)

/** 后端是否可达（不可达时给出更明确的提示，而不是让用户猜口令错了没）。 */
const backendUp = ref(true)

const rules: FormRules<typeof form> = {
  username: [
    { required: true, message: '请输入账号', trigger: 'blur' },
    { min: 2, max: 150, message: '账号长度为 2–150 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码长度为 6–128 个字符', trigger: 'blur' },
  ],
}

/** 目标跳转地址：只接受站内单斜杠路径，防开放重定向。 */
function resolveRedirect(): string {
  const raw = route.query.redirect
  const target = Array.isArray(raw) ? raw[0] : raw
  if (typeof target !== 'string' || target === '') return HOME_PATH
  if (!target.startsWith('/') || target.startsWith('//')) return HOME_PATH
  return target
}

/** 提交登录。 */
async function handleSubmit(): Promise<void> {
  const instance = formRef.value
  if (!instance) return

  const valid = await instance.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const admin = await auth.login({
      username: form.username.trim(),
      password: form.password,
    })
    ElMessage.success(`欢迎回来，${admin.display_name}`)
    await router.replace(resolveRedirect())
  } catch (error) {
    if (error instanceof NetworkError) {
      backendUp.value = false
      ElMessage.error(error.message)
    } else if (error instanceof ApiError) {
      // 后端文案已经统一（口令错误不区分账号是否存在），直接展示。
      ElMessage.error(error.message)
      // 口令错误时清空口令并聚焦，方便重试。
      form.password = ''
    } else {
      ElMessage.error('登录失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}

// 进页面时探一次后端是否可达。失败不阻塞登录（可能是暂时的网络抖动），
// 只是把提示条显示出来，省得用户对着"账号或密码错误"反复试。
onMounted(async () => {
  try {
    await health()
    backendUp.value = true
  } catch {
    backendUp.value = false
  }
})
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand">
        <div class="login-brand__mark">麒</div>
        <h1 class="login-brand__title">麻将管理平台</h1>
        <p class="login-brand__subtitle">四川麻将 · 运营后台</p>
      </div>

      <el-alert
        v-if="!backendUp"
        class="login-alert"
        type="error"
        show-icon
        :closable="false"
        title="无法连接后端服务"
        description="请确认 platform_server 已启动（默认 http://127.0.0.1:8000）。"
      />

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        size="large"
        :disabled="submitting"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="账号" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入管理员账号"
            autocomplete="username"
            clearable
            :prefix-icon="User"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
            show-password
            :prefix-icon="Lock"
            @keyup.enter="handleSubmit"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            class="login-submit"
            type="primary"
            size="large"
            :loading="submitting"
            native-type="submit"
            @click="handleSubmit"
          >
            {{ submitting ? '登录中…' : '登 录' }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <el-text size="small" type="info">
          管理平台账号与游戏账号相互独立，游戏账号无法登录此处
        </el-text>
      </div>
    </div>

    <div class="login-copyright">
      © {{ new Date().getFullYear() }} 麒麟游戏 · 管理后台
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100%;
  padding: 24px;
  background:
    radial-gradient(circle at 15% 20%, rgb(64 158 255 / 18%), transparent 45%),
    radial-gradient(circle at 85% 80%, rgb(47 127 216 / 16%), transparent 45%),
    linear-gradient(135deg, #eef4fd 0%, #f7f9fc 55%, #eaf1fb 100%);
}

.login-card {
  box-sizing: border-box;
  width: 100%;
  max-width: 400px;
  padding: 36px 32px 24px;
  background-color: #ffffff;
  border-radius: 12px;
  box-shadow:
    0 12px 32px rgb(31 45 61 / 10%),
    0 2px 8px rgb(31 45 61 / 6%);
}

.login-brand {
  margin-bottom: 24px;
  text-align: center;
}

.login-brand__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  margin-bottom: 12px;
  font-size: 26px;
  font-weight: 700;
  color: #ffffff;
  background: linear-gradient(135deg, #409eff, #2f7fd8);
  border-radius: 14px;
}

.login-brand__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--admin-text);
}

.login-brand__subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--admin-text-secondary);
}

.login-alert {
  margin-bottom: 16px;
}

.login-submit {
  width: 100%;
  letter-spacing: 2px;
}

.login-footer {
  margin-top: 8px;
  text-align: center;
}

.login-copyright {
  margin-top: 24px;
  font-size: 12px;
  color: var(--admin-text-secondary);
}
</style>
