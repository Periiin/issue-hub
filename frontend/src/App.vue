<template>
  <!-- 登录页这类独立页面不套壳：没有顶栏和底部导航 -->
  <router-view v-if="$route.meta?.bare" />
  <div v-else class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand" @click="$router.push('/issues')">
          <div class="logo">
            <span class="logo-dot" />
          </div>
          <div class="brand-text">
            <span class="brand-name">Issue Hub</span>
            <span class="brand-sub">甲方问题跟踪</span>
          </div>
        </div>

        <nav v-if="!isMobile" class="nav">
          <router-link to="/issues" class="nav-link" active-class="is-on">问题列表</router-link>
          <router-link to="/settings" class="nav-link" active-class="is-on">设置</router-link>
        </nav>

        <div class="topbar-right">
          <button class="search-btn" title="快速搜索（Ctrl+K）" @click="openQuickSearch">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
            </svg>
            <span v-if="!isMobile" class="search-kbd">Ctrl K</span>
          </button>
          <button class="theme-btn" :title="isDark ? '切换到浅色' : '切换到深色'" @click="toggleTheme">
            <!-- 浅色时显示月亮（点了变深色），深色时显示太阳 -->
            <svg v-if="!isDark" viewBox="0 0 24 24" width="18" height="18" fill="none"
                 stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none"
                 stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="12" r="4.2" />
              <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4" />
            </svg>
          </button>
          <el-button v-if="!isMobile" type="primary" round @click="goCreate">＋ 新建问题</el-button>

          <!-- 用户菜单：鉴权关闭时不显示 -->
          <el-dropdown v-if="user" trigger="click" @command="onUserCommand">
            <button class="user-btn">
              <span class="user-avatar">{{ avatarText }}</span>
              <span v-if="!isMobile" class="user-name">{{ user.displayName || user.username }}</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ user.username }}<span v-if="user.role === 'admin'"> · 管理员</span>
                </el-dropdown-item>
                <el-dropdown-item command="password" divided>修改密码</el-dropdown-item>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </header>

    <main class="content">
      <router-view />
    </main>

    <!-- 手机端底部导航 -->
    <nav v-if="isMobile" class="tabbar">
      <router-link to="/issues" class="tab" active-class="is-on">
        <span class="tab-icon">☰</span>
        <span class="tab-text">列表</span>
      </router-link>
      <button class="tab tab--main" @click="goCreate">
        <span class="tab-plus">＋</span>
        <span class="tab-text">新建</span>
      </button>
      <router-link to="/settings" class="tab" active-class="is-on">
        <span class="tab-icon">⚙</span>
        <span class="tab-text">设置</span>
      </router-link>
    </nav>

    <!-- Ctrl+K 快搜 -->
    <el-dialog
      v-model="quickOpen" width="560px" append-to-body
      :show-close="false" class="quick-dialog" @opened="focusQuick"
    >
      <input
        ref="quickInput" v-model="quickQ" class="quick-input"
        placeholder="搜标题 / 原文 / 模块…，或输入 #12 直达编号"
        @input="quickSearch" @keydown="onQuickKey"
      />
      <div class="quick-list">
        <div
          v-for="(item, i) in quickResults" :key="item.id"
          class="quick-item" :class="{ 'is-active': i === quickIndex }"
          @mouseenter="quickIndex = i" @click="goQuick(item.id)"
        >
          <span class="ih-mono ih-muted">#{{ item.id }}</span>
          <span class="quick-title">{{ item.title }}</span>
          <span :class="['pill', item.priority === 'P0' ? 'pill--p0' : item.priority === 'P1' ? 'pill--p1' : 'pill--p3']">
            {{ item.priority || '未定' }}
          </span>
          <span class="quick-status">{{ item.status }}</span>
        </div>
        <div v-if="!quickResults.length && quickQ" class="quick-empty ih-muted">没有匹配的问题</div>
        <div v-else-if="!quickQ" class="quick-empty ih-muted">
          输入关键词搜问题；输入 #编号 直接跳转；↑↓ 选择，回车打开
        </div>
      </div>
    </el-dialog>

    <!-- 修改自己的密码 -->
    <el-drawer v-model="pwdDrawer" title="修改密码" :size="isMobile ? '100%' : '400px'" append-to-body>
      <el-form label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="pwdNew" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="再输一次">
          <el-input v-model="pwdAgain" type="password" show-password @keyup.enter="savePassword" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDrawer = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="savePassword">保存</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword, clearToken, getMe, logout, type AuthUser } from './api'
import { useMobile } from './useMobile'
import { useTheme } from './useTheme'

const router = useRouter()
const route = useRoute()
const isMobile = useMobile()
const { isDark, toggle: toggleTheme } = useTheme()

/* ---------- 当前用户 ---------- */
const user = ref<AuthUser | null>(null)
const avatarText = computed(() => {
  const n = user.value?.displayName || user.value?.username || ''
  return n ? n.slice(0, 1).toUpperCase() : '?'
})

const loadMe = async () => {
  // 鉴权关闭时后端返回虚拟 admin（id=0），一样展示菜单（改密码会被后端拒绝）
  try {
    const r = await getMe()
    user.value = r.user || null
  } catch {
    user.value = null
  }
}

const onUserCommand = async (cmd: string) => {
  if (cmd === 'password') {
    pwdNew.value = ''
    pwdAgain.value = ''
    pwdDrawer.value = true
    return
  }
  if (cmd === 'logout') {
    try {
      await logout()
    } catch {
      /* 网络挂了也要能退出 */
    }
    clearToken()
    user.value = null
    ElMessage.success('已退出登录')
    router.replace('/login')
  }
}

/* ---------- Ctrl+K 快搜 ---------- */
const quickOpen = ref(false)
const quickQ = ref('')
const quickResults = ref<any[]>([])
const quickIndex = ref(0)
const quickInput = ref<HTMLInputElement | null>(null)

const openQuickSearch = () => {
  quickOpen.value = true
  quickQ.value = ''
  quickResults.value = []
  quickIndex.value = 0
}

const focusQuick = () => (quickInput.value as HTMLInputElement | null)?.focus()

const quickSearch = async () => {
  quickIndex.value = 0
  const q = quickQ.value.trim()
  if (!q) {
    quickResults.value = []
    return
  }
  const direct = /^#?(\d+)$/.exec(q)
  if (direct) {
    quickResults.value = [{ id: Number(direct[1]), title: '直接打开 #' + direct[1], priority: '', status: '' }]
    return
  }
  clearTimeout((quickSearch as any)._t)
  ;(quickSearch as any)._t = setTimeout(async () => {
    try {
      const { listIssues } = await import('./api')
      const r = await listIssues({ q, limit: 8 })
      quickResults.value = r.list || []
    } catch {
      quickResults.value = []
    }
  }, 250)
}

const goQuick = (id: number) => {
  quickOpen.value = false
  router.push(`/issues/${id}`)
}

const onQuickKey = (e: KeyboardEvent) => {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    quickIndex.value = Math.min(quickIndex.value + 1, quickResults.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    quickIndex.value = Math.max(0, quickIndex.value - 1)
  } else if (e.key === 'Enter') {
    const item = quickResults.value[quickIndex.value]
    if (item) goQuick(item.id)
  }
}

/** 全局 Ctrl/Cmd+K */
const onGlobalKey = (e: KeyboardEvent) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    openQuickSearch()
  }
}
window.addEventListener('keydown', onGlobalKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))

/* ---------- 改密码 ---------- */
const pwdDrawer = ref(false)
const pwdNew = ref('')
const pwdAgain = ref('')
const pwdSaving = ref(false)

const savePassword = async () => {
  if (!pwdNew.value || pwdNew.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (pwdNew.value !== pwdAgain.value) {
    ElMessage.warning('两次输入不一致')
    return
  }
  if (!user.value?.id) {
    ElMessage.warning('当前是本机免登录模式，没有可改的密码')
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(user.value.id, pwdNew.value)
    ElMessage.success('密码已修改')
    pwdDrawer.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    pwdSaving.value = false
  }
}

onMounted(loadMe)

// 登录页是 bare 布局，App.vue 那时已挂载但还没有 token；
// 登录成功跳走时组件不会重新挂载，所以跟着路由再拉一次。
watch(() => route.fullPath, () => {
  if (!user.value) loadMe()
})

/** 新建入口统一走列表页的弹窗（?new=1 由列表页消费） */
const goCreate = () => router.push({ path: '/issues', query: { new: '1' } })
</script>

<style scoped>
.shell { min-height: 100vh; padding-bottom: calc(64px + env(safe-area-inset-bottom)); }
@media (min-width: 769px) { .shell { padding-bottom: 0; } }

.topbar {
  position: sticky; top: 0; z-index: 20;
  background: var(--ih-topbar);
  backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--ih-line);
  transition: background-color 0.2s ease, border-color 0.2s ease;
}
.topbar-inner {
  max-width: 1120px; margin: 0 auto; padding: 0 20px;
  height: 60px; display: flex; align-items: center; gap: 20px;
}
.brand { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.logo {
  width: 32px; height: 32px; border-radius: 10px;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 14px rgba(79, 70, 229, 0.28);
}
.logo-dot { width: 10px; height: 10px; border-radius: 50%; background: #fff; opacity: 0.92; }
.brand-text { display: flex; flex-direction: column; line-height: 1.15; }
.brand-name { font-size: 16px; font-weight: 700; letter-spacing: 0.2px; color: var(--ih-ink); }
.brand-sub { font-size: 11px; color: var(--ih-sub); }

.nav { display: flex; gap: 6px; margin-left: 8px; }
.nav-link {
  padding: 7px 14px; border-radius: 999px; font-size: 14px;
  color: var(--ih-sub); text-decoration: none; transition: all 0.16s ease;
}
.nav-link:hover { background: var(--ih-soft); color: var(--ih-ink); }
.nav-link.is-on {
  background: var(--ih-primary-soft); color: var(--ih-primary); font-weight: 600;
}

.topbar-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }

/* 主题切换按钮 */
.theme-btn {
  width: 36px; height: 36px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--ih-line); background: var(--ih-card);
  color: var(--ih-sub); cursor: pointer; transition: all 0.16s ease;
}
.theme-btn:hover { color: var(--ih-primary); border-color: var(--ih-primary); transform: rotate(8deg); }
.theme-btn:active { transform: scale(0.94); }

/* Ctrl+K 快搜 */
.search-btn {
  display: inline-flex; align-items: center; gap: 6px;
  height: 36px; padding: 0 10px; border-radius: 999px;
  border: 1px solid var(--ih-line); background: var(--ih-card);
  color: var(--ih-sub); cursor: pointer; transition: all 0.16s ease;
}
.search-btn:hover { color: var(--ih-primary); border-color: var(--ih-primary); }
.search-kbd {
  font-size: 10.5px; padding: 1px 6px; border-radius: 6px;
  border: 1px solid var(--ih-line); background: var(--ih-soft); color: var(--ih-sub);
}
.quick-input {
  width: 100%; height: 44px; padding: 0 14px; font-size: 14px;
  border: 1px solid var(--ih-primary); border-radius: 12px; outline: none;
  background: var(--ih-surface); color: var(--ih-ink);
}
.quick-list { margin-top: 10px; max-height: 340px; overflow: auto; }
.quick-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 10px; cursor: pointer; font-size: 13px;
}
.quick-item.is-active { background: var(--ih-soft); }
.quick-title { flex: 1 1 auto; min-width: 0; color: var(--ih-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.quick-status { font-size: 11px; color: var(--ih-sub); }
.quick-empty { padding: 18px; text-align: center; font-size: 12.5px; }
.pill { font-size: 10.5px; padding: 1px 8px; border-radius: 999px; font-weight: 600; }
.pill--p0 { background: rgba(240,68,56,.12); color: #f04438; }
.pill--p1 { background: rgba(247,144,9,.14); color: #f79009; }
.pill--p3 { background: var(--ih-chip); color: var(--ih-sub); }

/* 用户菜单按钮 */
.user-btn {
  display: inline-flex; align-items: center; gap: 7px;
  height: 36px; padding: 0 10px 0 4px; border-radius: 999px;
  border: 1px solid var(--ih-line); background: var(--ih-card);
  color: var(--ih-ink); cursor: pointer; transition: all 0.16s ease;
}
.user-btn:hover { border-color: var(--ih-primary); }
.user-avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600; color: #fff;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
}
.user-name { font-size: 13px; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.content { max-width: 1400px; margin: 0 auto; padding: 20px; }
/* 列表页内容比详情页窄，单独收一下，避免表格被拉得过长 */
.content:has(.list-page) { max-width: 1180px; }

/* ---------- 手机底部导航 ---------- */
.tabbar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
  display: flex; align-items: stretch;
  padding-bottom: env(safe-area-inset-bottom);
  background: var(--ih-tabbar);
  backdrop-filter: saturate(180%) blur(12px);
  border-top: 1px solid var(--ih-line);
  transition: background-color 0.2s ease, border-color 0.2s ease;
}
.tab {
  flex: 1; height: 56px; border: none; background: transparent;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; color: var(--ih-sub); text-decoration: none; font-size: 11px;
  -webkit-appearance: none;
}
.tab.is-on { color: var(--ih-primary); }
.tab-icon { font-size: 18px; line-height: 1; }
.tab-text { font-size: 11px; }
.tab--main { position: relative; top: -12px; flex: 0 0 72px; }
.tab-plus {
  width: 48px; height: 48px; border-radius: 50%;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  color: #fff; font-size: 26px; line-height: 46px; text-align: center;
  box-shadow: 0 10px 22px rgba(79, 70, 229, 0.35);
}
.tab--main .tab-text { color: var(--ih-primary); font-weight: 600; margin-top: 2px; }

@media (max-width: 768px) {
  .topbar-inner { height: 52px; padding: 0 14px; gap: 10px; }
  .content { padding: 14px 12px 20px; }
}
</style>
