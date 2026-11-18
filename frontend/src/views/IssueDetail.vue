<template>
  <div v-if="issue" class="detail-layout">
    <!-- ================= 左栏：问题本身（只读为主） ================= -->
    <div class="detail-main">
      <!-- 头图 -->
      <section class="hero ih-card">
        <div class="hero-top">
          <div class="hero-main">
            <div class="hero-eyebrow">
              <span class="ih-mono">#{{ issue.id }}</span>
              <span class="status"><i :class="['dot', dotClass(issue.status)]" />{{ issue.status }}</span>
            </div>
            <h1 class="hero-title">{{ issue.title }}</h1>
            <div class="hero-meta">
              <span v-if="issue.reporter">提出人 {{ issue.reporter }}</span>
              <span v-if="issue.module">模块 {{ issue.module }}</span>
              <span>创建 {{ issue.created_at }}</span>
            </div>
            <!-- 所属项目：选定后代码范围与可改仓库都从这里带出 -->
            <div class="project-row">
              <span class="project-label">项目</span>
              <el-select
                v-model="projectId" clearable placeholder="未指定项目" class="project-select"
                @change="changeProject"
              >
                <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id"
                           :disabled="p.ignored">
                  <span>{{ p.name }}</span>
                  <span class="opt-repos">{{ p.repos.length }} 个仓库</span>
                </el-option>
              </el-select>
              <span v-if="currentProject" class="project-hint">
                {{ currentProject.repos.map((r) => r.split(/[\\/]/).pop()).join(' · ') }}
              </span>
              <el-button link type="primary" class="project-jump" @click="$router.push('/settings')">
                管理项目
              </el-button>
            </div>
          </div>
          <div class="hero-side">
            <div class="hero-badges">
              <span :class="priorityClass(issue.priority)">{{ issue.priority || '未定级' }}</span>
              <span v-if="issue.severity" class="badge badge--soft">{{ issue.severity }}</span>
              <span v-if="issue.complexity" class="badge badge--ghost">{{ issue.complexity }}</span>
            </div>
            <div class="hero-actions">
              <el-select v-model="issue.status" class="status-select" @change="changeStatus">
                <el-option v-for="s in allStatus" :key="s" :label="s" :value="s" />
              </el-select>
              <el-button round @click="exportMd">导出</el-button>
              <el-button round type="danger" plain @click="removeIssue">删除</el-button>
            </div>
          </div>
        </div>
      </section>

      <!-- 原始描述 + 附件 -->
      <section class="panel ih-card">
        <div class="panel-head is-toggle" @click="toggleSection('raw')">
          <div class="panel-title">
            <span class="step-badge step-badge--gray">原</span>
            <div>
              <h2>原始描述</h2>
              <p v-if="sections.raw">甲方原话与截图，粘贴即上传</p>
              <p v-else class="fold-summary">
                {{ rawText ? rawText.slice(0, 40) + (rawText.length > 40 ? '…' : '') : '（无文字）' }}
                <span v-if="attachments.length" class="ih-muted">· {{ attachments.length }} 个附件</span>
              </p>
            </div>
          </div>
          <div class="panel-actions" @click.stop>
            <input ref="fileInput" type="file" accept="image/*,application/pdf" multiple hidden @change="onPickFiles" />
            <el-button round @click="fileInput?.click()">选择文件</el-button>
            <el-button round type="primary" plain :loading="uploading" :disabled="!pendingFiles.length" @click="uploadNow">
              上传{{ pendingFiles.length ? `(${pendingFiles.length})` : '' }}
            </el-button>
          </div>
          <span class="fold-arrow" :class="{ 'is-open': sections.raw }" />
        </div>

        <div v-show="sections.raw" class="fold-body">
          <el-input
            v-model="rawText" type="textarea" :rows="4" resize="none"
            placeholder="甲方原话；截图可以直接 Ctrl+V 粘贴"
            class="raw-input" @paste="onPaste" @blur="saveRawText"
          />
          <div v-if="attachments.length" class="thumbs">
            <div v-for="a in attachments" :key="a.id" class="thumb">
              <el-image
                v-if="isImage(a)" :src="fileUrl(a.path)" :preview-src-list="imageUrls"
                fit="cover" class="thumb-img" preview-teleported
              />
              <a v-else :href="fileUrl(a.path)" target="_blank" class="file-link">PDF</a>
              <button class="thumb-del" @click.stop="removeAttachment(a)">×</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ① AI 定性 -->
      <section class="panel ih-card">
        <div class="panel-head is-toggle" @click="toggleSection('qualify')">
          <div class="panel-title">
            <span class="step-badge">1</span>
            <div>
              <h2>AI 定性</h2>
              <p v-if="sections.qualify">把口语化成结构化描述，人工确认后才进入定级</p>
              <p v-else class="fold-summary">
                <i :class="['fold-dot', issue.qualify_final ? 'is-done' : 'is-todo']" />
                {{ issue.qualify_final ? '已确认' : '尚未确认' }}
                <span v-if="issue.qualify_final?.phenomenon" class="ih-muted">
                  · {{ issue.qualify_final.phenomenon.slice(0, 30) }}
                </span>
              </p>
            </div>
          </div>
          <div class="panel-actions" @click.stop>
            <el-select v-model="provider" class="provider-select">
              <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
            </el-select>
            <el-button type="primary" round :loading="qualifying" @click="doQualify">
              {{ issue.qualify_final ? '重新定性' : 'AI 定性' }}
            </el-button>
          </div>
          <span class="fold-arrow" :class="{ 'is-open': sections.qualify }" />
        </div>

        <div v-show="sections.qualify" class="fold-body">
          <el-form label-position="top" class="qualify-form">
            <el-form-item label="标题"><el-input v-model="q.title" /></el-form-item>
            <el-form-item label="现象">
              <el-input v-model="q.phenomenon" type="textarea" :rows="2" resize="none" />
            </el-form-item>
            <el-form-item label="复现步骤">
              <el-input v-model="q.repro_text" type="textarea" :rows="3" resize="none" placeholder="一行一步" />
            </el-form-item>
            <div class="two-col">
              <el-form-item label="期望结果">
                <el-input v-model="q.expected" type="textarea" :rows="2" resize="none" />
              </el-form-item>
              <el-form-item label="实际结果">
                <el-input v-model="q.actual" type="textarea" :rows="2" resize="none" />
              </el-form-item>
            </div>
            <div class="two-col">
              <el-form-item label="影响范围">
                <el-input v-model="q.scope" type="textarea" :rows="2" resize="none" />
              </el-form-item>
              <el-form-item label="待确认点">
                <el-input v-model="q.uncertain_text" type="textarea" :rows="2" resize="none" placeholder="一行一条" />
              </el-form-item>
            </div>
            <el-form-item label="归属模块"><el-input v-model="q.module" /></el-form-item>
          </el-form>
          <div class="panel-foot">
            <el-button type="success" round :loading="confirming" @click="doConfirm">
              确认定性，进入定级
            </el-button>
          </div>
        </div>
      </section>

      <!-- ② AI 定级 -->
      <section class="panel ih-card">
        <div class="panel-head is-toggle" @click="toggleSection('triage')">
          <div class="panel-title">
            <span class="step-badge">2</span>
            <div>
              <h2>AI 定级</h2>
              <p v-if="sections.triage">影响等级、修复复杂度、优先级，可手动修正</p>
              <p v-else class="fold-summary">
                <template v-if="issue.priority">
                  <span :class="priorityClass(issue.priority)">{{ issue.priority }}</span>
                  <span class="ih-muted">{{ issue.severity || '-' }} · {{ issue.complexity || '-' }}</span>
                </template>
                <span v-else class="ih-muted">未定级</span>
              </p>
            </div>
          </div>
          <div class="panel-actions" @click.stop>
            <el-button type="primary" round :loading="triaging" @click="doTriage">生成定级</el-button>
          </div>
          <span class="fold-arrow" :class="{ 'is-open': sections.triage }" />
        </div>

        <div v-show="sections.triage" class="fold-body">
          <div class="triage-grid">
            <div class="triage-cell">
              <span class="triage-label">影响等级</span>
              <el-select v-model="issue.severity" clearable placeholder="S1-S4" @change="saveTriageManual">
                <el-option v-for="s in ['S1', 'S2', 'S3', 'S4']" :key="s" :label="s" :value="s" />
              </el-select>
            </div>
            <div class="triage-cell">
              <span class="triage-label">修复复杂度</span>
              <el-select v-model="issue.complexity" clearable placeholder="简单/中等/复杂" @change="saveTriageManual">
                <el-option v-for="s in ['简单', '中等', '复杂']" :key="s" :label="s" :value="s" />
              </el-select>
            </div>
            <div class="triage-cell">
              <span class="triage-label">优先级</span>
              <el-select v-model="issue.priority" clearable placeholder="P0-P3" @change="saveTriageManual">
                <el-option v-for="s in ['P0', 'P1', 'P2', 'P3']" :key="s" :label="s" :value="s" />
              </el-select>
            </div>
          </div>

          <div v-if="triage" class="triage-detail">
            <div v-if="triage.reasons?.length" class="reason-box">
              <h3>定级依据</h3>
              <ul><li v-for="(r, i) in triage.reasons" :key="i">{{ r }}</li></ul>
            </div>
            <div class="triage-meta">
              <span v-if="triage.suggested_owner">建议处理人：{{ triage.suggested_owner }}</span>
              <span v-if="triage.estimated_effort">预估：{{ triage.estimated_effort }}</span>
            </div>
            <div v-if="triage.risks?.length" class="reason-box reason-box--warn">
              <h3>风险点</h3>
              <ul><li v-for="(r, i) in triage.risks" :key="i">{{ r }}</li></ul>
            </div>
          </div>
          <el-empty v-else description="确认定性后点「生成定级」" :image-size="70" />
        </div>
      </section>

      <!-- 时间线 -->
      <section class="panel ih-card">
        <div class="panel-head is-toggle" @click="toggleSection('events')">
          <div class="panel-title">
            <span class="step-badge step-badge--gray">迹</span>
            <div>
              <h2>操作记录</h2>
              <p v-if="!sections.events" class="fold-summary ih-muted">{{ events.length }} 条</p>
            </div>
          </div>
          <span class="fold-arrow" :class="{ 'is-open': sections.events }" />
        </div>
        <div v-show="sections.events" class="fold-body">
          <el-timeline class="timeline">
            <el-timeline-item
              v-for="e in events" :key="e.id" :timestamp="e.created_at" placement="top"
              :color="e.type === 'status' ? '#7c3aed' : e.type === 'create' ? '#12b76a' : '#c7cbe0'"
            >
              <div class="event-line">
                <span class="event-type">{{ eventLabel(e.type) }}</span>
                <span v-if="e.from_status || e.to_status" class="ih-muted">
                  {{ e.from_status || '-' }} → {{ e.to_status || '-' }}
                </span>
                <span v-if="e.note" class="event-note">{{ e.note }}</span>
              </div>
            </el-timeline-item>
          </el-timeline>
        </div>
      </section>
    </div>

    <!-- ================= 右栏：操作台（宽屏） ================= -->
    <aside v-if="!isMobile" class="detail-side">
      <FixWorkbench :issue-id="id" :issue="issue" :provider="provider" :project-id="projectId" @changed="refresh" />
    </aside>

    <!-- 手机：折叠成底部抽屉 -->
    <template v-else>
      <button class="wb-fab" @click="workbenchOpen = true">
        <span class="wb-fab-icon">③</span>
        <span class="wb-fab-text">操作台</span>
        <span v-if="fabBadge" class="wb-fab-badge" :class="{ 'is-warn': fabBadge.warn }">{{ fabBadge.text }}</span>
      </button>
      <el-drawer
        v-model="workbenchOpen" direction="btt" size="92%"
        :with-header="false" append-to-body class="wb-drawer"
      >
        <div class="wb-drawer-bar">
          <span class="wb-drawer-title">操作台</span>
          <el-button link @click="workbenchOpen = false">收起</el-button>
        </div>
        <div class="wb-drawer-body">
          <FixWorkbench
            v-if="workbenchOpen" :issue-id="id" :issue="issue" :provider="provider"
            :project-id="projectId" @changed="refresh"
          />
        </div>
      </el-drawer>
    </template>
  </div>

  <div v-else class="loading-wrap"><el-skeleton :rows="8" animated /></div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import FixWorkbench from './FixWorkbench.vue'
import { useMobile } from '../useMobile'
import {
  confirmQualify, deleteAttachment, deleteIssue, fileUrl, getIssue, getProjects,
  getSettings, patchIssue, runQualify, runTriage, uploadAttachments, type Project
} from '../api'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))
const isMobile = useMobile()

const issue = ref<any>(null)
const attachments = ref<any[]>([])
const events = ref<any[]>([])
const allStatus = ref<string[]>([])
const providers = ref<string[]>(['mock', 'deepseek', 'dsh', 'claude'])
const provider = ref('mock')

const rawText = ref('')
const pendingFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const qualifying = ref(false)
const confirming = ref(false)
const triaging = ref(false)

const workbenchOpen = ref(false)

/* ===== 所属项目 ===== */
const projects = ref<Project[]>([])
const projectId = ref<number | null>(null)
const currentProject = computed(
  () => projects.value.find((p) => p.id === projectId.value) || null
)

const loadProjects = async () => {
  const r = await getProjects().catch(() => null)
  projects.value = r?.projects || []
}

/**
 * 切换项目：项目决定默认代码范围与可改仓库。
 * 换项目时清掉原来手填的 code_scopes / target_repos，否则会残留上一个项目的路径。
 */
const changeProject = async (val: number | null) => {
  await patchIssue(id.value, {
    project_id: val ?? 0,
    code_scopes: [],
    target_repos: []
  })
  if (issue.value) {
    issue.value.project_id = val
    issue.value.code_scopes = []
    issue.value.target_repos = []
  }
  ElMessage.success(val ? `已归属到「${currentProject.value?.name || ''}」` : '已取消项目归属')
  await refresh()
}

const q = reactive({
  title: '', phenomenon: '', repro_text: '', expected: '', actual: '',
  scope: '', module: '', uncertain_text: ''
})

const triage = computed(() => issue.value?.triage || null)

/* ===== 折叠：按状态给默认值，之后用户手动切换不被覆盖 ===== */
type SectionKey = 'raw' | 'qualify' | 'triage' | 'events'
const sections = reactive<Record<SectionKey, boolean>>({
  raw: true, qualify: true, triage: true, events: true
})
let defaultedIssue = 0

const toggleSection = (name: SectionKey) => {
  sections[name] = !sections[name]
}

const applySectionDefaults = () => {
  if (!issue.value || defaultedIssue === issue.value.id) return
  defaultedIssue = issue.value.id
  const st = issue.value.status || ''
  if (st === '待定性') {
    Object.assign(sections, { raw: true, qualify: true, triage: false, events: false })
  } else if (st === '待定级') {
    Object.assign(sections, { raw: true, qualify: false, triage: true, events: false })
  } else {
    // 待处理及之后：定性/定级收起，把空间留给时间线
    Object.assign(sections, { raw: true, qualify: false, triage: false, events: true })
  }
}

/* ===== 手机 FAB 角标（有待审改动或新出入时提示） ===== */
const fabBadge = computed(() => {
  const states = issue.value?.fix_state?.repos || {}
  const pending = Object.values(states).filter(
    (s: any) => s?.status === 'changed' && !s?.accepted
  ).length
  const attempts = issue.value?.attempts || []
  const first = attempts[0]
  const deviated = first &&
    ((first.deviations?.length || 0) + (first.found_issues?.length || 0) > 0)
  if (deviated) return { text: '有出入', warn: true }
  if (pending) return { text: `${pending} 待审`, warn: false }
  return null
})

/* ===== 展示辅助 ===== */
const imageUrls = computed(() =>
  attachments.value.filter((a) => (a.mime || '').startsWith('image/')).map((a) => fileUrl(a.path))
)
const priorityClass = (p: string | null) =>
  `pill ${p === 'P0' ? 'pill--p0' : p === 'P1' ? 'pill--p1' : p === 'P2' ? 'pill--p2' : p ? 'pill--p3' : 'pill--none'}`
const dotClass = (s: string) => {
  if (s === '待定性') return 'dot--draft'
  if (s === '待定级') return 'dot--triage'
  if (s === '待处理') return 'dot--todo'
  if (s === '处理中') return 'dot--doing'
  if (s === '待验收') return 'dot--accept'
  if (s === '已解决') return 'dot--done'
  return 'dot--drop'
}
const eventLabel = (t: string) =>
  ({ create: '新建', qualify: 'AI 定性', confirm: '人工确认', triage: 'AI 定级', fix: '生成方案',
     fix_apply: '开始修改', fix_accept: '采纳', fix_reject: '驳回',
     status: '状态变更', note: '备注' } as any)[t] || t
const isImage = (a: any) => (a.mime || '').startsWith('image/')

const fillQualifyForm = (data: any) => {
  if (!data) return
  q.title = data.title || ''
  q.phenomenon = data.phenomenon || ''
  q.repro_text = (data.repro_steps || []).join('\n')
  q.expected = data.expected || ''
  q.actual = data.actual || ''
  q.scope = data.scope || ''
  q.module = data.module || ''
  q.uncertain_text = (data.uncertainties || []).join('\n')
}

/* ===== 数据加载 ===== */
/** attempts 挂到 issue 上，右栏组件直接读，避免重复请求 */
const applyIssue = (res: any) => {
  res.issue.attempts = res.attempts || []
  issue.value = res.issue
  attachments.value = res.attachments || []
  events.value = res.events || []
  rawText.value = res.issue.raw_text || ''
  projectId.value = res.issue.project_id ?? null
}

const load = async () => {
  const res = await getIssue(id.value)
  applyIssue(res)
  fillQualifyForm(res.issue.qualify_final || res.issue.qualify_draft)
  applySectionDefaults()
}

/** 右栏操作后只刷新数据，不动折叠状态、不覆盖正在编辑的定性表单 */
const refresh = async () => {
  const res = await getIssue(id.value)
  const prevFinal = JSON.stringify(issue.value?.qualify_final || null)
  applyIssue(res)
  if (prevFinal !== JSON.stringify(res.issue.qualify_final || null)) {
    fillQualifyForm(res.issue.qualify_final || res.issue.qualify_draft)
  }
}

const saveRawText = async () => {
  if (!issue.value || rawText.value === (issue.value.raw_text || '')) return
  await patchIssue(id.value, { raw_text: rawText.value })
  issue.value.raw_text = rawText.value
}

const changeStatus = async (status: string) => {
  await patchIssue(id.value, { status })
  ElMessage.success(`状态已改为 ${status}`)
  await refresh()
}

const exportMd = () => window.open(`/api/issues/${id.value}/export`, '_blank')

/* ===== 定性 / 定级 ===== */
const doQualify = async () => {
  qualifying.value = true
  sections.qualify = true
  try {
    const res = await runQualify(id.value, provider.value)
    fillQualifyForm(res.draft)
    await refresh()
    ElMessage.success(`定性完成（${res.provider}，${res.durationMs}ms）`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '定性失败')
  } finally {
    qualifying.value = false
  }
}

const doConfirm = async () => {
  confirming.value = true
  try {
    await confirmQualify(id.value, {
      title: q.title,
      phenomenon: q.phenomenon,
      repro_steps: q.repro_text.split('\n').map((s) => s.trim()).filter(Boolean),
      expected: q.expected,
      actual: q.actual,
      scope: q.scope,
      module: q.module,
      uncertainties: q.uncertain_text.split('\n').map((s) => s.trim()).filter(Boolean),
      tags: []
    })
    await refresh()
    sections.qualify = false
    sections.triage = true
    ElMessage.success('已确认，进入待定级')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '确认失败')
  } finally {
    confirming.value = false
  }
}

const doTriage = async () => {
  triaging.value = true
  try {
    const res = await runTriage(id.value, provider.value)
    await refresh()
    ElMessage.success(`定级完成：${res.triage.priority} / ${res.triage.severity}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '定级失败')
  } finally {
    triaging.value = false
  }
}

const saveTriageManual = async () => {
  await patchIssue(id.value, {
    severity: issue.value.severity, complexity: issue.value.complexity, priority: issue.value.priority
  })
  ElMessage.success('已保存')
}

/* ===== 附件 ===== */
const onPaste = (e: ClipboardEvent) => {
  const files = Array.from(e.clipboardData?.files || [])
  if (files.length) {
    uploadAttachments(id.value, files).then(refresh)
    ElMessage.success(`已上传 ${files.length} 张截图`)
  }
}
const onPickFiles = (e: Event) => {
  const input = e.target as HTMLInputElement
  if (input.files?.length) pendingFiles.value.push(...Array.from(input.files))
  input.value = ''
}
const uploadNow = async () => {
  if (!pendingFiles.value.length) return
  uploading.value = true
  try {
    await uploadAttachments(id.value, pendingFiles.value)
    pendingFiles.value = []
    await refresh()
  } finally {
    uploading.value = false
  }
}
const removeAttachment = async (a: any) => {
  await deleteAttachment(id.value, a.id)
  await refresh()
}
const removeIssue = async () => {
  await ElMessageBox.confirm('删除后不可恢复，确认删除这条问题？', '提示', { type: 'warning' })
  await deleteIssue(id.value)
  router.push('/issues')
}

watch(() => route.params.id, async () => {
  defaultedIssue = 0
  workbenchOpen.value = false
  await load()
})

onMounted(async () => {
  const [s] = await Promise.all([
    getSettings().catch(() => null),
    loadProjects()
  ])
  if (s) providers.value = s.providers
  await load()
})
</script>

<style scoped>
/* ---------- 双栏布局 ---------- */
.detail-layout {
  display: grid;
  grid-template-columns: 1fr;
  gap: 14px;
  align-items: start;
}
/* 宽屏才切双栏：更窄的话右栏会挤得没法用 */
@media (min-width: 1280px) {
  .detail-layout {
    grid-template-columns: minmax(0, 1fr) 500px;
    gap: 16px;
  }
}
.detail-main { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.detail-side { min-width: 0; }

.loading-wrap { padding: 20px; }

/* ---------- 头图 ---------- */
.hero {
  padding: 20px 22px;
  background:
    radial-gradient(900px 240px at 100% -40%, var(--ih-hero-glow-a), transparent 70%),
    radial-gradient(700px 220px at -10% 120%, var(--ih-hero-glow-b), transparent 70%),
    var(--ih-card);
}
.hero-top { display: flex; justify-content: space-between; gap: 18px; flex-wrap: wrap; }
.hero-eyebrow { display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--ih-sub); }
.hero-title { margin: 8px 0 0; font-size: 26px; font-weight: 750; letter-spacing: -0.4px; line-height: 1.3; }
.hero-meta { display: flex; gap: 16px; margin-top: 10px; font-size: 12px; color: var(--ih-sub); flex-wrap: wrap; }
.hero-side { display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.hero-badges { display: flex; gap: 8px; align-items: center; }
.badge { padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.badge--soft { background: var(--ih-warn-soft); color: var(--ih-warn-ink); }
.badge--ghost { background: var(--ih-soft-2); color: var(--ih-sub); }
.hero-actions { display: flex; gap: 8px; align-items: center; }
.status-select { width: 120px; }

/* 所属项目 */
.project-row { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.project-label { font-size: 12px; color: var(--ih-sub); }
.project-select { width: 180px; }
.project-hint { font-size: 11.5px; color: var(--ih-sub); }
.project-jump { font-size: 12px; margin-left: auto; }
.opt-repos { float: right; margin-left: 12px; font-size: 11px; color: var(--ih-sub); }

/* ---------- 面板（含折叠） ---------- */
.panel { padding: 18px 20px; }
.panel-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 12px; flex-wrap: wrap; margin-bottom: 14px;
}
.panel-head.is-toggle {
  cursor: pointer; user-select: none; justify-content: flex-start; margin-bottom: 0;
}
.panel-head.is-toggle .panel-title { flex: 1 1 auto; min-width: 0; }
.panel-head.is-toggle:hover h2 { color: var(--el-color-primary); }
.fold-body { padding-top: 14px; }
.fold-arrow {
  flex: 0 0 auto; width: 9px; height: 9px; align-self: center;
  border-right: 2px solid var(--ih-sub); border-bottom: 2px solid var(--ih-sub);
  transform: rotate(-45deg); transition: transform 0.18s ease;
}
.fold-arrow.is-open { transform: rotate(45deg); }
.fold-summary {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin: 3px 0 0; font-size: 12px; color: var(--ih-ink);
}
.fold-dot { width: 7px; height: 7px; border-radius: 50%; }
.fold-dot.is-done { background: #12b76a; }
.fold-dot.is-todo { background: #f0a13c; }
.panel-title { display: flex; gap: 12px; align-items: flex-start; }
.panel-title h2 { margin: 0; font-size: 16px; font-weight: 700; }
.panel-title p { margin: 3px 0 0; font-size: 12px; color: var(--ih-sub); }
.step-badge {
  flex: 0 0 auto; width: 28px; height: 28px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  box-shadow: 0 6px 14px rgba(79, 70, 229, 0.25);
}
.step-badge--gray { background: var(--ih-soft-2); color: var(--ih-sub); box-shadow: none; }
.panel-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.panel-foot { display: flex; justify-content: flex-end; }
.provider-select { width: 130px; }

/* 原始描述 */
.raw-input :deep(.el-textarea__inner) { background: var(--ih-soft); }
.thumbs { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.thumb { position: relative; width: 96px; height: 96px; }
.thumb-img { width: 96px; height: 96px; border-radius: 12px; border: 1px solid var(--ih-line); }
.file-link {
  display: flex; width: 96px; height: 96px; border-radius: 12px;
  align-items: center; justify-content: center;
  background: var(--ih-soft-2); color: var(--ih-primary);
  text-decoration: none; font-weight: 600; font-size: 13px;
}
.thumb-del {
  position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; border-radius: 50%;
  border: none; background: rgba(16, 24, 40, 0.7); color: #fff;
  font-size: 12px; line-height: 20px; cursor: pointer;
}
html.dark .thumb-del { background: rgba(255, 255, 255, 0.9); color: #101828; }

/* 定性表单 */
.qualify-form :deep(.el-form-item) { margin-bottom: 12px; }
.qualify-form :deep(.el-form-item__label) { padding-bottom: 2px; font-size: 12px; color: var(--ih-sub); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

/* 定级 */
.triage-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.triage-cell {
  background: var(--ih-soft); border: 1px solid var(--ih-line); border-radius: 12px;
  padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
}
.triage-label { font-size: 12px; color: var(--ih-sub); }
.triage-detail { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.reason-box { background: var(--ih-soft); border-radius: 12px; padding: 12px 14px; }
.reason-box h3 { margin: 0 0 6px; font-size: 13px; color: var(--ih-ink); }
.reason-box ul { margin: 0; padding-left: 18px; font-size: 13px; color: var(--ih-sub); line-height: 1.7; }
.reason-box--warn { background: var(--ih-warn-soft); }
.reason-box--warn h3, .reason-box--warn ul { color: var(--ih-warn-ink); }
.triage-meta { display: flex; gap: 16px; font-size: 12px; color: var(--ih-sub); flex-wrap: wrap; }

/* 时间线 */
.timeline { padding-left: 4px; }
.event-line { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 13px; }
.event-type { font-weight: 600; color: var(--ih-ink); }
.event-note { color: var(--ih-sub); font-size: 12px; }

/* ---------- 手机 ---------- */
.wb-fab {
  position: fixed; right: 16px; bottom: calc(72px + env(safe-area-inset-bottom)); z-index: 40;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
  width: 62px; height: 62px; border: none; border-radius: 50%;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  color: #fff; box-shadow: 0 10px 24px rgba(79, 70, 229, 0.4); cursor: pointer;
}
.wb-fab:active { transform: scale(0.95); }
.wb-fab-icon { font-size: 15px; font-weight: 700; }
.wb-fab-text { font-size: 10px; }
.wb-fab-badge {
  position: absolute; top: -4px; right: -8px;
  padding: 1px 6px; border-radius: 999px; font-size: 10px; font-weight: 600;
  background: #fff; color: var(--ih-primary); box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}
.wb-fab-badge.is-warn { background: #f79009; color: #fff; }
.wb-drawer :deep(.el-drawer__body) { padding: 0; display: flex; flex-direction: column; }
.wb-drawer-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--ih-line);
  font-size: 14px; font-weight: 600; color: var(--ih-ink);
}
.wb-drawer-title { font-size: 14px; font-weight: 600; }
.wb-drawer-body { flex: 1; min-height: 0; overflow-y: auto; padding: 12px; }

@media (max-width: 768px) {
  .hero { padding: 16px; }
  .hero-title { font-size: 21px; }
  .hero-side { align-items: stretch; width: 100%; }
  .hero-actions { width: 100%; }
  .status-select { flex: 1; }
  .panel { padding: 14px; }
  .triage-grid { grid-template-columns: 1fr; }
  .two-col { grid-template-columns: 1fr; }
}
</style>
