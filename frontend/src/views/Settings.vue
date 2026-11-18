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

    <!-- AI 通道 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge">AI</span>
          <div>
            <h2>AI 通道</h2>
            <p>填一个 OpenAI 兼容端点 + 模型即可；本地 claude/dsh 也能加成通道</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button round @click="openCreateChannel">＋ 新建通道</el-button>
        </div>
      </div>

      <div class="ch-list">
        <div v-for="c in channels" :key="c.id" class="ch-card" :class="{ 'is-default': defaultChannelId === c.id }">
          <div class="ch-head">
            <div class="ch-title">
              <b>{{ c.name }}</b>
              <span class="ch-kind" :class="`is-${c.kind}`">{{ kindLabel(c.kind) }}</span>
              <span v-if="defaultChannelId === c.id" class="ch-tag">默认</span>
              <span v-if="!c.enabled" class="ch-tag">已停用</span>
            </div>
            <div class="ch-actions">
              <el-button size="small" round :loading="testingId === c.id" @click="doTest(c)">测试</el-button>
              <el-button size="small" round @click="openEditChannel(c)">编辑</el-button>
              <el-button size="small" round type="danger" plain @click="removeChannel(c)">删除</el-button>
            </div>
          </div>
          <div class="ch-meta">
            <template v-if="c.kind === 'api'">
              <code>{{ c.base_url }}</code>
              <span class="ch-model">{{ c.model || '未选模型' }}</span>
              <span class="ch-key" :class="{ 'is-ok': c.hasKey }">{{ c.hasKey ? 'Key 已配' : '未配 Key' }}</span>
            </template>
            <template v-else-if="c.kind === 'agent'">
              <code>{{ c.command }}</code>
              <span class="ch-model">本地进程</span>
            </template>
            <template v-else>
              <span class="ih-muted">假数据通道，不消耗额度</span>
            </template>
          </div>
        </div>
        <div v-if="!channels.length" class="ih-muted ch-empty">
          还没有通道。点右上角「新建通道」填一个端点（如 <code>https://api.deepseek.com/v1</code>）。
        </div>
      </div>

      <div class="field-grid ch-globals">
        <label class="field">
          <span class="field-label">超时（秒）</span>
          <el-input v-model="form['ai.timeout']" />
        </label>
        <label class="field">
          <span class="field-label">默认通道</span>
          <el-select v-model="defaultChannelId" clearable placeholder="未设置" @change="saveDefaultChannel">
            <el-option v-for="c in channels" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </label>
      </div>
    </section>

    <!-- 通道编辑抽屉 -->
    <el-drawer v-model="chDrawer" :title="chForm.id ? '编辑通道' : '新建通道'" :size="isMobile ? '100%' : '620px'" append-to-body>
      <el-form label-position="top" class="ch-form">
        <el-form-item label="名称">
          <el-input v-model="chForm.name" placeholder="随便起，如 DeepSeek 官方 / xx 中转站" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="chForm.kind">
            <el-radio-button value="api">API 端点</el-radio-button>
            <el-radio-button value="agent">本地 Agent</el-radio-button>
            <el-radio-button value="mock">Mock</el-radio-button>
          </el-radio-group>
          <div class="field-hint">
            API 端点走 OpenAI 兼容格式，程序会自动带上读写文件的工具，因此也能改代码；
            本地 Agent 是 claude / dsh 这类自带工具的命令行。
          </div>
        </el-form-item>

        <template v-if="chForm.kind === 'api'">
          <el-form-item label="Base URL">
            <el-input v-model="chForm.base_url" placeholder="https://api.deepseek.com/v1" />
            <div class="field-hint">要带版本路径（多数是 <code>/v1</code>），程序会拼 <code>/chat/completions</code></div>
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="chForm.api_key" type="password" show-password
              :placeholder="chForm.hasKey ? '已配置，留空表示不修改' : 'sk-...'"
            />
          </el-form-item>
          <el-form-item label="模型">
            <div class="model-row">
              <el-select
                v-model="chForm.model" filterable allow-create default-first-option
                placeholder="先拉取，或直接手填模型名" class="model-select"
              >
                <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
              </el-select>
              <el-button round :loading="loadingModels" @click="fetchModels">拉取模型</el-button>
            </div>
          </el-form-item>
          <el-form-item label="温度">
            <el-input-number v-model="chForm.temperature" :min="0" :max="2" :step="0.1" />
          </el-form-item>
          <el-form-item label="工具循环最大轮数">
            <el-input-number v-model="chForm.max_rounds" :min="1" :max="100" />
            <div class="field-hint">改代码时模型会多轮读写文件，太小会半途而废</div>
          </el-form-item>
        </template>

        <template v-else-if="chForm.kind === 'agent'">
          <el-form-item label="命令">
            <el-input v-model="chForm.command" placeholder="claude 或 /home/you/.nvm/.../bin/claude" />
            <div class="field-hint">不在 PATH 里就填绝对路径；用 ./start.sh 启动会自动补 nvm 的 PATH</div>
          </el-form-item>
          <el-form-item label="额外参数（可选）">
            <el-input v-model="chForm.args" placeholder="如 --profile headless" />
          </el-form-item>
        </template>

        <el-form-item label="启用">
          <el-switch v-model="chForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="chDrawer = false">取消</el-button>
        <el-button type="primary" :loading="chSaving" @click="saveChannel">保存</el-button>
      </template>
    </el-drawer>


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
  createChannel, createProject, deleteChannel, deleteProject, getChannels, getProjects,
  getSettings, listChannelModels, mergeProjects, saveSettings, scanRepos, testChannel,
  updateChannel, updateProject,
  type Channel, type Project, type ScanResult
} from '../api'
import { useTheme } from '../useTheme'
import { useMobile } from '../useMobile'

const { mode, setMode } = useTheme()
const isMobile = useMobile()
const form = reactive<Record<string, any>>({})
const rubricVersion = ref('')
const saving = ref(false)

/* ===== AI 通道 ===== */
const channels = ref<Channel[]>([])
const defaultChannelId = ref<number | null>(null)
const testingId = ref(0)
const chDrawer = ref(false)
const chSaving = ref(false)
const loadingModels = ref(false)
const modelOptions = ref<string[]>([])
const chForm = reactive<Record<string, any>>({
  id: 0, name: '', kind: 'api', base_url: '', api_key: '', model: '',
  command: '', args: '', temperature: 0.2, max_rounds: 25, enabled: true, hasKey: false
})

const kindLabel = (k: string) =>
  ({ api: 'API', agent: '本地', mock: 'Mock' } as any)[k] || k

const loadChannels = async () => {
  const r = await getChannels().catch(() => null)
  channels.value = r?.channels || []
}

const resetChForm = () => {
  Object.assign(chForm, {
    id: 0, name: '', kind: 'api', base_url: '', api_key: '', model: '',
    command: '', args: '', temperature: 0.2, max_rounds: 25, enabled: true, hasKey: false
  })
  modelOptions.value = []
}

const openCreateChannel = () => {
  resetChForm()
  chDrawer.value = true
}

const openEditChannel = (c: Channel) => {
  resetChForm()
  Object.assign(chForm, {
    id: c.id, name: c.name, kind: c.kind, base_url: c.base_url || '',
    model: c.model || '', command: c.command || '', args: c.args || '',
    temperature: c.temperature ?? 0.2, max_rounds: c.max_rounds ?? 25,
    enabled: c.enabled, hasKey: c.hasKey
  })
  if (c.model) modelOptions.value = [c.model]
  chDrawer.value = true
}

/** 拉模型列表：key 可以现填，也可以复用通道里存的（不回显明文） */
const fetchModels = async () => {
  if (!chForm.base_url) {
    ElMessage.warning('先填 Base URL')
    return
  }
  loadingModels.value = true
  try {
    const r = await listChannelModels({
      base_url: chForm.base_url,
      api_key: chForm.api_key || undefined,
      channel_id: chForm.id || undefined
    })
    modelOptions.value = r.models
    ElMessage.success(`拉到 ${r.models.length} 个模型`)
    if (!chForm.model && r.models.length) chForm.model = r.models[0]
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '拉取失败，可以手填模型名')
  } finally {
    loadingModels.value = false
  }
}

const saveChannel = async () => {
  if (!chForm.name.trim()) {
    ElMessage.warning('通道名称不能为空')
    return
  }
  chSaving.value = true
  try {
    const payload: Record<string, any> = {
      name: chForm.name, kind: chForm.kind, base_url: chForm.base_url,
      model: chForm.model, command: chForm.command, args: chForm.args,
      temperature: chForm.temperature, max_rounds: chForm.max_rounds,
      enabled: chForm.enabled
    }
    if (chForm.api_key) payload.api_key = chForm.api_key
    if (chForm.id) await updateChannel(chForm.id, payload)
    else await createChannel(payload)
    chDrawer.value = false
    await loadChannels()
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    chSaving.value = false
  }
}

const doTest = async (c: Channel) => {
  testingId.value = c.id
  try {
    const r = await testChannel(c.id)
    ElMessage.success(`连通正常（${r.durationMs}ms）：${r.reply || r.model}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '测试失败')
  } finally {
    testingId.value = 0
  }
}

const removeChannel = async (c: Channel) => {
  await ElMessageBox.confirm(`删除通道「${c.name}」？`, '提示', { type: 'warning' })
  await deleteChannel(c.id)
  await loadChannels()
  if (defaultChannelId.value === c.id) {
    defaultChannelId.value = null
    await saveDefaultChannel()
  }
  ElMessage.success('已删除')
}

const saveDefaultChannel = async () => {
  await saveSettings({ 'ai.channel_id': defaultChannelId.value ? String(defaultChannelId.value) : '' })
}

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

const load = async () => {
  const res = await getSettings()
  Object.assign(form, res.settings)
  defaultChannelId.value = res.settings['ai.channel_id']
    ? Number(res.settings['ai.channel_id'])
    : null
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
  await loadChannels()
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

/* ---------- AI 通道 ---------- */
.ch-list { display: flex; flex-direction: column; gap: 10px; }
.ch-card {
  border: 1px solid var(--ih-line); border-radius: 12px; padding: 12px;
  background: var(--ih-soft); display: flex; flex-direction: column; gap: 8px;
}
.ch-card.is-default { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.ch-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
.ch-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ch-title b { font-size: 14px; color: var(--ih-ink); }
.ch-kind {
  font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}
.ch-kind.is-api { background: rgba(46, 144, 250, 0.14); color: #1570ef; }
.ch-kind.is-agent { background: rgba(124, 58, 237, 0.14); color: #7c3aed; }
.ch-tag {
  font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-primary-soft); color: var(--el-color-primary);
}
.ch-actions { display: flex; gap: 6px; }
.ch-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 11.5px; }
.ch-meta code { color: var(--ih-sub); word-break: break-all; }
.ch-model { color: var(--ih-ink); font-weight: 500; }
.ch-key { padding: 1px 7px; border-radius: 999px; background: rgba(240, 68, 56, 0.12); color: #f04438; }
.ch-key.is-ok { background: var(--ih-success-soft); color: var(--ih-success-ink); }
.ch-empty { padding: 14px 0; }
.ch-globals { margin-top: 14px; }
.ch-form :deep(.el-form-item) { margin-bottom: 14px; }
.model-row { display: flex; gap: 8px; width: 100%; }
.model-select { flex: 1; }

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
