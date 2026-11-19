<template>
  <div class="login-page">
    <div class="login-card ih-card">
      <div class="brand">
        <div class="logo"><span class="logo-dot" /></div>
        <div class="brand-text">
          <span class="brand-name">Issue Hub</span>
          <span class="brand-sub">甲方问题跟踪</span>
        </div>
      </div>

      <form class="form" @submit.prevent="submit">
        <label class="field">
          <span class="field-label">用户名</span>
          <el-input v-model="username" placeholder="请输入用户名" size="large" autofocus />
        </label>
        <label class="field">
          <span class="field-label">密码</span>
          <el-input
            v-model="password" type="password" show-password size="large"
            placeholder="请输入密码" @keyup.enter="submit"
          />
        </label>

        <div v-if="error" class="error">{{ error }}</div>

        <el-button
          type="primary" size="large" class="submit"
          :loading="loading" native-type="submit"
        >登录</el-button>
      </form>

      <p class="hint">
        首次使用请用服务端日志里的初始 admin 账号登录，登录后请立即改密码。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getAuthMode, login, setToken } from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

const submit = async () => {
  if (!username.value.trim() || !password.value) {
    error.value = '请填写用户名和密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const res = await login(username.value.trim(), password.value)
    setToken(res.token)
    ElMessage.success(`欢迎，${res.user.displayName}`)
    // 记住上次要去的页面
    const next = new URLSearchParams(location.search).get('next') || '/issues'
    router.replace(next)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '登录失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 鉴权没开（单人本机）：不用登录，直接进去
  try {
    const mode = await getAuthMode()
    if (!mode.enabled) router.replace('/issues')
  } catch {
    /* 拿不到就当需要登录 */
  }
})
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(900px 400px at 50% -10%, var(--ih-hero-glow-a), transparent 70%),
    var(--ih-bg);
}
.login-card {
  width: 100%;
  max-width: 380px;
  padding: 32px 28px;
}
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
.logo {
  width: 40px; height: 40px; border-radius: 12px;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 8px 18px rgba(79, 70, 229, 0.28);
}
.logo-dot { width: 12px; height: 12px; border-radius: 50%; background: #fff; opacity: 0.92; }
.brand-text { display: flex; flex-direction: column; line-height: 1.2; }
.brand-name { font-size: 18px; font-weight: 700; color: var(--ih-ink); }
.brand-sub { font-size: 12px; color: var(--ih-sub); }

.form { display: flex; flex-direction: column; gap: 16px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field-label { font-size: 13px; color: var(--ih-sub); }
.error {
  padding: 8px 12px; border-radius: 10px; font-size: 13px;
  background: rgba(240, 68, 56, 0.1); color: #f04438;
}
.submit { width: 100%; margin-top: 4px; }
.hint {
  margin: 20px 0 0; font-size: 12px; line-height: 1.6;
  color: var(--ih-sub); text-align: center;
}

@media (max-width: 480px) {
  .login-card { padding: 24px 20px; }
}
</style>
