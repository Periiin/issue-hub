<template>
  <section class="panel ih-card">
    <div class="panel-head">
      <div class="panel-title">
        <span class="step-badge step-badge--gray">👥</span>
        <div>
          <h2>账号</h2>
          <p>每人只能看到自己的问题、项目和通道；管理员可以管所有人和所有通道</p>
        </div>
      </div>
      <div class="panel-actions">
        <el-button v-if="accountTab === 'users'" round :loading="usersLoading" @click="loadUsers">刷新</el-button>
        <el-button v-if="accountTab === 'users'" type="primary" round @click="openCreateUser">＋ 新建用户</el-button>
        <el-button v-else round :loading="logsLoading" @click="loadLogs">刷新</el-button>
      </div>
    </div>

    <div class="acct-tabs">
      <button
        class="acct-tab" :class="{ 'is-on': accountTab === 'users' }"
        @click="switchAccountTab('users')"
      >用户管理 <span class="acct-count">{{ users.length }}</span></button>
      <button
        class="acct-tab" :class="{ 'is-on': accountTab === 'logs' }"
        @click="switchAccountTab('logs')"
      >登录记录 <span class="acct-count">{{ logs.total }}</span></button>
    </div>

    <!-- 用户管理 -->
    <div v-show="accountTab === 'users'" class="user-list">
      <div v-for="u in users" :key="u.id" class="user-row">
        <div class="user-main">
          <div class="user-name">
            {{ u.display_name || u.username }}
            <span class="user-role" :class="`is-${u.role}`">{{ u.role === 'admin' ? '管理员' : '普通' }}</span>
            <span v-if="!u.enabled" class="user-tag">已停用</span>
            <span v-if="me && u.id === me.id" class="user-tag is-me">当前登录</span>
          </div>
          <div class="user-account">
            <code>{{ u.username }}</code>
            <span v-if="u.created_at" class="ih-muted">创建于 {{ u.created_at }}</span>
          </div>
        </div>
        <div class="user-actions">
          <el-button size="small" round @click="openResetPassword(u)">改密码</el-button>
          <el-button
            size="small" round :disabled="me && u.id === me.id"
            @click="doToggleUser(u)"
          >{{ u.enabled ? '停用' : '启用' }}</el-button>
          <el-button
            size="small" round type="danger" plain :disabled="me && u.id === me.id"
            @click="doDeleteUser(u)"
          >删除</el-button>
        </div>
      </div>
      <div v-if="!users.length" class="ih-muted user-empty">
        还没有用户。
      </div>
    </div>

    <!-- 登录记录 -->
    <div v-show="accountTab === 'logs'" class="log-wrap">
      <div class="log-filter">
        <el-input
          v-model="logKeyword" placeholder="搜用户名 / IP / 归属地"
          clearable class="log-search" @keyup.enter="applyLogFilter"
        >
          <template #prefix><span class="log-search-icon">⌕</span></template>
        </el-input>
        <el-select v-model="logResult" placeholder="全部结果" clearable class="log-select" @change="applyLogFilter">
          <el-option label="登录成功" value="ok" />
          <el-option label="密码错误" value="bad_password" />
          <el-option label="用户不存在" value="no_user" />
          <el-option label="账号已停用" value="disabled" />
          <el-option label="被限流锁定" value="locked" />
          <el-option label="IP 不在白名单" value="bad_ip" />
          <el-option label="退出登录" value="logout" />
        </el-select>
        <el-button round @click="applyLogFilter">查询</el-button>
        <el-button round type="danger" plain class="log-clear" @click="doClearLogs">清空</el-button>
      </div>

      <!-- 桌面：表格 -->
      <div v-if="!isMobile" class="log-table-wrap">
        <table class="log-table">
          <thead>
            <tr>
              <th class="col-time">时间</th>
              <th class="col-user">账号</th>
              <th class="col-result">结果</th>
              <th class="col-ip">IP</th>
              <th class="col-region">归属地</th>
              <th class="col-agent">客户端</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in logs.items" :key="l.id">
              <td class="col-time">{{ l.created_at }}</td>
              <td class="col-user">
                <b>{{ l.display_name || l.username }}</b>
                <span v-if="l.display_name && l.display_name !== l.username" class="log-account">{{ l.username }}</span>
              </td>
              <td class="col-result">
                <span class="log-result" :class="l.success ? 'is-ok' : 'is-bad'">{{ l.resultLabel }}</span>
              </td>
              <td class="col-ip"><code>{{ l.ip || '—' }}</code></td>
              <td class="col-region">{{ l.ip_region || '—' }}</td>
              <td class="col-agent">
                <span class="log-agent" :title="l.user_agent">{{ shortAgent(l.user_agent) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!logs.items.length" class="ih-muted user-empty">没有匹配的登录记录。</div>
      </div>

      <!-- 手机：卡片 -->
      <div v-else class="log-cards">
        <div v-for="l in logs.items" :key="l.id" class="log-card">
          <div class="log-card-head">
            <span class="log-result" :class="l.success ? 'is-ok' : 'is-bad'">{{ l.resultLabel }}</span>
            <span class="log-time">{{ l.created_at }}</span>
          </div>
          <div class="log-card-user">{{ l.display_name || l.username }}</div>
          <div class="log-card-line">
            <code>{{ l.ip || '—' }}</code>
            <span class="log-region">{{ l.ip_region || '未知' }}</span>
          </div>
          <div v-if="l.user_agent" class="log-card-agent">{{ shortAgent(l.user_agent) }}</div>
        </div>
        <div v-if="!logs.items.length" class="ih-muted user-empty">没有匹配的登录记录。</div>
      </div>

      <div v-if="logs.total > logsPageSize" class="log-pager">
        <el-button size="small" round :disabled="logsPage === 0" @click="logsPrev">上一页</el-button>
        <span class="ih-muted">
          {{ logsPage + 1 }} / {{ Math.max(1, Math.ceil(logs.total / logsPageSize)) }} 页 · 共 {{ logs.total }} 条
        </span>
        <el-button size="small" round :disabled="logsPage + 1 >= Math.ceil(logs.total / logsPageSize)" @click="logsNext">下一页</el-button>
      </div>
    </div>

    <p v-if="accountTab === 'users'" class="field-hint user-hint">
      登录开关在「其他代码设置」里。开之前先确认已配好 IP 白名单，
      否则换网络就登不进来了。
    </p>
  </section>

  <!-- 用户编辑抽屉 -->
  <el-drawer
    v-model="userDrawer" :title="userForm.id ? '重置密码' : '新建用户'"
    :size="isMobile ? '100%' : '460px'" append-to-body
  >
    <el-form label-position="top">
      <template v-if="!userForm.id">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" placeholder="登录用，字母数字" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="userForm.display_name" placeholder="可选，列表里显示的名字" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="userForm.role">
            <el-radio-button value="user">普通</el-radio-button>
            <el-radio-button value="admin">管理员</el-radio-button>
          </el-radio-group>
          <div class="field-hint">
            管理员能看所有人的问题、管理用户和通道；普通用户只看自己的
          </div>
        </el-form-item>
      </template>
      <el-form-item :label="userForm.id ? `给 ${userForm.username} 设置新密码` : '密码'">
        <el-input
          v-model="userForm.password" type="password" show-password
          placeholder="至少 6 位" @keyup.enter="saveUser"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="userDrawer = false">取消</el-button>
      <el-button type="primary" :loading="userSaving" @click="saveUser">保存</el-button>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  changePassword, clearLoginLogs, createUser, deleteUser, getLoginLogs, getMe,
  listUsers, toggleUser,
  type AppUser, type AuthUser, type LoginLog
} from '../api'
import { useMobile } from '../useMobile'

const isMobile = useMobile()

/* ---------- 用户管理 ---------- */
const me = ref<AuthUser | null>(null)
const users = ref<AppUser[]>([])
const usersLoading = ref(false)
const userDrawer = ref(false)
const userSaving = ref(false)
const userForm = reactive<Record<string, any>>({
  id: 0, username: '', display_name: '', role: 'user', password: ''
})

const loadUsers = async () => {
  usersLoading.value = true
  try {
    const r = await listUsers()
    users.value = r.users || []
  } catch {
    users.value = []
  } finally {
    usersLoading.value = false
  }
}

const resetUserForm = () => {
  Object.assign(userForm, { id: 0, username: '', display_name: '', role: 'user', password: '' })
}

const openCreateUser = () => {
  resetUserForm()
  userDrawer.value = true
}

const openResetPassword = (u: AppUser) => {
  resetUserForm()
  Object.assign(userForm, { id: u.id, username: u.username })
  userDrawer.value = true
}

const saveUser = async () => {
  if (!userForm.password || userForm.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  userSaving.value = true
  try {
    if (userForm.id) {
      await changePassword(userForm.id, userForm.password)
      ElMessage.success('密码已重置')
    } else {
      if (!userForm.username.trim()) {
        ElMessage.warning('请填用户名')
        return
      }
      await createUser({
        username: userForm.username.trim(),
        password: userForm.password,
        display_name: userForm.display_name || userForm.username.trim(),
        role: userForm.role
      })
      ElMessage.success('用户已创建')
    }
    userDrawer.value = false
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    userSaving.value = false
  }
}

const doToggleUser = async (u: AppUser) => {
  await toggleUser(u.id, !u.enabled)
  await loadUsers()
  ElMessage.success(u.enabled ? '已停用' : '已启用')
}

const doDeleteUser = async (u: AppUser) => {
  await ElMessageBox.confirm(
    '删除用户「' + (u.display_name || u.username) + '」？他的问题会变成「无归属」，不会删除。',
    '提示', { type: 'warning' })
  await deleteUser(u.id)
  await loadUsers()
  ElMessage.success('已删除')
}

/* ---------- 登录记录 ---------- */
const accountTab = ref<'users' | 'logs'>('users')
const logs = reactive<{ items: LoginLog[]; total: number }>({ items: [], total: 0 })
const logsLoading = ref(false)
const logsPage = ref(0)
const logsPageSize = 30
const logKeyword = ref('')
const logResult = ref('')

const loadLogs = async () => {
  logsLoading.value = true
  try {
    const r = await getLoginLogs({
      limit: logsPageSize,
      offset: logsPage.value * logsPageSize,
      keyword: logKeyword.value.trim(),
      result: logResult.value || ''
    })
    logs.items = r.items || []
    logs.total = r.total || 0
  } catch {
    logs.items = []
    logs.total = 0
  } finally {
    logsLoading.value = false
  }
}

const applyLogFilter = () => {
  logsPage.value = 0
  loadLogs()
}

const logsPrev = () => {
  if (logsPage.value === 0) return
  logsPage.value -= 1
  loadLogs()
}

const logsNext = () => {
  if ((logsPage.value + 1) * logsPageSize >= logs.total) return
  logsPage.value += 1
  loadLogs()
}

const maxLogPage = computed(() => Math.max(1, Math.ceil(logs.total / logsPageSize)))

/** UA 太长，表格里只留浏览器+系统这种能看懂的部分 */
const shortAgent = (ua: string) => {
  if (!ua) return '—'
  const browser =
    /Edg\/([\d.]+)/.exec(ua)?.[0]?.replace('Edg/', 'Edge ') ||
    /Chrome\/([\d.]+)/.exec(ua)?.[0]?.replace('Chrome/', 'Chrome ') ||
    /Firefox\/([\d.]+)/.exec(ua)?.[0]?.replace('Firefox/', 'Firefox ') ||
    /Version\/([\d.]+).*Safari/.exec(ua)?.[0]?.replace(/Version\/([\d.]+).*/, 'Safari $1') ||
    ''
  // 顺序要紧：iPhone/iPad 的 UA 里也有 "Mac OS X"，必须先判 iOS
  const os = /Windows NT/.test(ua) ? 'Windows'
    : /iPhone|iPad|iPod/.test(ua) ? 'iOS'
    : /Android/.test(ua) ? 'Android'
    : /Macintosh|Mac OS X/.test(ua) ? 'macOS'
    : /Linux/.test(ua) ? 'Linux' : ''
  if (browser && os) return browser + ' · ' + os
  if (browser) return browser
  if (os) return os
  return ua.length > 28 ? ua.slice(0, 28) + '…' : ua
}

const switchAccountTab = (tab: 'users' | 'logs') => {
  accountTab.value = tab
  if (tab === 'logs' && !logs.items.length) loadLogs()
}

const doClearLogs = async () => {
  await ElMessageBox.confirm(
    '清空全部登录记录？这一步不能撤销，审计信息会永久丢失。',
    '提示', { type: 'warning' })
  const r = await clearLoginLogs()
  logsPage.value = 0
  await loadLogs()
  ElMessage.success('已清空 ' + (r.deleted ?? 0) + ' 条')
}

onMounted(async () => {
  const m = await getMe().catch(() => null)
  me.value = m?.user || null
  await loadUsers()
  await loadLogs()
})
</script>

<style scoped>
/* ===== 账号：tab 切换 ===== */
.acct-tabs {
  display: flex; gap: 6px; margin-bottom: 14px;
  padding: 4px; border-radius: 12px; background: var(--ih-soft);
  width: fit-content;
}
.acct-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border: none; border-radius: 9px;
  background: transparent; color: var(--ih-sub);
  font-size: 13px; font-weight: 500; cursor: pointer;
  transition: all 0.16s ease; -webkit-appearance: none;
}
.acct-tab:hover { color: var(--ih-ink); }
.acct-tab.is-on {
  background: var(--ih-card); color: var(--ih-primary); font-weight: 600;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.1);
}
.acct-count {
  min-width: 18px; padding: 0 5px; border-radius: 999px;
  font-size: 10.5px; font-weight: 600; line-height: 16px; text-align: center;
  background: var(--ih-chip); color: var(--ih-sub);
}
.acct-tab.is-on .acct-count { background: var(--ih-primary-soft); color: var(--ih-primary); }

/* ===== 登录记录 ===== */
.log-wrap { display: flex; flex-direction: column; gap: 10px; }
.log-filter { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.log-search { flex: 1 1 200px; min-width: 150px; }
.log-select { width: 130px; flex: 0 0 auto; }
.log-search-icon { color: var(--ih-sub); font-size: 13px; }

.log-table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--ih-line); }
.log-table {
  width: 100%; border-collapse: collapse; font-size: 12.5px;
  background: var(--ih-surface);
}
.log-table th {
  text-align: left; font-weight: 600; font-size: 11.5px; color: var(--ih-sub);
  padding: 9px 10px; border-bottom: 1px solid var(--ih-line);
  background: var(--ih-soft); white-space: nowrap;
}
.log-table td {
  padding: 9px 10px; border-bottom: 1px solid var(--ih-line);
  color: var(--ih-ink); vertical-align: middle;
}
.log-table tr:last-child td { border-bottom: none; }
.log-table tbody tr:hover { background: var(--ih-soft); }
.col-time { white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--ih-sub); }
.col-user { white-space: nowrap; }
.col-ip code { font-size: 12px; }
.col-region { color: var(--ih-sub); }
.log-account { margin-left: 5px; font-size: 11px; color: var(--ih-sub); }
.log-agent {
  display: inline-block; max-width: 150px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; color: var(--ih-sub); font-size: 11.5px;
}

.log-result {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 500; white-space: nowrap;
}
.log-result.is-ok { background: rgba(18, 183, 106, 0.12); color: #12b76a; }
.log-result.is-bad { background: rgba(240, 68, 56, 0.1); color: #f04438; }

.log-cards { display: flex; flex-direction: column; gap: 8px; }
.log-card {
  padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--ih-line); background: var(--ih-surface);
  display: flex; flex-direction: column; gap: 5px;
}
.log-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.log-time { font-size: 11px; color: var(--ih-sub); font-variant-numeric: tabular-nums; }
.log-card-user { font-size: 13.5px; font-weight: 600; color: var(--ih-ink); }
.log-card-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11.5px; }
.log-card-line code { font-size: 11.5px; color: var(--ih-ink); }
.log-region { color: var(--ih-sub); }
.log-card-agent { font-size: 11px; color: var(--ih-sub); }

.log-pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding-top: 4px; font-size: 12px; }

/* ===== 用户管理 ===== */
.user-list { display: flex; flex-direction: column; gap: 8px; }
.user-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--ih-line); background: var(--ih-surface);
}
.user-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.user-name {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 13.5px; font-weight: 600; color: var(--ih-ink);
}
.user-role {
  font-size: 10.5px; font-weight: 500; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-chip); color: var(--ih-sub);
}
.user-role.is-admin { background: rgba(79, 70, 229, 0.12); color: var(--ih-primary); }
.user-tag {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  background: rgba(240, 68, 56, 0.1); color: #f04438;
}
.user-tag.is-me { background: rgba(18, 183, 106, 0.12); color: #12b76a; }
.user-account {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 11.5px; color: var(--ih-sub);
}
.user-account code { font-size: 11.5px; color: var(--ih-ink); }
.user-actions { display: flex; gap: 6px; flex-shrink: 0; }
.user-empty { padding: 16px 12px; }
.user-hint { margin-top: 10px; }

@media (max-width: 768px) {
  /* 登录记录筛选：窄屏下输入框占满一行 */
  .acct-tabs { width: 100%; }
  .acct-tab { flex: 1; justify-content: center; }
  .log-search { flex: 1 1 100%; }
  .log-select { flex: 1 1 45%; width: auto; }
  .log-clear { flex: 0 0 auto; }

  /* 手机上按钮换行到下一行，避免挤压用户名 */
  .user-row { flex-direction: column; align-items: stretch; gap: 8px; }
  .user-actions { justify-content: flex-end; }
}
</style>
