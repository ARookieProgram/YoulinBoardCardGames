<script setup lang="ts">
/**
 * 「修改密码」弹窗 —— 当前登录管理员改自己的口令。
 *
 * 走的是 `POST /api/admins/me/password/`（`/api/admins/` 下唯一不要求
 * 超级管理员的端点），必须带**原口令**。
 *
 * 改完之后后端会把该账号已签发的 refresh 令牌全部拉黑，所以这里**主动登出**
 * 并跳回登录页：继续留在一个"下一次刷新必然失败"的页面里只会让人困惑。
 * （access 是 JWT、无状态，在过期前仍然有效——这是 JWT 的固有边界。）
 */

import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { changeMyPassword } from '@/api/admins'
import { ApiError } from '@/api/errors'
import { LOGIN_PATH } from '@/router/routes'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  /** 弹窗是否可见（v-model）。 */
  modelValue: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
}>()

const router = useRouter()
const auth = useAuthStore()

/** 弹窗可见性。 */
const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const rules: FormRules<typeof form> = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位，且不能是纯数字或与账号太像', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback: (error?: Error) => void) => {
        if (value !== form.newPassword) {
          callback(new Error('两次输入的密码不一致'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

/** 关闭时清空表单（避免下次打开还留着上次输入的密码）。 */
function resetForm(): void {
  form.oldPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''
  formRef.value?.clearValidate()
}

/** 提交。 */
async function submit(): Promise<void> {
  const instance = formRef.value
  if (instance) {
    const valid = await instance.validate().catch(() => false)
    if (!valid) return
  }

  submitting.value = true
  try {
    await changeMyPassword({
      old_password: form.oldPassword,
      new_password: form.newPassword,
    })
    visible.value = false
    resetForm()
    ElMessage.success('密码已修改，请用新密码重新登录')
    // 后端已吊销本账号的 refresh 令牌：本地登录态必须一起清掉。
    auth.reset()
    await router.replace({ path: LOGIN_PATH })
  } catch (error) {
    if (error instanceof ApiError) {
      ElMessage.error(error.message)
    } else {
      ElMessage.error('修改密码失败')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="修改密码"
    width="440px"
    @closed="resetForm"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="账号">
        <el-text>{{ auth.admin?.username }}</el-text>
      </el-form-item>
      <el-form-item label="原密码" prop="oldPassword">
        <el-input v-model="form.oldPassword" type="password" show-password autocomplete="current-password" />
      </el-form-item>
      <el-form-item label="新密码" prop="newPassword">
        <el-input v-model="form.newPassword" type="password" show-password autocomplete="new-password" />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirmPassword">
        <el-input v-model="form.confirmPassword" type="password" show-password autocomplete="new-password" />
      </el-form-item>
    </el-form>
    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="改完密码后需要重新登录：服务端会吊销该账号已签发的刷新令牌。"
    />

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认修改</el-button>
    </template>
  </el-dialog>
</template>
