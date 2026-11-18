<template>
  <div class="workbench ih-card">
    <!-- 头部：标题 + 主操作 -->
    <div class="wb-head">
      <div class="wb-title">
        <span class="wb-badge">③</span>
        <div>
          <h2>操作解决</h2>
          <p>分析可跨目录；改代码在独立 worktree 里，人工采纳才合并</p>
        </div>
      </div>
      <div class="wb-head-actions">
        <el-button type="warning" round :loading="fixing" @click="doFix">生成修复方案</el-button>
        <el-button
          v-if="selectedRepos.length"
          type="primary" round :loading="applying" :disabled="!canApply"
          @click="doApply"
        >开始修改</el-button>
      </div>
    </div>

    <!-- 出入告警：最新一轮与方案不一致时置顶，避免埋在页面底部 -->
    <div v-if="latestAttemptAlert" class="alert-bar" @click="tab = 'attempts'">
      <span class="alert-icon">!</span>
      <div class="alert-body">
        <b>第 {{ latestAttemptAlert.seq }} 次修改与方案有出入</b>
        <span class="alert-detail">
          <template v-if="latestAttemptAlert.deviations?.length">
            {{ latestAttemptAlert.deviations.length }} 处偏离
          </template>
          <template v-if="latestAttemptAlert.found_issues?.length">
            <template v-if="latestAttemptAlert.deviations?.length"> · </template>
            {{ latestAttemptAlert.found_issues.length }} 个新发现
          </template>
        </span>
        <span v-if="latestAttemptAlert.deviations?.length" class="alert-first">
          {{ latestAttemptAlert.deviations[0] }}
        </span>
      </div>
      <span class="alert-go">查看 ›</span>
    </div>

    <!-- tab 切换 -->
    <div class="wb-tabs">
      <button
        v-for="t in TABS" :key="t.key" class="wb-tab"
        :class="{ 'is-on': tab === t.key }" @click="tab = t.key"
      >
        <span class="wb-tab-text">{{ t.label }}</span>
        <span v-if="tabCount(t.key)" class="wb-tab-count" :class="t.key === 'attempts' && latestAttemptAlert ? 'is-warn' : ''">
          {{ tabCount(t.key) }}
        </span>
      </button>
    </div>

    <div class="wb-body">
      <!-- ========== 准备：代码范围 / 目标仓库 / 上下文 ========== -->
      <template v-if="tab === 'prep'">
        <div class="field-block">
          <div class="field-head">
            <span class="field-title">代码范围</span>
            <span class="ih-muted">勾上即可分析 + 修改；项目里的仓库</span>
          </div>
          <div class="scope-list">
            <button
              v-for="r in roots" :key="r.path" class="scope-chip"
              :class="{ 'is-on': selectedScopes.includes(r.path), 'is-missing': !r.exists }"
              @click="toggleScope(r.path)"
            >
              <span class="scope-name">{{ r.name }}</span>
              <span v-if="r.isGit" class="scope-badge">git</span>
              <span v-if="!r.exists" class="scope-badge scope-badge--warn">不存在</span>
            </button>
            <span v-if="!roots.length" class="ih-muted">还没有配置候选目录，去「设置 → 代码范围」添加</span>
          </div>
        </div>

        <!-- 代码范围之外的可改仓库：平时和代码范围一致，只有在用户缩小了范围时才出现 -->
        <div v-if="uncoveredRepos.length" class="field-block">
          <div class="field-head">
            <span class="field-title">本次改哪些仓库</span>
            <span class="ih-muted">默认跟随代码范围，可取消（比如只改后端）</span>
          </div>
          <div class="scope-list">
            <button
              v-for="r in targetRepos" :key="r.path" class="scope-chip"
              :class="{ 'is-on': isRepoSelected(r.path), 'is-missing': !r.exists }"
              @click="toggleRepo(r.path)"
            >
              <span class="scope-name">{{ r.name }}</span>
              <span v-if="!r.exists" class="scope-badge scope-badge--warn">不存在</span>
            </button>
          </div>
        </div>

        <div v-if="outOfRepoScopes.length" class="scope-warn">
          <b>代码范围与目标仓库不匹配</b>
          <div class="scope-warn-body">
            这些目录不在已选目标仓库内，AI 在 worktree 里无法修改：
            <code v-for="s in outOfRepoScopes" :key="s">{{ s }}</code>
          </div>
        </div>

        <div class="field-block">
          <div class="field-head">
            <span class="field-title">修复边界</span>
            <span class="ih-muted">AI 按这里的说明改代码</span>
            <el-button link type="primary" class="field-head-btn" @click="contextDrawer = true">
              查看 / 编辑
            </el-button>
          </div>
          <div class="ctx-preview" @click="contextDrawer = true">
            <code class="ctx-path">{{ contextPath || '（还没有生成）' }}</code>
            <span class="ih-muted ctx-tip">点开可编辑；「你维护区」的内容重新生成时保留</span>
          </div>
        </div>

        <!-- 对话记忆：挂在问题上，换通道也不丢 -->
        <div class="field-block">
          <div class="field-head">
            <span class="field-title">对话记忆</span>
            <span class="ih-muted">挂在问题上，换通道/换模型都不丢</span>
            <el-button
              v-if="memorySessions.length" link type="danger" class="field-head-btn"
              @click="doClearMemory()"
            >全部清空</el-button>
          </div>
          <div v-if="memorySessions.length" class="mem-list">
            <div v-for="m in memorySessions" :key="m.id" class="mem-row">
              <span class="mem-kind">{{ m.kindLabel }}</span>
              <span class="mem-stat">{{ m.turns }} 次调用 · {{ m.rounds }} 轮工具</span>
              <span class="mem-tokens">{{ m.tokens }} tok</span>
              <span class="ih-muted mem-time">{{ (m.updated_at || '').slice(5, 16) }}</span>
              <el-button link type="danger" size="small" @click="doClearMemory(m.kind)">清空</el-button>
            </div>
          </div>
          <div v-else class="ih-muted mem-empty">
            还没有对话记录。跑过一次定性/分析后，这里会显示累积的上下文。
          </div>
        </div>
      </template>

      <!-- ========== 分析：方案 + 流程图 ========== -->
      <template v-else-if="tab === 'analysis'">
        <div v-if="fixPlan" class="fix-plan">
          <div class="fix-row"><span class="fix-k">根因</span><span class="fix-v">{{ fixPlan.root_cause }}</span></div>
          <div v-if="fixPlan.files?.length" class="fix-row">
            <span class="fix-k">涉及文件</span>
            <span class="fix-v"><code v-for="(f, i) in fixPlan.files" :key="i">{{ f }}</code></span>
          </div>
          <div v-if="fixPlan.changes?.length" class="fix-row">
            <span class="fix-k">改动点</span>
            <span class="fix-v"><ul><li v-for="(c, i) in fixPlan.changes" :key="i">{{ c }}</li></ul></span>
          </div>
          <div v-if="fixPlan.verification?.length" class="fix-row">
            <span class="fix-k">验证方式</span>
            <span class="fix-v"><ul><li v-for="(c, i) in fixPlan.verification" :key="i">{{ c }}</li></ul></span>
          </div>
          <div v-if="fixPlan.risks?.length" class="fix-row">
            <span class="fix-k">风险</span>
            <span class="fix-v"><ul><li v-for="(c, i) in fixPlan.risks" :key="i">{{ c }}</li></ul></span>
          </div>
        </div>
        <el-empty v-else description="还没有分析结果，点上方「生成修复方案」" :image-size="80" />

        <div v-if="fixFlow" class="flow-block">
          <div class="flow-head">分析流程图</div>
          <MermaidView :code="fixFlow" :dark="isDark" />
        </div>
      </template>

      <!-- ========== 修改：worktree 与 diff ========== -->
      <template v-else-if="tab === 'worktree'">
        <template v-if="repoStateList.length">
          <div class="wt-toolbar">
            <span class="ih-muted">{{ repoStateList.length }} 个仓库</span>
            <el-button size="small" round @click="refreshDiff">刷新 diff</el-button>
            <el-button
              v-if="hasAnyDiff && repoStateList.some((r) => !r.state.accepted && r.state.status !== 'failed')"
              size="small" round type="success" :loading="accepting" @click="doAccept()"
            >全部采纳</el-button>
            <el-button size="small" round type="danger" plain :loading="rejecting" @click="doReject()">
              全部驳回
            </el-button>
          </div>

          <div v-for="r in repoStateList" :key="r.path" class="repo-card">
            <div class="repo-card-head">
              <div class="repo-card-title">
                <b>{{ r.name }}</b>
                <span class="repo-card-status" :class="`is-${r.state.status || 'unknown'}`">
                  {{ r.state.status === 'failed' ? '失败' : r.state.status === 'unchanged' ? '无改动' : r.state.accepted ? '已采纳' : '待审阅' }}
                </span>
              </div>
              <div class="repo-card-actions">
                <el-button
                  v-if="r.state.branch" size="small" round type="success"
                  :disabled="r.state.accepted || r.state.status === 'failed'"
                  :loading="accepting" @click="doAccept(r.path)"
                >采纳</el-button>
                <el-button size="small" round type="danger" plain :loading="rejecting" @click="doReject(r.path)">
                  驳回
                </el-button>
              </div>
            </div>

            <div v-if="r.state.branch" class="repo-card-meta">
              <code>{{ r.state.branch }}</code>
              <span class="ih-muted">{{ r.state.worktree }}</span>
            </div>

            <div v-if="r.state.status === 'failed'" class="repo-error">
              <b>修改失败</b>
              <div>{{ r.state.error }}</div>
            </div>

            <div v-if="r.state.accepted" class="accepted-box">
              <b>已采纳</b>
              <span v-if="r.state.merge?.merged">已合并到 {{ r.state.merge.base_branch }}</span>
              <span v-else>已提交到分支，需人工合并：<code>{{ r.state.merge?.command }}</code></span>
            </div>

            <template v-if="r.state.status !== 'failed'">
              <div class="diff-stat">{{ diffs[r.path]?.stat || r.state.diff_stat || '（暂无改动）' }}</div>
              <pre v-if="diffs[r.path]?.diff" class="diff-view"><code><span
                v-for="(line, i) in (diffs[r.path].diff || '').split('\n')" :key="i" :class="diffLineClass(line)"
              >{{ line + '\n' }}</span></code></pre>
              <div v-if="diffs[r.path]?.truncated" class="ih-muted">diff 太长已截断，完整内容请到 worktree 查看。</div>
              <div v-if="r.state.summary" class="repo-summary">{{ r.state.summary }}</div>
            </template>
          </div>
        </template>
        <el-empty v-else description="还没有开始修改" :image-size="80" />
      </template>

      <!-- ========== 轮次：历史修改档案 ========== -->
      <template v-else>
        <template v-if="attempts.length">
          <div class="attempts-head">
            <span class="ih-muted">共 {{ attempts.length }} 轮 · 记录每次实际修改与分析方案的出入</span>
          </div>
          <el-collapse v-model="openAttempts" class="attempts-collapse">
            <el-collapse-item v-for="a in attempts" :key="a.seq" :name="a.seq">
              <template #title>
                <span class="attempt-title">
                  <span class="attempt-seq">第 {{ a.seq }} 次</span>
                  <span class="attempt-status" :class="`is-${a.status}`">{{ attemptStatusLabel(a) }}</span>
                  <span
                    v-if="(a.deviations?.length || 0) + (a.found_issues?.length || 0) > 0"
                    class="attempt-flag"
                  >与方案有出入</span>
                  <span v-if="a.files?.length" class="ih-muted attempt-files">{{ a.files.length }} 个文件</span>
                </span>
              </template>
              <div class="attempt-time">{{ (a.created_at || '').slice(0, 19) }}</div>
              <div class="attempt-body">
                <div v-if="a.deviations?.length" class="attempt-sec attempt-sec--warn">
                  <div class="attempt-sec-title">与方案的出入</div>
                  <ul><li v-for="(d, i) in a.deviations" :key="i">{{ d }}</li></ul>
                </div>
                <div v-if="a.found_issues?.length" class="attempt-sec attempt-sec--info">
                  <div class="attempt-sec-title">过程中发现的新问题</div>
                  <ul><li v-for="(d, i) in a.found_issues" :key="i">{{ d }}</li></ul>
                </div>
                <div v-if="a.actual_root_cause" class="attempt-sec">
                  <div class="attempt-sec-title">实际根因</div>
                  <div class="attempt-sec-text">{{ a.actual_root_cause }}</div>
                </div>
                <div v-if="a.files?.length" class="attempt-sec">
                  <div class="attempt-sec-title">改动文件</div>
                  <code v-for="(f, i) in a.files" :key="i" class="attempt-file">{{ f }}</code>
                </div>
                <div v-if="a.risks?.length" class="attempt-sec">
                  <div class="attempt-sec-title">风险</div>
                  <ul><li v-for="(d, i) in a.risks" :key="i">{{ d }}</li></ul>
                </div>
                <div v-if="a.verification" class="attempt-sec">
                  <div class="attempt-sec-title">验证方式</div>
                  <div class="attempt-sec-text">{{ a.verification }}</div>
                </div>
                <div v-if="a.summary" class="attempt-sec">
                  <div class="attempt-sec-title">总结</div>
                  <div class="attempt-sec-text attempt-summary">{{ a.summary }}</div>
                </div>
                <div v-if="a.repos" class="attempt-repos">
                  <div v-for="(st, rp) in a.repos" :key="rp" class="attempt-repo-row">
                    <span class="ih-muted">{{ String(rp).split(/[\\/]/).pop() }}</span>
                    <span class="attempt-repo-status" :class="`is-${st.status}`">
                      {{ st.status === 'failed' ? '失败' : st.status === 'unchanged' ? '无改动' : '有改动' }}
                    </span>
                    <span v-if="st.error" class="attempt-repo-err">{{ st.error }}</span>
                  </div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </template>
        <el-empty v-else description="还没有修改记录" :image-size="80" />
      </template>
    </div>

    <!-- 修复边界抽屉 -->
    <el-drawer v-model="contextDrawer" title="修复边界（上下文文件）" :size="drawerSize" append-to-body>
      <div class="ctx-drawer">
        <div class="ctx-toolbar">
          <span class="ih-muted ctx-path">{{ contextPath }}</span>
          <div>
            <el-button size="small" round :loading="contextLoading" @click="regenerateContext">
              按当前范围重新生成
            </el-button>
            <el-button size="small" round type="primary" :loading="contextSaving" @click="saveContext">
              保存
            </el-button>
          </div>
        </div>
        <el-input
          v-model="contextDraft" type="textarea" :rows="22" class="ctx-input"
          placeholder="这里会显示本次修复的边界说明：哪些仓库能改、哪些不能碰、有哪些约束。可以自己改。"
        />
        <div class="ih-muted ctx-hint">
          「自动生成区」会被重新生成覆盖；「你维护区」里的内容永远保留。
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MermaidView from '../components/MermaidView.vue'
import { useTheme } from '../useTheme'
import { useMobile } from '../useMobile'
import {
  acceptFix, applyFix, clearMemory, getCodeRoots, getFixContext, getFixDiff, getMemory,
  patchIssue, regenerateFixContext, rejectFix, runFix, saveFixContext,
  type CodeRoot, type MemorySession, type TargetRepo, type FixAttempt
} from '../api'

const props = defineProps<{
  issueId: number
  /** 父级加载好的 issue（含 fix_plan / fix_state / attempts / code_scopes 等） */
  issue: any
  /** 当前 AI 通道 id；为空表示用设置里的默认通道 */
  channelId?: number | null
  /** 所属项目：决定代码范围与可改仓库的候选 */
  projectId?: number | null
}>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const { isDark } = useTheme()
const isMobile = useMobile()
const drawerSize = computed(() => (isMobile.value ? '100%' : '720px'))

const TABS = [
  { key: 'prep', label: '准备' },
  { key: 'analysis', label: '分析' },
  { key: 'worktree', label: '修改' },
  { key: 'attempts', label: '轮次' }
] as const
type TabKey = typeof TABS[number]['key']
const tab = ref<TabKey>('prep')

const roots = ref<CodeRoot[]>([])
const targetRepos = ref<TargetRepo[]>([])
const selectedScopes = ref<string[]>([])
const selectedRepos = ref<string[]>([])
const diffs = ref<Record<string, any>>({})

const fixing = ref(false)
const applying = ref(false)
const accepting = ref(false)
const rejecting = ref(false)

const attempts = ref<FixAttempt[]>([])
const openAttempts = ref<number[]>([])

/* ===== 对话记忆 ===== */
const memorySessions = ref<MemorySession[]>([])

const loadMemory = async () => {
  const r = await getMemory(props.issueId).catch(() => null)
  memorySessions.value = r?.sessions || []
}

const doClearMemory = async (kind?: string) => {
  const label = kind
    ? memorySessions.value.find((m) => m.kind === kind)?.kindLabel || kind
    : '全部'
  await ElMessageBox.confirm(`清空${label}的对话记忆？下次会从零开始。`, '提示', { type: 'warning' })
  await clearMemory(props.issueId, kind || '')
  await loadMemory()
  ElMessage.success('已清空')
}

const fixPlan = computed(() => props.issue?.fix_plan || null)
const fixState = computed(() => props.issue?.fix_state || null)
const fixFlow = computed<string>(() => {
  const raw = fixPlan.value?.flow
  return typeof raw === 'string' ? raw.trim() : ''
})

/** 执行器由用户自己选，前端不拦：选了不能改代码的（如 deepseek），后端会给明确报错 */
const canApply = computed(() => selectedRepos.value.length > 0)

/* ===== 代码范围 × 目标仓库 ===== */
const normPath = (p: string) => (p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
const isUnder = (child: string, parent: string) => {
  const c = normPath(child); const p = normPath(parent)
  if (!c || !p) return false
  return c === p || c.startsWith(p + '/')
}
const coveredBy = (repo: TargetRepo | undefined) =>
  repo ? [repo.path, ...(repo.covers || [])] : []

const reposInScopes = computed(() =>
  targetRepos.value.filter((repo) =>
    coveredBy(repo).some((c) => selectedScopes.value.some((s) => isUnder(s, c)))
  )
)

const outOfRepoScopes = computed(() => {
  if (!selectedRepos.value.length) return [] as string[]
  const covered = selectedRepos.value.flatMap((p) => {
    const r = targetRepos.value.find((x) => normPath(x.path) === normPath(p))
    return coveredBy(r)
  })
  if (!covered.length) return [] as string[]
  return selectedScopes.value.filter((s) => !covered.some((c) => isUnder(s, c)))
})

const isRepoSelected = (path: string) =>
  selectedRepos.value.some((p) => normPath(p) === normPath(path))

/** 项目里存在、但不在当前代码范围内的仓库（需要单独给个开关） */
const uncoveredRepos = computed(() =>
  targetRepos.value.filter(
    (r) => !selectedScopes.value.some((sc) => isUnder(sc, r.path))
  )
)

const uniqRepos = computed(() => {
  const seen = new Set<string>()
  return selectedRepos.value.filter((p) => {
    const k = normPath(p)
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
})

const repoInfo = (path: string) =>
  targetRepos.value.find((r) => normPath(r.path) === normPath(path))

/* ===== worktree 状态（按仓库分组，兼容旧的扁平结构） ===== */
const repoStates = computed<Record<string, any>>(() => {
  const s = fixState.value
  if (!s) return {}
  if (s.repos) return s.repos
  if (s.repo) return { [s.repo]: { ...s } }
  return {}
})
const repoStateList = computed(() =>
  Object.entries(repoStates.value).map(([path, st]) => ({
    path,
    name: (st as any).name || repoInfo(path)?.name || path.split(/[\\/]/).pop(),
    state: st as any
  }))
)
const hasAnyDiff = computed(() => repoStateList.value.some((r) => (r.state.files || []).length > 0))

/* ===== 出入告警 ===== */
const latestAttemptAlert = computed<FixAttempt | null>(() => {
  const a = attempts.value[0]
  if (!a) return null
  const n = (a.deviations?.length || 0) + (a.found_issues?.length || 0)
  return n > 0 ? a : null
})

/* ===== tab 角标 ===== */
const tabCount = (key: TabKey): number | '' => {
  if (key === 'prep') {
    const n = selectedScopes.value.length + selectedRepos.value.length
    return n || ''
  }
  if (key === 'analysis') return fixPlan.value ? 1 : ''
  if (key === 'worktree') {
    const pending = repoStateList.value.filter((r) => !r.state.accepted && r.state.status !== 'unchanged').length
    return pending || ''
  }
  return attempts.value.length || ''
}

/* ===== 修复上下文 ===== */
const contextText = ref('')
const contextPath = ref('')
const contextDraft = ref('')
const contextDrawer = ref(false)
const contextSaving = ref(false)
const contextLoading = ref(false)

const loadContext = async () => {
  if (!props.issueId) return
  contextLoading.value = true
  try {
    const r = await getFixContext(props.issueId)
    contextText.value = r.text || ''
    contextPath.value = r.path || ''
    contextDraft.value = r.text || ''
  } catch {
    contextText.value = ''
  } finally {
    contextLoading.value = false
  }
}

const saveContext = async () => {
  contextSaving.value = true
  try {
    const r = await saveFixContext(props.issueId, contextDraft.value)
    contextText.value = contextDraft.value
    contextPath.value = r.path || contextPath.value
    ElMessage.success('上下文已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    contextSaving.value = false
  }
}

const regenerateContext = async () => {
  contextLoading.value = true
  try {
    const r = await regenerateFixContext(props.issueId)
    contextText.value = r.text
    contextDraft.value = r.text
    contextPath.value = r.path
    ElMessage.success('已按当前范围重新生成（你手写的部分已保留）')
  } catch {
    ElMessage.error('重新生成失败')
  } finally {
    contextLoading.value = false
  }
}

/* ===== 修改轮次 ===== */
const loadAttempts = (list?: FixAttempt[]) => {
  attempts.value = list || []
  const withDeviation = attempts.value.find(
    (a) => (a.deviations?.length || 0) + (a.found_issues?.length || 0) > 0
  )
  openAttempts.value = withDeviation ? [withDeviation.seq]
    : attempts.value.length ? [attempts.value[0].seq] : []
}
const attemptStatusLabel = (a: FixAttempt) =>
  ({ changed: '有改动', unchanged: '无改动', failed: '失败', partial: '部分成功' } as any)[a.status || ''] || a.status || '-'

/* ===== 从 props.issue 同步状态 ===== */
const syncFromIssue = () => {
  const iss = props.issue
  if (!iss) return
  selectedScopes.value = Array.isArray(iss.code_scopes) ? iss.code_scopes : []
  const tr = iss.target_repos
  selectedRepos.value = Array.isArray(tr) ? tr : (iss.target_repo ? [iss.target_repo] : [])
  loadAttempts(iss.attempts)
  // 老数据没有目标仓库时，按已勾范围自动补一次
  if (!selectedRepos.value.length && selectedScopes.value.length && targetRepos.value.length) {
    const mapped = reposInScopes.value.map((r) => r.path)
    if (mapped.length) {
      selectedRepos.value = mapped
      patchIssue(props.issueId, { target_repos: mapped }).catch(() => {})
    }
  }
  if (iss.fix_state) loadDiff()
}

watch(() => props.issue, syncFromIssue, { deep: false })

/* ===== 操作 ===== */
const saveRepos = async () => {
  await patchIssue(props.issueId, { target_repos: selectedRepos.value })
}

const toggleScope = async (path: string) => {
  const next = selectedScopes.value.includes(path)
    ? selectedScopes.value.filter((p) => p !== path)
    : [...selectedScopes.value, path]
  selectedScopes.value = next
  await patchIssue(props.issueId, { code_scopes: next })
  await autoMapRepos()
  emit('changed')
}

/** 勾范围 → 自动带出目标仓库；取消范围时移除不再被覆盖的仓库 */
const autoMapRepos = async () => {
  const should = reposInScopes.value.map((r) => r.path)
  const next = Array.from(new Set([...selectedRepos.value, ...should]))
    .filter((p) => should.some((s) => normPath(s) === normPath(p)))
  if (JSON.stringify(next.slice().sort()) === JSON.stringify(selectedRepos.value.slice().sort())) return
  selectedRepos.value = next
  await saveRepos()
}

const toggleRepo = async (path: string) => {
  selectedRepos.value = isRepoSelected(path)
    ? selectedRepos.value.filter((p) => normPath(p) !== normPath(path))
    : [...selectedRepos.value, path]
  await saveRepos()
  emit('changed')
}

const loadDiff = async () => {
  if (!Object.keys(repoStates.value).length) return
  try {
    const res = await getFixDiff(props.issueId)
    diffs.value = res.diffs || {}
  } catch {
    diffs.value = {}
  }
}

const refreshDiff = async () => {
  await loadDiff()
  ElMessage.success('已刷新')
}

const diffLineClass = (line: string) => {
  if (line.startsWith('+++') || line.startsWith('---')) return 'dl-meta'
  if (line.startsWith('+')) return 'dl-add'
  if (line.startsWith('-')) return 'dl-del'
  if (line.startsWith('@@')) return 'dl-hunk'
  return ''
}

const doFix = async () => {
  fixing.value = true
  try {
    const res = await runFix(props.issueId, props.channelId)
    emit('changed')
    await loadMemory()
    tab.value = 'analysis'
    ElMessage.success(`方案已生成（${res.provider}）`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    fixing.value = false
  }
}

const doApply = async () => {
  if (!selectedRepos.value.length) {
    ElMessage.warning('先选择至少一个目标仓库')
    return
  }
  applying.value = true
  try {
    const res = await applyFix(props.issueId, { channel_id: props.channelId, repos: selectedRepos.value })
    emit('changed')
    diffs.value = res.diffs || {}
    if (res.attempt) loadAttempts([res.attempt, ...attempts.value])
    await loadMemory()
    tab.value = 'worktree'
    const states = Object.values(res.state?.repos || {}) as any[]
    const failed = states.filter((s) => s.status === 'failed')
    const changed = states.filter((s) => s.status === 'changed')
    if (failed.length && !changed.length) ElMessage.error(`${failed.length} 个仓库修改失败，看下错误详情`)
    else if (failed.length) ElMessage.warning(`${changed.length} 个仓库有改动，${failed.length} 个失败`)
    else if (!changed.length) ElMessage.warning('AI 没有产生任何文件改动，看下它的说明')
    else ElMessage.success(`${changed.length} 个仓库有改动，请审阅 diff`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    applying.value = false
  }
}

const doAccept = async (repo?: string) => {
  const label = repo ? repoInfo(repo)?.name || repo : '全部仓库'
  await ElMessageBox.confirm(
    `将提交 ${label} 的改动，并在主仓库干净时自动合并。继续？`, '采纳', { type: 'warning' })
  accepting.value = true
  try {
    const res = await acceptFix(props.issueId, repo ? { repo } : {})
    emit('changed')
    await loadDiff()
    const results = Object.entries(res.results || {})
    const merged = results.filter(([, r]: any) => r?.merge?.merged).length
    const notMerged = results.filter(([, r]: any) => r?.ok && !r?.merge?.merged)
    const bad = results.filter(([, r]: any) => !r?.ok)
    if (bad.length) ElMessage.error(`${bad.length} 个仓库采纳失败：${(bad[0][1] as any).error || ''}`)
    else if (notMerged.length) ElMessage.warning('已提交到分支，需人工合并')
    else ElMessage.success(`已合并 ${merged} 个仓库`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '采纳失败')
  } finally {
    accepting.value = false
  }
}

const doReject = async (repo?: string) => {
  const label = repo ? repoInfo(repo)?.name || repo : '全部仓库'
  await ElMessageBox.confirm(`丢弃 ${label} 的 worktree 和分支？改动会全部删除。`, '驳回', { type: 'warning' })
  rejecting.value = true
  try {
    await rejectFix(props.issueId, repo ? { repo } : {})
    emit('changed')
    if (repo) delete diffs.value[repo]
    else diffs.value = {}
    ElMessage.success('已丢弃')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '驳回失败')
  } finally {
    rejecting.value = false
  }
}

const loadRoots = async () => {
  const r = await getCodeRoots(props.projectId).catch(() => null)
  if (r) {
    roots.value = r.roots
    targetRepos.value = r.targetRepos || []
  }
}

/** 换项目要重新拉候选仓库，否则还显示上一个项目的目录 */
watch(() => props.projectId, async (next, prev) => {
  if (next === prev) return
  await loadRoots()
  syncFromIssue()
})

onMounted(async () => {
  await loadRoots()
  syncFromIssue()
  await loadContext()
  await loadMemory()
})
</script>

<style scoped>
.workbench {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  /* 右栏粘性：滚左栏时它不动 */
  position: sticky;
  top: 76px;
  max-height: calc(100vh - 92px);
  overflow: hidden;
}

/* 头部 */
.wb-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; }
.wb-title { display: flex; gap: 10px; align-items: flex-start; }
.wb-title h2 { margin: 0; font-size: 16px; font-weight: 700; color: var(--ih-ink); }
.wb-title p { margin: 3px 0 0; font-size: 12px; color: var(--ih-sub); }
.wb-badge {
  flex: 0 0 auto; width: 26px; height: 26px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  box-shadow: 0 6px 14px rgba(79, 70, 229, 0.25);
}
.wb-head-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* 出入告警 */
.alert-bar {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 12px; border-radius: 12px; cursor: pointer;
  background: var(--ih-warn-soft); border: 1px solid rgba(247, 144, 9, 0.35);
  transition: transform 0.14s ease;
}
.alert-bar:hover { transform: translateY(-1px); }
.alert-icon {
  flex: 0 0 auto; width: 18px; height: 18px; border-radius: 50%;
  background: #f79009; color: #fff; font-size: 12px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; margin-top: 1px;
}
.alert-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.alert-body b { font-size: 13px; color: var(--ih-warn-ink); }
.alert-detail { font-size: 12px; color: var(--ih-warn-ink); opacity: 0.85; }
.alert-first {
  font-size: 12px; color: var(--ih-sub);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.alert-go { flex: 0 0 auto; font-size: 12px; color: var(--ih-warn-ink); align-self: center; }

/* tabs */
.wb-tabs {
  display: flex; gap: 4px; padding: 4px; border-radius: 12px; background: var(--ih-soft);
}
.wb-tab {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 5px;
  padding: 7px 6px; border: none; border-radius: 9px; background: transparent;
  font-size: 13px; color: var(--ih-sub); cursor: pointer; transition: all 0.16s ease;
  -webkit-appearance: none;
}
.wb-tab:hover { color: var(--ih-ink); }
.wb-tab.is-on {
  background: var(--ih-card); color: var(--el-color-primary); font-weight: 600;
  box-shadow: 0 2px 8px rgba(16, 24, 40, 0.08);
}
.wb-tab-count {
  min-width: 17px; padding: 0 5px; border-radius: 999px; font-size: 11px; line-height: 17px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}
.wb-tab.is-on .wb-tab-count { background: var(--ih-primary-soft); color: var(--el-color-primary); }
.wb-tab-count.is-warn { background: var(--ih-warn-soft); color: var(--ih-warn-ink); }

/* 主体：独立滚动 */
.wb-body {
  flex: 1 1 auto; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: 12px;
  padding-right: 2px;
}

/* 字段块 */
.field-block { display: flex; flex-direction: column; gap: 8px; }
.field-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.field-title { font-size: 13px; font-weight: 600; color: var(--ih-ink); }
.field-head-btn { margin-left: auto; font-size: 12px; }
.scope-list { display: flex; flex-wrap: wrap; gap: 7px; }
.scope-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 11px; border-radius: 999px; font-size: 12.5px;
  border: 1px solid var(--ih-line); background: var(--ih-card);
  color: var(--ih-sub); cursor: pointer; transition: all 0.16s ease;
}
.scope-chip:hover { border-color: var(--ih-line-strong); }
.scope-chip.is-on {
  border-color: var(--el-color-primary); background: var(--el-color-primary-light-9);
  color: var(--el-color-primary); font-weight: 600;
}
.scope-chip.is-missing { opacity: 0.55; }
.scope-badge {
  font-size: 10px; padding: 0 5px; border-radius: 6px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}
.scope-chip.is-on .scope-badge { background: var(--ih-primary-soft); color: var(--el-color-primary); }
.scope-badge--warn { background: var(--ih-warn-soft); color: var(--ih-warn-ink); }
.repo-detail { display: flex; flex-direction: column; gap: 3px; }
.repo-detail-row code { font-size: 11px; color: var(--ih-sub); word-break: break-all; }

.scope-warn {
  padding: 9px 12px; border-radius: 10px; font-size: 12px; line-height: 1.6;
  background: var(--ih-warn-soft); color: var(--ih-warn-ink);
  display: flex; flex-direction: column; gap: 4px;
}
.scope-warn code { display: block; font-size: 11px; opacity: 0.9; }
.scope-warn-body { display: flex; flex-direction: column; gap: 2px; }

/* 对话记忆 */
.mem-list { display: flex; flex-direction: column; gap: 4px; }
.mem-row {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 10px; border-radius: 8px; background: var(--ih-soft);
  font-size: 12px;
}
.mem-kind {
  flex: 0 0 auto; padding: 1px 8px; border-radius: 999px;
  background: var(--ih-primary-soft); color: var(--el-color-primary); font-weight: 600;
}
.mem-stat { color: var(--ih-sub); }
.mem-tokens { color: var(--ih-ink); font-variant-numeric: tabular-nums; }
.mem-time { margin-left: auto; font-size: 11px; }
.mem-empty { padding: 4px 0; }

.ctx-preview {
  display: flex; flex-direction: column; gap: 3px; cursor: pointer;
  padding: 9px 12px; border-radius: 10px; background: var(--ih-soft);
  border: 1px dashed var(--ih-line-strong); transition: border-color 0.16s ease;
}
.ctx-preview:hover { border-color: var(--el-color-primary); }
.ctx-path { font-size: 11.5px; word-break: break-all; color: var(--ih-ink); }
.ctx-tip { font-size: 11.5px; }

/* 分析结果 */
.fix-plan { display: flex; flex-direction: column; gap: 10px; }
.fix-row { display: grid; grid-template-columns: 68px 1fr; gap: 10px; font-size: 13px; }
.fix-k { color: var(--ih-sub); font-size: 12px; }
.fix-v { color: var(--ih-ink); }
.fix-v ul { margin: 0; padding-left: 16px; line-height: 1.7; }
.fix-v code {
  display: block; background: var(--ih-soft-2); padding: 2px 8px; border-radius: 6px;
  margin: 2px 0; font-size: 11.5px; word-break: break-all;
}
.flow-block { display: flex; flex-direction: column; gap: 8px; }
.flow-head { font-size: 13px; font-weight: 600; color: var(--ih-ink); }

/* worktree */
.wt-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.wt-toolbar .ih-muted { margin-right: auto; }
.repo-card {
  border: 1px solid var(--ih-line); border-radius: 12px; padding: 12px;
  display: flex; flex-direction: column; gap: 8px; background: var(--ih-soft);
}
.repo-card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.repo-card-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
.repo-card-status {
  font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}
.repo-card-status.is-changed { background: var(--ih-warn-soft); color: var(--ih-warn-ink); }
.repo-card-status.is-failed { background: rgba(240, 68, 56, 0.12); color: #f04438; }
.repo-card-status.is-unknown { opacity: 0.7; }
.repo-card-meta { display: flex; gap: 8px; font-size: 11px; flex-wrap: wrap; }
.repo-card-meta code { color: var(--el-color-primary); }
.repo-error {
  padding: 8px 10px; border-radius: 8px; font-size: 12px;
  background: rgba(240, 68, 56, 0.1); color: #f04438;
}
.accepted-box {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  padding: 8px 10px; border-radius: 10px; font-size: 12px;
  background: var(--ih-success-soft); color: var(--ih-success-ink);
}
.diff-stat {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px;
  color: var(--ih-sub); white-space: pre-wrap;
}
.diff-view {
  max-height: 300px; overflow: auto; margin: 0; padding: 9px 11px;
  background: var(--ih-card); border: 1px solid var(--ih-line); border-radius: 10px;
}
.diff-view code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11.5px; line-height: 1.55; white-space: pre; }
.dl-add { display: block; color: #12b76a; }
.dl-del { display: block; color: #f04438; }
.dl-hunk { display: block; color: #7c3aed; }
.dl-meta { display: block; color: var(--ih-sub); }
.repo-summary { font-size: 12px; color: var(--ih-sub); line-height: 1.6; white-space: pre-wrap; }

/* 轮次 */
.attempts-head { display: flex; align-items: center; gap: 8px; }
.attempts-collapse { border: none; }
.attempt-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; }
.attempt-seq { font-weight: 600; color: var(--ih-ink); }
.attempt-status { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--ih-soft-2); color: var(--ih-sub); }
.attempt-status.is-changed { background: var(--ih-warn-soft); color: var(--ih-warn-ink); }
.attempt-status.is-failed { background: rgba(240, 68, 56, 0.12); color: #f04438; }
.attempt-flag {
  font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-warn-soft); color: var(--ih-warn-ink); font-weight: 600;
}
.attempt-files { font-size: 11px; }
.attempt-time { font-size: 11px; color: var(--ih-sub); margin-bottom: 6px; }
.attempt-body { display: flex; flex-direction: column; gap: 10px; }
.attempt-sec { display: flex; flex-direction: column; gap: 4px; }
.attempt-sec-title { font-size: 12px; font-weight: 600; color: var(--ih-ink); }
.attempt-sec-text { font-size: 12.5px; color: var(--ih-sub); line-height: 1.65; }
.attempt-sec ul { margin: 0; padding-left: 16px; font-size: 12.5px; color: var(--ih-sub); line-height: 1.7; }
.attempt-sec--warn { background: var(--ih-warn-soft); border-radius: 10px; padding: 9px 11px; }
.attempt-sec--warn .attempt-sec-title { color: var(--ih-warn-ink); }
.attempt-sec--warn ul { color: var(--ih-warn-ink); }
.attempt-sec--info { background: var(--ih-soft); border-radius: 10px; padding: 9px 11px; }
.attempt-file {
  display: block; font-size: 11px; background: var(--ih-soft-2);
  padding: 2px 7px; border-radius: 5px; margin: 2px 0; word-break: break-all;
}
.attempt-summary { white-space: pre-wrap; }
.attempt-repos { display: flex; flex-direction: column; gap: 3px; }
.attempt-repo-row { display: flex; gap: 8px; align-items: center; font-size: 11.5px; }
.attempt-repo-status { padding: 0 6px; border-radius: 5px; background: var(--ih-soft-2); font-size: 11px; }
.attempt-repo-err { color: #f04438; font-size: 11px; }

/* 上下文抽屉 */
.ctx-drawer { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.ctx-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.ctx-path { font-size: 11.5px; word-break: break-all; }
.ctx-input :deep(.el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; line-height: 1.6;
}
.ctx-hint { font-size: 11.5px; }

@media (max-width: 768px) {
  .workbench {
    position: static; max-height: none; height: 100%;
    box-shadow: none; border: none; padding: 12px;
  }
  .wb-body { overflow-y: visible; }
  .fix-row { grid-template-columns: 1fr; gap: 2px; }
  .diff-view { max-height: 260px; }
}
</style>
