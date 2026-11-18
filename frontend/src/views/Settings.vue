<template>
  <div class="settings">
    <div class="page-head">
      <div>
        <h1 class="page-title">设置</h1>
        <p class="page-sub">选择 AI 执行器、填 API Key、配置代码仓库路径</p>
      </div>
      <el-button type="primary" round :loading="saving" @click="save">保存配置</el-button>
    </div>

    <!-- 外观 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">◐</span>
          <div>
            <h2>外观</h2>
            <p>深色 / 浅色全局生效，后续新页面同样走这套变量</p>
          </div>
        </div>
      </div>
      <el-radio-group :model-value="mode" @change="(v: any) => setMode(v)">
        <el-radio-button value="light">浅色</el-radio-button>
        <el-radio-button value="dark">深色</el-radio-button>
        <el-radio-button value="system">跟随系统</el-radio-button>
      </el-radio-group>
    </section>

    <!-- 项目：一组 git 仓库 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">&lt;/&gt;</span>
          <div>
            <h2>项目</h2>
            <p>一个项目 = 一组各自独立的 git 仓库（如 gym 包含 4 个）；问题归属到项目后自动带出代码范围</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button round :loading="scanning" @click="doScan">
            {{ scanPreview ? '重新扫描' : '扫描仓库' }}
          </el-button>
          <el-button type="primary" round :loading="importing" :disabled="!scanPreview?.created?.length" @click="doImport">
            导入新项目{{ scanPreview?.created?.length ? `(${scanPreview.created.length})` : '' }}
          </el-button>
        </div>
      </div>

      <!-- 扫描根 -->
      <label class="field field--wide">
        <span class="field-label">扫描根（一行一个）</span>
        <el-input v-model="form['code.scan_roots']" type="textarea" :rows="2" resize="none"
                  placeholder="/src&#10;E:/project" />
        <span class="field-hint">
          从这些目录往下 3 层寻找 git 仓库。换机器只改这里；家里 Windows 可以填 <code>E:/project</code>
        </span>
      </label>

      <!-- 扫描预览 -->
      <div v-if="scanPreview" class="scan-result">
        <div class="scan-line">
          扫描根 <code v-for="r in scanPreview.roots" :key="r">{{ r }}</code>
          发现 <b>{{ scanPreview.scanned }}</b> 个仓库，聚成 <b>{{ scanPreview.clusters.length }}</b> 个候选项目
          <span v-if="scanPreview.hint" class="ih-muted">（{{ scanPreview.hint }}）</span>
        </div>

        <div v-if="scanPreview.suggestions.length" class="suggest-box">
          <div v-for="(sg, i) in scanPreview.suggestions" :key="i" class="suggest-row">
            <div>
              <b>{{ sg.reason }}</b>
              <span class="ih-muted">：{{ sg.projects.map((p) => p.name).join('、') }}</span>
            </div>
            <el-button size="small" round type="warning" plain @click="doMergeSuggestion(sg)">
              合并为 {{ sg.mergedName }}
            </el-button>
          </div>
        </div>
      </div>

      <!-- 已有项目 -->
      <div class="proj-list">
        <div v-for="p in projects" :key="p.id" class="proj-card" :class="{ 'is-ignored': p.ignored }">
          <div class="proj-head">
            <div class="proj-title">
              <el-input
                v-if="editingId === p.id" v-model="editName" size="small" class="proj-name-input"
                @keyup.enter="saveName(p)" @blur="saveName(p)"
              />
              <b v-else class="proj-name" @click="startEdit(p)">{{ p.name }}</b>
              <span class="proj-count">{{ p.repos.length }} 个仓库</span>
              <span v-if="p.ignored" class="proj-tag">已忽略</span>
            </div>
            <div class="proj-actions">
              <el-button size="small" round @click="toggleIgnore(p)">
                {{ p.ignored ? '恢复' : '忽略' }}
              </el-button>
              <el-button size="small" round type="danger" plain @click="removeProject(p)">删除</el-button>
            </div>
          </div>
          <div class="proj-repos">
            <code v-for="r in p.repos" :key="r">{{ r }}</code>
          </div>
          <el-input
            v-model="p._notes" size="small" class="proj-notes"
            placeholder="给 AI 的项目说明（可选），如：后端用 Spring Boot，前端 Vue3"
            @blur="saveNotes(p)"
          />
        </div>
        <div v-if="!projects.length" class="ih-muted proj-empty">
          还没有项目。填好扫描根后点「扫描仓库」。
        </div>
      </div>
    </section>

    <!-- 其他代码设置 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">⋯</span>
          <div>
            <h2>搜索与说明</h2>
            <p>影响 AI 在代码里找东西的效率</p>
          </div>
        </div>
      </div>
      <div class="field-grid">
        <label class="field field--wide">
          <span class="field-label">搜索跳过的目录（逗号分隔）</span>
          <el-input v-model="form['code.ignore']" />
          <span class="field-hint">默认排除 node_modules / target / dist / backup / import-json 等大目录</span>
        </label>
        <label class="field field--wide">
          <span class="field-label">全局项目说明</span>
          <el-input v-model="form['code.project_notes']" type="textarea" :rows="4" resize="none" />
          <span class="field-hint">拼进所有问题的提示词；单个项目自己的说明会追加在后面</span>
        </label>
      </div>
    </section>

    <!-- 执行器 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge">AI</span>
          <div>
            <h2>默认执行器</h2>
            <p>单次操作也可以在详情页临时切换</p>
          </div>
        </div>
      </div>

      <div class="provider-grid">
        <button
          v-for="p in providers"
          :key="p"
          class="provider-card"
          :class="{ 'is-on': form['ai.provider'] === p }"
          @click="form['ai.provider'] = p"
        >
          <span class="provider-name">{{ label(p) }}</span>
          <span class="provider-desc">{{ desc(p) }}</span>
        </button>
      </div>

      <div class="field-grid">
        <label class="field">
          <span class="field-label">超时（秒）</span>
          <el-input v-model="form['ai.timeout']" />
        </label>
        <label class="field field--wide">
          <span class="field-label">代码仓库根目录</span>
          <el-input v-model="form['repo.root']" placeholder="/src/gym-fold" />
          <span class="field-hint">dsh / claude 在这个目录下分析代码；多个仓库时填父目录</span>
        </label>
      </div>
    </section>

    <!-- DeepSeek -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--blue">DS</span>
          <div>
            <h2>DeepSeek API</h2>
            <p>最快的定性/定级通道，看不到代码</p>
          </div>
        </div>
        <el-tag v-if="form['deepseek.api_key_set']" type="success" effect="light">已配置 Key</el-tag>
      </div>

      <div class="field-grid">
        <label class="field field--wide">
          <span class="field-label">Base URL</span>
          <el-input v-model="form['deepseek.base_url']" />
        </label>
        <label class="field">
          <span class="field-label">模型</span>
          <el-input v-model="form['deepseek.model']" placeholder="deepseek-chat" />
        </label>
        <label class="field field--wide">
          <span class="field-label">API Key</span>
          <el-input
            v-model="form['deepseek.api_key']"
            type="password"
            show-password
            :placeholder="form['deepseek.api_key_set'] ? '已配置，留空表示不修改' : 'sk-...'"
          />
        </label>
      </div>
    </section>

    <!-- CLI -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">&gt;_</span>
          <div>
            <h2>命令行执行器</h2>
            <p>同机运行，能读仓库；只做只读分析，不改文件</p>
          </div>
        </div>
      </div>

      <div class="field-grid">
        <label class="field">
          <span class="field-label">dsh 命令</span>
          <el-input v-model="form['dsh.bin']" placeholder="dsh" />
        </label>
        <label class="field">
          <span class="field-label">dsh profile</span>
          <el-input v-model="form['dsh.profile']" placeholder="headless" />
        </label>
        <label class="field">
          <span class="field-label">claude 命令</span>
          <el-input v-model="form['claude.bin']" placeholder="claude" />
        </label>
        <label class="field">
          <span class="field-label">claude 模型</span>
          <el-input v-model="form['claude.model']" placeholder="留空用默认" />
        </label>
      </div>

      <p class="tip">
        命令不在默认 PATH 时填绝对路径（如 <code>~/.nvm/versions/node/v24.16.0/bin/claude</code>）。
        用 <code>./start.sh</code> 启动会自动补 nvm PATH。
      </p>
    </section>

    <div class="footer">
      <span class="ih-muted">定级规则版本：{{ rubricVersion }}</span>
      <el-button type="primary" round :loading="saving" @click="save">保存配置</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createProject, deleteProject, getProjects, getSettings, mergeProjects,
  saveSettings, scanRepos, updateProject, type Project, type ScanResult
} from '../api'
import { useTheme } from '../useTheme'

const { mode, setMode } = useTheme()
const form = reactive<Record<string, any>>({})
const providers = ref<string[]>([])
const rubricVersion = ref('')
const saving = ref(false)

/* ===== 项目 ===== */
const projects = ref<(Project & { _notes?: string })[]>([])
const scanPreview = ref<ScanResult | null>(null)
const scanning = ref(false)
const importing = ref(false)
const editingId = ref<number | null>(null)
const editName = ref('')

const loadProjects = async () => {
  const r = await getProjects().catch(() => null)
  if (r) projects.value = (r.projects || []).map((p) => ({ ...p, _notes: p.notes || '' }))
}

const doScan = async () => {
  // 先保存扫描根，否则后端还是用旧配置
  await save(true)
  scanning.value = true
  try {
    scanPreview.value = await scanRepos(true)
    const n = scanPreview.value.clusters.length
    if (!n) ElMessage.warning('没发现 git 仓库，检查扫描根是否正确')
    else ElMessage.success(`发现 ${scanPreview.value.scanned} 个仓库，${n} 个候选项目`)
  } catch {
    ElMessage.error('扫描失败')
  } finally {
    scanning.value = false
  }
}

/** 把扫描出的候选项目入库（只补新的，不动已有改名/说明） */
const doImport = async () => {
  importing.value = true
  try {
    const res = await scanRepos(false)
    scanPreview.value = res
    await loadProjects()
    const n = res.created?.length || 0
    ElMessage.success(n ? `已导入 ${n} 个新项目` : '没有新项目需要导入')
  } catch {
    ElMessage.error('导入失败')
  } finally {
    importing.value = false
  }
}

const startEdit = (p: Project) => {
  editingId.value = p.id
  editName.value = p.name
}
const saveName = async (p: Project) => {
  if (editingId.value !== p.id) return
  editingId.value = null
  const name = editName.value.trim()
  if (!name || name === p.name) return
  await updateProject(p.id, { name })
  p.name = name
  ElMessage.success('已改名')
}

const saveNotes = async (p: Project & { _notes?: string }) => {
  if ((p._notes || '') === (p.notes || '')) return
  await updateProject(p.id, { notes: p._notes || '' })
  p.notes = p._notes
}

const toggleIgnore = async (p: Project) => {
  await updateProject(p.id, { ignored: !p.ignored })
  p.ignored = !p.ignored
  ElMessage.success(p.ignored ? '已忽略（扫描不再提示）' : '已恢复')
}

const removeProject = async (p: Project) => {
  await ElMessageBox.confirm(`删除项目「${p.name}」？关联问题会变成「未指定项目」，但不会被删除。`,
    '提示', { type: 'warning' })
  await deleteProject(p.id)
  await loadProjects()
  ElMessage.success('已删除')
}

/** 把建议里的多个项目合并成一个（各自保留自己的 git 仓库） */
const doMergeSuggestion = async (sg: ScanResult['suggestions'][number]) => {
  await ElMessageBox.confirm(
    `把 ${sg.projects.map((x) => x.name).join('、')} 合并为「${sg.mergedName}」？` +
    '各仓库仍是独立的 git 仓库，只是归到同一个项目下。', '合并项目', { type: 'warning' })
  // 先确保这些候选已入库，才能拿到 id
  const res = await scanRepos(false)
  const all = res.projects || []
  const ids = sg.projects
    .map((x) => all.find((p) => p.name === x.name))
    .filter(Boolean)
    .map((p) => (p as Project).id)
  if (ids.length < 2) {
    ElMessage.error('候选项目还没入库，请先点「导入新项目」')
    return
  }
  await mergeProjects(ids[0], ids[1], sg.mergedName)
  await loadProjects()
  scanPreview.value = null
  ElMessage.success(`已合并为「${sg.mergedName}」`)
}

const label = (p: string) =>
  ({ mock: 'Mock', deepseek: 'DeepSeek API', dsh: 'dsh harness', claude: 'Claude Code' } as any)[p] || p
const desc = (p: string) =>
  ({
    mock: '假数据，验证流程，不花额度',
    deepseek: '快、便宜，仅看文字',
    dsh: '同机读仓库，DeepSeek 驱动',
    claude: '同机读仓库，适合深析'
  } as any)[p] || ''

const load = async () => {
  const res = await getSettings()
  Object.assign(form, res.settings)
  providers.value = res.providers
  rubricVersion.value = res.rubricVersion
}

const save = async (silent = false) => {
  saving.value = true
  try {
    const values: Record<string, any> = {}
    for (const [k, v] of Object.entries(form)) {
      if (k.endsWith('_set')) continue
      values[k] = v
    }
    await saveSettings(values)
    if (!silent) ElMessage.success('已保存')
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await load()
  await loadProjects()
})
</script>

<style scoped>
.settings { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
.page-title { margin: 0; font-size: 24px; font-weight: 700; }
.page-sub { margin: 4px 0 0; font-size: 13px; color: var(--ih-sub); }

.panel { padding: 18px 20px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.panel-title { display: flex; gap: 12px; align-items: flex-start; }
.panel-title h2 { margin: 0; font-size: 16px; font-weight: 700; }
.panel-title p { margin: 3px 0 0; font-size: 12px; color: var(--ih-sub); }
.step-badge {
  flex: 0 0 auto; min-width: 30px; height: 28px; padding: 0 8px; border-radius: 9px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
}
.step-badge--blue { background: linear-gradient(135deg, #1570ef, #2e90fa); }
.step-badge--gray { background: var(--ih-soft-2); color: var(--ih-sub); }

.provider-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
.provider-card {
  text-align: left; cursor: pointer; padding: 12px;
  border-radius: 12px; border: 1px solid var(--ih-line); background: var(--ih-card);
  display: flex; flex-direction: column; gap: 4px; transition: all 0.16s ease;
}
.provider-card:hover { border-color: var(--ih-line-strong); transform: translateY(-1px); }
.provider-card.is-on {
  border-color: var(--ih-primary);
  background: var(--el-color-primary-light-9);
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.15);
}
.provider-name { font-size: 14px; font-weight: 650; color: var(--ih-ink); }
.provider-desc { font-size: 12px; color: var(--ih-sub); line-height: 1.5; }

.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field--wide { grid-column: span 2; }
.field-label { font-size: 12px; color: var(--ih-sub); }
.field-hint { font-size: 12px; color: #98a2b3; }

.tip { margin: 14px 0 0; font-size: 12px; color: var(--ih-sub); line-height: 1.7; }
.tip code { background: var(--ih-soft-2); padding: 1px 6px; border-radius: 6px; color: var(--ih-ink); }

/* ---------- 项目 ---------- */
.scan-result { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
.scan-line { font-size: 12.5px; color: var(--ih-sub); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.scan-line code {
  background: var(--ih-soft-2); padding: 1px 7px; border-radius: 5px; font-size: 11.5px;
}
.scan-line b { color: var(--ih-ink); }
.suggest-box {
  display: flex; flex-direction: column; gap: 8px;
  padding: 10px 12px; border-radius: 10px;
  background: var(--ih-warn-soft); border: 1px solid rgba(247, 144, 9, 0.3);
}
.suggest-row {
  display: flex; justify-content: space-between; align-items: center;
  gap: 10px; flex-wrap: wrap; font-size: 12.5px; color: var(--ih-warn-ink);
}
.proj-list { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.proj-card {
  border: 1px solid var(--ih-line); border-radius: 12px; padding: 12px;
  display: flex; flex-direction: column; gap: 8px; background: var(--ih-soft);
}
.proj-card.is-ignored { opacity: 0.55; }
.proj-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.proj-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.proj-name { font-size: 14px; color: var(--ih-ink); cursor: pointer; }
.proj-name:hover { color: var(--el-color-primary); }
.proj-name-input { width: 180px; }
.proj-count { font-size: 11.5px; color: var(--ih-sub); }
.proj-tag {
  font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}
.proj-actions { display: flex; gap: 6px; }
.proj-repos { display: flex; flex-direction: column; gap: 2px; }
.proj-repos code { font-size: 11.5px; color: var(--ih-sub); word-break: break-all; }
.proj-notes { margin-top: 2px; }
.proj-empty { padding: 12px 0; }

.footer { display: flex; justify-content: space-between; align-items: center; padding: 4px 2px 10px; }

@media (max-width: 768px) {
  .page-head .el-button { display: none; }
  .panel { padding: 14px; }
  .provider-grid { grid-template-columns: 1fr 1fr; }
  .field-grid { grid-template-columns: 1fr; }
  .field--wide { grid-column: span 1; }
  .footer { position: sticky; bottom: calc(64px + env(safe-area-inset-bottom)); }
}
</style>
