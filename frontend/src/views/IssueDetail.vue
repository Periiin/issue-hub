<template>
  <div v-if="issue" class="detail">
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
        </div>
        <div class="hero-side">
          <div class="hero-badges">
            <span :class="priorityClass(issue.priority)">{{ issue.priority || '未定级' }}</span>
            <span v-if="issue.severity" class="badge badge--soft">{{ issue.severity }}</span>
            <span v-if="issue.complexity" class="badge badge--ghost">{{ issue.complexity }}</span>
          </div>
          <div class="hero-actions">
            <el-select v-model="issue.status" size="default" class="status-select" @change="changeStatus">
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
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">原</span>
          <div>
            <h2>原始描述</h2>
            <p>甲方原话与截图，粘贴即上传</p>
          </div>
        </div>
        <div class="panel-actions">
          <input ref="fileInput" type="file" accept="image/*,application/pdf" multiple hidden @change="onPickFiles" />
          <el-button round @click="fileInput?.click()">选择文件</el-button>
          <el-button round type="primary" plain :loading="uploading" :disabled="!pendingFiles.length" @click="uploadNow">
            上传{{ pendingFiles.length ? `(${pendingFiles.length})` : '' }}
          </el-button>
        </div>
      </div>

      <el-input
        v-model="rawText"
        type="textarea"
        :rows="4"
        resize="none"
        placeholder="甲方原话；截图可以直接 Ctrl+V 粘贴"
        class="raw-input"
        @paste="onPaste"
        @blur="saveRawText"
      />

      <div v-if="attachments.length" class="thumbs">
        <div v-for="a in attachments" :key="a.id" class="thumb">
          <el-image
            v-if="isImage(a)"
            :src="fileUrl(a.path)"
            :preview-src-list="imageUrls"
            fit="cover"
            class="thumb-img"
            preview-teleported
          />
          <a v-else :href="fileUrl(a.path)" target="_blank" class="file-link">PDF</a>
          <button class="thumb-del" @click.stop="removeAttachment(a)">×</button>
        </div>
      </div>
    </section>

    <!-- ① AI 定性 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge">1</span>
          <div>
            <h2>AI 定性</h2>
            <p>把口语化成结构化描述，人工确认后才进入定级</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-select v-model="provider" size="default" class="provider-select">
            <el-option v-for="p in providers" :key="p" :label="p" :value="p" />
          </el-select>
          <el-button type="primary" round :loading="qualifying" @click="doQualify">
            {{ issue.qualify_final ? '重新定性' : 'AI 定性' }}
          </el-button>
        </div>
      </div>

      <div class="state-chip" :class="issue.qualify_final ? 'is-done' : 'is-todo'">
        <span>{{ issue.qualify_final ? '已确认定性' : '尚未确认' }}</span>
        <span class="ih-muted" v-if="issue.qualify_final">{{ issue.updated_at }}</span>
      </div>

      <el-form label-position="top" class="qualify-form">
        <el-form-item label="标题">
          <el-input v-model="q.title" />
        </el-form-item>
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
        <el-form-item label="归属模块">
          <el-input v-model="q.module" />
        </el-form-item>
      </el-form>

      <div class="panel-foot">
        <el-button type="success" round :loading="confirming" @click="doConfirm">确认定性，进入定级</el-button>
      </div>
    </section>

    <!-- ② AI 定级 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge">2</span>
          <div>
            <h2>AI 定级</h2>
            <p>影响等级、修复复杂度、优先级，可手动修正</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button type="primary" round :loading="triaging" @click="doTriage">生成定级</el-button>
        </div>
      </div>

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
    </section>

    <!-- ③ 操作解决 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge">3</span>
          <div>
            <h2>操作解决</h2>
            <p>分析可跨目录；改代码在独立 worktree 里进行，人工采纳才合并</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button type="warning" round :loading="fixing" @click="doFix">生成修复方案</el-button>
          <el-button
            v-if="targetRepo"
            type="primary" round :loading="applying" :disabled="!canApply"
            @click="doApply"
          >开始修改</el-button>
        </div>
      </div>

      <!-- 代码范围（分析用，多选） -->
      <div class="field-block">
        <div class="field-head">
          <span class="field-title">代码范围</span>
          <span class="ih-muted">分析时搜索的目录，可多选（父目录也能选）</span>
        </div>
        <div class="scope-list">
          <button
            v-for="r in roots"
            :key="r.path"
            class="scope-chip"
            :class="{ 'is-on': selectedScopes.includes(r.path), 'is-missing': !r.exists }"
            @click="toggleScope(r.path)"
          >
            <span class="scope-name">{{ r.name }}</span>
            <span v-if="r.isGit" class="scope-badge">git</span>
            <span v-if="!r.exists" class="scope-badge scope-badge--warn">不存在</span>
          </button>
        </div>
      </div>

      <!-- 目标仓库（改代码用，单选） -->
      <div class="field-block">
        <div class="field-head">
          <span class="field-title">目标仓库</span>
          <span class="ih-muted">改代码必须落到单个 git 仓库</span>
        </div>
        <el-select v-model="targetRepo" clearable placeholder="选择一个 git 仓库" class="repo-select" @change="saveRepo">
          <el-option
            v-for="r in gitRoots" :key="r.path" :value="r.path"
            :label="`${r.name}　${r.path}`"
          />
        </el-select>
      </div>

      <div v-if="targetRepo && !canApply" class="apply-hint">
        当前执行器 <b>{{ provider }}</b> 只能分析；改代码请切到 <b>claude</b> 或 <b>dsh</b>（在 ① 里切换）。
      </div>

      <!-- 分析结果 -->
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
      <div v-else-if="!fixState" class="ih-muted fix-empty">还没有分析结果，点「生成修复方案」。</div>

      <!-- worktree 结果 -->
      <div v-if="fixState" class="worktree">
        <div class="wt-head">
          <div class="wt-meta">
            <span class="wt-tag">worktree</span>
            <code>{{ fixState.branch }}</code>
            <span class="ih-muted">{{ fixState.worktree }}</span>
          </div>
          <div class="wt-actions">
            <el-button size="small" round @click="refreshDiff">刷新 diff</el-button>
            <el-button
              v-if="!fixState.accepted"
              size="small" round type="success" :loading="accepting" :disabled="diffEmpty || !diffData"
              @click="doAccept"
            >采纳并合并</el-button>
            <el-button
              v-if="!fixState.accepted"
              size="small" round type="danger" plain :loading="rejecting" @click="doReject"
            >驳回</el-button>
          </div>
        </div>

        <div v-if="fixState.accepted" class="accepted-box">
          <b>已采纳</b>
          <span v-if="fixState.merge?.merged">已合并到 {{ fixState.merge.base_branch }}</span>
          <span v-else>已提交到分支，需人工合并：<code>{{ fixState.merge?.command }}</code></span>
        </div>

        <div class="diff-stat">{{ diffData?.stat || fixState.diff_stat || '（暂无改动）' }}</div>
        <pre v-if="diffData?.diff" class="diff-view"><code><span
          v-for="(line, i) in diffLines" :key="i" :class="diffLineClass(line)"
        >{{ line + '\n' }}</span></code></pre>
        <div v-if="diffData?.truncated" class="ih-muted">diff 太长已截断，完整内容请到 worktree 查看。</div>
      </div>
    </section>

    <!-- 时间线 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">迹</span>
          <div><h2>操作记录</h2></div>
        </div>
      </div>
      <el-timeline class="timeline">
        <el-timeline-item
          v-for="e in events"
          :key="e.id"
          :timestamp="e.created_at"
          placement="top"
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
    </section>
  </div>

  <div v-else class="loading-wrap">
    <el-skeleton :rows="8" animated />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  acceptFix, applyFix, confirmQualify, deleteAttachment, deleteIssue, fileUrl,
  getCodeRoots, getFixDiff, getIssue, getSettings, patchIssue, rejectFix,
  runFix, runQualify, runTriage, uploadAttachments, type CodeRoot
} from '../api'

const route = useRoute()
const router = useRouter()
const id = computed(() => Number(route.params.id))

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
const fixing = ref(false)

/* ===== ③ 操作解决：代码范围 / worktree / diff ===== */
/** 设置里的代码目录候选 */
const roots = ref<CodeRoot[]>([])
/** 分析用（可多选），存到 issue.code_scopes */
const selectedScopes = ref<string[]>([])
/** 改代码用（单个 git 仓库），存到 issue.target_repo */
const targetRepo = ref('')
const diffData = ref<{ stat: string; diff: string; files: string[]; truncated: boolean } | null>(null)
const applying = ref(false)
const accepting = ref(false)
const rejecting = ref(false)

const q = reactive({
  title: '', phenomenon: '', repro_text: '', expected: '', actual: '',
  scope: '', module: '', uncertain_text: ''
})

const triage = computed(() => issue.value?.triage || null)
const fixPlan = computed(() => issue.value?.fix_plan || null)
const fixState = computed(() => issue.value?.fix_state || null)
const gitRoots = computed(() => roots.value.filter((r) => r.isGit && r.exists))
const canApply = computed(() => !!targetRepo.value && ['claude', 'dsh'].includes(provider.value))
const diffEmpty = computed(() => !diffData.value || !diffData.value.files?.length)
const diffLines = computed(() => (diffData.value?.diff || '').split('\n'))

const diffLineClass = (line: string) => {
  if (line.startsWith('+++') || line.startsWith('---')) return 'dl-meta'
  if (line.startsWith('+')) return 'dl-add'
  if (line.startsWith('-')) return 'dl-del'
  if (line.startsWith('@@')) return 'dl-hunk'
  return ''
}
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
  ({ create: '新建', qualify: 'AI 定性', confirm: '人工确认', triage: 'AI 定级', fix: '生成方案', status: '状态变更' } as any)[t] || t

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

const load = async () => {
  const res = await getIssue(id.value)
  issue.value = res.issue
  attachments.value = res.attachments
  events.value = res.events
  rawText.value = res.issue.raw_text || ''
  selectedScopes.value = Array.isArray(res.issue.code_scopes) ? res.issue.code_scopes : []
  targetRepo.value = res.issue.target_repo || ''
  fillQualifyForm(res.issue.qualify_final || res.issue.qualify_draft)
  if (res.issue.fix_state) await loadDiff()
}

const saveRawText = async () => {
  if (!issue.value || rawText.value === (issue.value.raw_text || '')) return
  await patchIssue(id.value, { raw_text: rawText.value })
  issue.value.raw_text = rawText.value
}

const changeStatus = async (status: string) => {
  await patchIssue(id.value, { status })
  ElMessage.success(`状态已改为 ${status}`)
  await load()
}

const exportMd = () => window.open(`/api/issues/${id.value}/export`, '_blank')

const doQualify = async () => {
  qualifying.value = true
  try {
    const res = await runQualify(id.value, provider.value)
    fillQualifyForm(res.draft)
    await load()
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
    await load()
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
    await load()
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

const doFix = async () => {
  fixing.value = true
  try {
    const res = await runFix(id.value, provider.value)
    await load()
    ElMessage.success(`方案已生成（${res.provider}）`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成失败')
  } finally {
    fixing.value = false
  }
}

/* ===== 代码范围 / worktree 操作 ===== */

const toggleScope = async (path: string) => {
  const next = selectedScopes.value.includes(path)
    ? selectedScopes.value.filter((p) => p !== path)
    : [...selectedScopes.value, path]
  selectedScopes.value = next
  await patchIssue(id.value, { code_scopes: next })
}

const saveRepo = async () => {
  await patchIssue(id.value, { target_repo: targetRepo.value || '' })
}

const loadDiff = async () => {
  if (!fixState.value) return
  try {
    const res = await getFixDiff(id.value)
    diffData.value = res.diff
  } catch {
    diffData.value = null
  }
}

const refreshDiff = async () => {
  await loadDiff()
  ElMessage.success('已刷新')
}

const doApply = async () => {
  applying.value = true
  try {
    const res = await applyFix(id.value, { provider: provider.value, repo: targetRepo.value })
    await load()
    diffData.value = res.diff
    if (res.diff?.empty) ElMessage.warning('AI 没有产生任何文件改动，看下它的说明')
    else ElMessage.success(`已修改 ${res.diff.files.length} 个文件，请审阅 diff`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    applying.value = false
  }
}

const doAccept = async () => {
  await ElMessageBox.confirm(
    '将提交 worktree 里的改动，并在主仓库干净时自动合并。继续？', '采纳', { type: 'warning' })
  accepting.value = true
  try {
    const res = await acceptFix(id.value, {})
    await load()
    await loadDiff()
    if (res.merge?.merged) ElMessage.success(`已合并到 ${res.merge.base_branch}`)
    else ElMessage.warning(res.merge?.reason || '已提交到分支，需人工合并')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '采纳失败')
  } finally {
    accepting.value = false
  }
}

const doReject = async () => {
  await ElMessageBox.confirm('丢弃 worktree 和分支？改动会全部删除。', '驳回', { type: 'warning' })
  rejecting.value = true
  try {
    await rejectFix(id.value)
    await load()
    diffData.value = null
    ElMessage.success('已丢弃')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '驳回失败')
  } finally {
    rejecting.value = false
  }
}

const onPaste = (e: ClipboardEvent) => {
  const files = Array.from(e.clipboardData?.files || [])
  if (files.length) {
    uploadAttachments(id.value, files).then(load)
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
    await load()
  } finally {
    uploading.value = false
  }
}
const removeAttachment = async (a: any) => {
  await deleteAttachment(id.value, a.id)
  await load()
}
const removeIssue = async () => {
  await ElMessageBox.confirm('删除后不可恢复，确认删除这条问题？', '提示', { type: 'warning' })
  await deleteIssue(id.value)
  router.push('/issues')
}

watch(() => route.params.id, load)
onMounted(async () => {
  const [s, r] = await Promise.all([
    getSettings().catch(() => null),
    getCodeRoots().catch(() => null)
  ])
  if (s) providers.value = s.providers
  if (r) roots.value = r.roots
  await load()
})
</script>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 14px; }
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

/* ---------- 面板 ---------- */
.panel { padding: 18px 20px; }
.panel-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 12px; flex-wrap: wrap; margin-bottom: 14px;
}
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
  display: flex; width: 96px; height: 96px; border-radius: 12px; align-items: center; justify-content: center;
  background: var(--ih-soft-2); color: var(--ih-primary); text-decoration: none; font-weight: 600; font-size: 13px;
}
.thumb-del {
  position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; border-radius: 50%;
  border: none; background: rgba(16, 24, 40, 0.7); color: #fff; font-size: 12px; line-height: 20px;
  cursor: pointer;
}

/* 定性 */
.state-chip {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 6px 12px; border-radius: 999px; font-size: 12px; margin-bottom: 12px;
}
.state-chip.is-done { background: var(--ih-success-soft); color: var(--ih-success-ink); }
.state-chip.is-todo { background: var(--ih-warn-soft); color: var(--ih-warn-ink); }
.qualify-form :deep(.el-form-item) { margin-bottom: 12px; }
.qualify-form :deep(.el-form-item__label) { padding-bottom: 2px; font-size: 12px; color: var(--ih-sub); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

/* 定级 */
.triage-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.triage-cell {
  background: var(--ih-soft); border: 1px solid var(--ih-line); border-radius: 12px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 6px;
}
.triage-label { font-size: 12px; color: var(--ih-sub); }
.triage-detail { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.reason-box { background: var(--ih-soft); border-radius: 12px; padding: 12px 14px; }
.reason-box h3 { margin: 0 0 6px; font-size: 13px; color: var(--ih-ink); }
.reason-box ul { margin: 0; padding-left: 18px; font-size: 13px; color: var(--ih-sub); line-height: 1.7; }
.reason-box--warn { background: var(--ih-warn-soft); }
.triage-meta { display: flex; gap: 16px; font-size: 12px; color: var(--ih-sub); flex-wrap: wrap; }

/* 修复方案 */
.notice {
  padding: 10px 12px; border-radius: 12px; background: var(--ih-warn-soft); color: var(--ih-warn-ink);
  font-size: 12px; margin-bottom: 12px;
}
.fix-plan { display: flex; flex-direction: column; gap: 10px; }
.fix-row { display: grid; grid-template-columns: 84px 1fr; gap: 10px; font-size: 13px; }
.fix-k { color: var(--ih-sub); }
.fix-v ul { margin: 0; padding-left: 18px; line-height: 1.7; }
.fix-v code { display: block; background: var(--ih-soft-2); padding: 2px 8px; border-radius: 6px; margin: 2px 0; font-size: 12px; }

/* 时间线 */
.timeline { padding-left: 4px; }
.event-line { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 13px; }
.event-type { font-weight: 600; color: var(--ih-ink); }
.event-note { color: var(--ih-sub); font-size: 12px; }

/* ---------- ③ 代码范围 / worktree ---------- */
.field-block { margin-bottom: 14px; }
.field-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.field-title { font-size: 13px; font-weight: 600; color: var(--ih-ink); }
.scope-list { display: flex; flex-wrap: wrap; gap: 8px; }
.scope-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 999px; font-size: 13px;
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
.repo-select { width: 100%; max-width: 460px; }
.repo-hint { margin-left: 10px; font-size: 12px; color: var(--ih-sub); }
.fix-empty { padding: 6px 0 2px; }
.apply-hint {
  padding: 8px 12px; border-radius: 10px; font-size: 12px; line-height: 1.6;
  background: var(--ih-warn-soft); color: var(--ih-warn-ink); margin-bottom: 12px;
}

.worktree { margin-top: 14px; border-top: 1px dashed var(--ih-line); padding-top: 14px; }
.wt-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.wt-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ih-sub); flex-wrap: wrap; }
.wt-tag { padding: 1px 8px; border-radius: 999px; background: var(--ih-soft-2); color: var(--ih-sub); font-size: 11px; }
.accepted-box {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  padding: 10px 12px; border-radius: 12px; font-size: 13px; margin-bottom: 10px;
  background: var(--ih-success-soft); color: var(--ih-success-ink);
}
.diff-stat { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--ih-sub); white-space: pre-wrap; margin-bottom: 8px; }
.diff-view {
  max-height: 380px; overflow: auto; margin: 0; padding: 10px 12px;
  background: var(--ih-soft); border: 1px solid var(--ih-line); border-radius: 12px;
}
.diff-view code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; white-space: pre; }
.dl-add { display: block; color: #12b76a; }
.dl-del { display: block; color: #f04438; }
.dl-hunk { display: block; color: #7c3aed; }
.dl-meta { display: block; color: var(--ih-sub); }

@media (max-width: 768px) {
  .hero { padding: 16px; }
  .hero-title { font-size: 21px; }
  .hero-side { align-items: stretch; width: 100%; }
  .hero-actions { width: 100%; }
  .status-select { flex: 1; }
  .panel { padding: 14px; }
  .triage-grid { grid-template-columns: 1fr; }
  .two-col { grid-template-columns: 1fr; }
  .fix-row { grid-template-columns: 1fr; gap: 2px; }
  .thumbs { gap: 8px; }
}
</style>
