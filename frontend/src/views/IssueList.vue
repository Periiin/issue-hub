<template>
  <div
    class="list-page"
    @dragover.prevent="dropActive = true"
    @dragleave.self="dropActive = false"
    @drop.prevent="onDropFiles"
  >
    <!-- 拖拽遮罩：截图拖进来直接弹新建 -->
    <div v-if="dropActive" class="drop-mask">
      <div class="drop-hint">松开即创建问题（图片/PDF 自动作为附件）</div>
    </div>
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h1 class="page-title">问题列表</h1>
        <p class="page-sub">甲方反馈 → AI 定性 → 人工确认 → 定级 → 修复</p>
      </div>
      <div class="head-actions">
        <el-button round :loading="weeklyLoading" @click="openWeekly">周报</el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filter-card ih-card">
      <div v-if="isMobile" class="search-row">
        <el-input v-model="filters.q" placeholder="搜索标题或原文" clearable @keyup.enter="load">
          <template #prefix><span class="search-ico">⌕</span></template>
        </el-input>
      </div>

      <!-- 项目：第一层归纳。项目多时横向滑动，不换行占两排 -->
      <div class="proj-chips">
        <button
          class="chip chip--proj" :class="{ 'is-on': !filters.project_id }"
          @click="setProject(0)"
        >
          全部项目 <b>{{ totalCount }}</b>
        </button>
        <button
          v-for="p in projectsWithCounts" :key="p.id"
          class="chip chip--proj" :class="{ 'is-on': filters.project_id === p.id }"
          @click="setProject(p.id)"
        >
          {{ p.name }} <b>{{ p.count }}</b>
        </button>
        <button
          v-if="data.unassigned"
          class="chip chip--proj chip--warn"
          :class="{ 'is-on': filters.project_id === -1 }"
          title="还没归到任何项目" @click="setProject(-1)"
        >
          未归属 <b>{{ data.unassigned }}</b>
        </button>

        <div class="chip-sep" />
        <button
          class="chip chip--view" :class="{ 'is-on': grouped }"
          title="按项目分段显示" @click="toggleGrouped"
        >{{ grouped ? '✓ ' : '' }}按项目分组</button>
      </div>

      <div class="chips">
        <button
          class="chip"
          :class="{ 'is-on': !filters.status }"
          @click="setStatus('')"
        >
          全部 <b>{{ totalCount }}</b>
        </button>
        <button
          v-for="s in statusOrder"
          :key="s"
          class="chip"
          :class="{ 'is-on': filters.status === s }"
          @click="setStatus(s)"
        >
          {{ s }} <b>{{ data.counts[s] || 0 }}</b>
        </button>
        <div class="chip-sep" />
        <button
          class="chip chip--mine" :class="{ 'is-on': filters.mine === 'assigned' }"
          title="分配给我的" @click="setMine('assigned')"
        >@ 我的</button>
        <button
          class="chip chip--mine" :class="{ 'is-on': filters.mine === 'reported' }"
          title="我提的" @click="setMine('reported')"
        >我提的</button>
      </div>

      <div v-if="!isMobile" class="filter-row">
        <el-select v-model="filters.priority" placeholder="优先级" clearable class="w-120">
          <el-option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :label="p" :value="p" />
        </el-select>
        <el-input v-model="filters.module" placeholder="模块" clearable class="w-140" />
        <el-select v-model="filters.tag" placeholder="标签" clearable class="w-120">
          <el-option v-for="t in data.tags || []" :key="t" :label="t" :value="t" />
        </el-select>
        <el-select v-model="filters.due" placeholder="截止" clearable class="w-120">
          <el-option label="已逾期" value="overdue" />
          <el-option label="7 天内到期" value="week" />
        </el-select>
        <el-select v-model="filters.mine" placeholder="我的" clearable class="w-120">
          <el-option label="分配给我" value="assigned" />
          <el-option label="我提的" value="reported" />
        </el-select>
        <el-input
          v-model="filters.q" placeholder="搜标题/原文/描述/模块/提出人"
          clearable class="w-240" @keyup.enter="applyFilter"
        />
        <el-button type="primary" plain @click="applyFilter">查询</el-button>
        <div class="spacer" />
        <span class="ih-muted count-label">共 {{ total }} 条</span>
      </div>
      <div v-else class="filter-row filter-row--mobile">
        <el-select v-model="filters.priority" placeholder="优先级" clearable class="w-110">
          <el-option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :label="p" :value="p" />
        </el-select>
        <el-input v-model="filters.module" placeholder="模块" clearable class="w-120" />
        <el-button plain @click="applyFilter">筛选</el-button>
      </div>
      <div v-if="isMobile" class="filter-row filter-row--mobile">
        <el-input
          v-model="filters.q" placeholder="搜标题/原文/描述/模块/提出人"
          clearable class="w-full" @keyup.enter="applyFilter"
        />
      </div>
    </div>

    <!-- 批量操作条：选中后才出现 -->
    <div v-if="selectedIds.length" class="batch-bar ih-card">
      <span class="batch-count">已选 <b>{{ selectedIds.length }}</b> 条</span>
      <div class="batch-actions">
        <el-select v-model="batchForm.status" placeholder="改状态" clearable size="small" class="batch-select">
          <el-option v-for="s in statusOrder" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="batchForm.priority" placeholder="改优先级" clearable size="small" class="batch-select">
          <el-option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="batchForm.project_id" placeholder="归属项目" clearable size="small" class="batch-select">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
        <el-button size="small" type="primary" round :loading="batchSaving" @click="applyBatch">应用</el-button>
        <el-button size="small" round @click="clearSelection">取消选择</el-button>
        <el-button size="small" type="danger" plain round @click="removeSelected">删除</el-button>
      </div>
    </div>

    <!-- 分组视图：按项目分段（桌面/手机共用同一套行） -->
    <div v-if="grouped" class="group-list">
      <el-skeleton v-if="loading" :rows="4" animated />
      <template v-else>
        <section v-for="g in groupedRows" :key="g.id" class="group-block ih-card">
          <div class="group-head" @click="toggleGroup(g.id)">
            <span class="group-arrow" :class="{ 'is-open': !collapsedGroups.has(g.id) }" />
            <span class="group-name">{{ g.name }}</span>
            <span class="group-count">{{ g.rows.length }} 条</span>
            <span class="group-dist">
              <span v-for="d in groupDist(g.rows)" :key="d.status" class="group-dist-item">
                <i :class="['dot', dotClass(d.status)]" />{{ d.status }} {{ d.n }}
              </span>
            </span>
          </div>
          <div v-show="!collapsedGroups.has(g.id)" class="group-body">
            <div
              v-for="row in g.rows" :key="row.id"
              class="g-row" @click="goDetail(row)"
            >
              <el-checkbox
                :model-value="selectedIds.includes(row.id)"
                class="g-check" @click.stop
                @change="() => toggleSelect(row.id)"
              />
              <span class="g-id ih-mono ih-muted">#{{ row.id }}</span>
              <span class="g-title">{{ row.title }}</span>
              <span :class="priorityClass(row.priority)">{{ row.priority || '未定' }}</span>
              <span class="status g-status"><i :class="['dot', dotClass(row.status)]" />{{ row.status }}</span>
              <span class="g-assignee" :class="{ 'ih-muted': !row.assignee }">{{ row.assignee ? '@' + row.assignee : '—' }}</span>
              <span v-if="row.due_date" :class="['due-cell', dueClass(row)]">{{ row.due_date.slice(5) }}</span>
              <span class="g-tags">
                <span v-for="t in parseTags(row.tags)" :key="t" class="cell-tag">{{ t }}</span>
              </span>
            </div>
          </div>
        </section>
        <el-empty
          v-if="!groupedRows.length"
          description="还没有记录，点右上角「新建问题」开始" :image-size="90"
        />
        <p v-if="total > data.list.length" class="group-hint ih-muted">
          按项目分组时一次最多显示 {{ data.list.length }} 条（共 {{ total }} 条），
          用上面的项目/状态筛选缩小范围。
        </p>
      </template>
    </div>

    <!-- 列表：桌面表格 -->
    <div v-else-if="!isMobile" class="table-card ih-card">
      <el-table
        ref="tableRef" :data="data.list" row-key="id" class="clickable"
        @row-click="goDetail" @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" :selectable="() => true" />
        <el-table-column label="#" width="64">
          <template #default="{ row }"><span class="ih-mono ih-muted">#{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column label="问题" min-width="280">
          <template #default="{ row }">
            <div class="cell-title" v-html="highlight(row.title)" />
            <div class="cell-sub">
              {{ row.module || '未标注模块' }} · {{ row.created_at }}
              <span v-for="t in parseTags(row.tags)" :key="t" class="cell-tag">{{ t }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="92">
          <template #default="{ row }"><span :class="priorityClass(row.priority)">{{ row.priority || '未定' }}</span></template>
        </el-table-column>
        <el-table-column label="等级" width="96">
          <template #default="{ row }">
            <span class="severity">{{ row.severity || '—' }}<i v-if="row.complexity"> / {{ row.complexity }}</i></span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <!-- 内联改状态：不用进详情。span.stop 防止冒泡到行点击 -->
            <span class="status-cell" @click.stop>
              <el-dropdown trigger="click" @command="(st: string) => inlineStatus(row, st)">
                <span class="status inline">
                  <i :class="['dot', dotClass(row.status)]" />{{ row.status }}
                  <i class="caret" />
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item
                      v-for="st in statusOrder" :key="st"
                      :command="st" :disabled="st === row.status"
                    >{{ st }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="96">
          <template #default="{ row }">
            <span :class="row.assignee ? '' : 'ih-muted'">{{ row.assignee || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="截止" width="104">
          <template #default="{ row }">
            <span v-if="!row.due_date" class="ih-muted">—</span>
            <span v-else :class="['due-cell', dueClass(row)]">{{ row.due_date.slice(5) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="提出人" width="96">
          <template #default="{ row }"><span class="ih-muted">{{ row.reporter || '—' }}</span></template>
        </el-table-column>
      </el-table>
      <el-empty
        v-if="!loading && !data.list.length"
        description="还没有记录，点右上角「新建问题」开始"
        :image-size="90"
      />
      <div v-if="total > pageSize && !grouped" class="pager">
        <el-button size="small" round :disabled="page === 1" @click="goPage(page - 1)">上一页</el-button>
        <span class="ih-muted">{{ page }} / {{ maxPage }} 页 · 共 {{ total }} 条</span>
        <el-button size="small" round :disabled="page >= maxPage" @click="goPage(page + 1)">下一页</el-button>
      </div>
    </div>

    <!-- 列表：手机卡片 -->
    <div v-else class="mobile-list">
      <el-skeleton v-if="loading" :rows="4" animated />
      <template v-else>
        <article v-for="row in data.list" :key="row.id" class="m-card" @click="goDetail(row)">
          <div class="m-card-top">
            <span :class="priorityClass(row.priority)">{{ row.priority || '未定级' }}</span>
            <h3 class="m-title" v-html="highlight(row.title)" />
          </div>
          <div class="m-meta">
            <span class="status"><i :class="['dot', dotClass(row.status)]" />{{ row.status }}</span>
            <span v-if="row.severity">{{ row.severity }}<template v-if="row.complexity"> · {{ row.complexity }}</template></span>
            <span class="m-id">#{{ row.id }}</span>
          </div>
          <div class="m-foot">
            <span>{{ row.module || '未标注模块' }}</span>
            <span v-if="row.assignee">@{{ row.assignee }}</span>
            <span v-if="row.due_date" :class="['due-cell', dueClass(row)]">截止 {{ row.due_date.slice(5) }}</span>
            <span>{{ (row.created_at || '').slice(5, 16) }}</span>
          </div>
        </article>
        <el-empty v-if="!data.list.length" description="还没有记录" :image-size="80" />
        <div v-if="total > pageSize" class="pager">
          <el-button size="small" round :disabled="page === 1" @click="goPage(page - 1)">上一页</el-button>
          <span class="ih-muted">{{ page }} / {{ maxPage }} 页</span>
          <el-button size="small" round :disabled="page >= maxPage" @click="goPage(page + 1)">下一页</el-button>
        </div>
      </template>
    </div>

    <!-- 周报 -->
    <el-dialog
      v-model="weeklyVisible" title="问题跟踪周报"
      :width="isMobile ? '100%' : '760px'" :fullscreen="isMobile" append-to-body
    >
      <div class="weekly-bar">
        <el-radio-group v-model="weeklyDays" size="small" @change="loadWeekly">
          <el-radio-button :value="0">本周</el-radio-button>
          <el-radio-button :value="7">最近 7 天</el-radio-button>
          <el-radio-button :value="30">最近 30 天</el-radio-button>
        </el-radio-group>
        <div class="spacer" />
        <el-button size="small" round @click="copyWeekly">复制 Markdown</el-button>
        <el-button size="small" round @click="downloadWeekly">下载 .md</el-button>
      </div>
      <pre class="weekly-pre">{{ weeklyText }}</pre>
      <template #footer>
        <el-button @click="weeklyVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新建问题 -->
    <el-dialog
      v-model="createVisible"
      title="新建问题"
      :width="isMobile ? '100%' : '640px'"
      :fullscreen="isMobile"
      append-to-body
      class="create-dialog"
    >
      <el-form label-position="top">
        <el-form-item label="原始描述">
          <el-input
            v-model="form.raw_text"
            type="textarea"
            :rows="isMobile ? 6 : 5"
            placeholder="把甲方在微信里的原话粘进来；截图可以直接 Ctrl+V 粘贴"
            @paste="onPaste"
          />
          <div class="field-hint">支持直接粘贴截图（微信截图后 Ctrl+V），也可以下面选择图片</div>
        </el-form-item>
        <el-form-item label="截图 / 附件">
          <div class="upload-box">
            <input ref="fileInput" type="file" accept="image/*,application/pdf" multiple @change="onPickFiles" hidden />
            <el-button round @click="fileInput?.click()">选择文件</el-button>
            <span class="ih-muted">{{ pendingFiles.length ? `已选 ${pendingFiles.length} 个` : '未选择' }}</span>
          </div>
          <div v-if="pendingFiles.length" class="pending">
            <el-tag v-for="(f, i) in pendingFiles" :key="i" closable @close="pendingFiles.splice(i, 1)">
              {{ f.name }}
            </el-tag>
          </div>
        </el-form-item>
        <el-form-item label="归属项目">
          <el-select
            v-model="form.project_id" clearable placeholder="不选则按模块/路径自动判断"
            class="w-full"
          >
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div v-if="guessHint" class="field-hint guess-hint">{{ guessHint }}</div>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="归属模块">
            <el-input
              v-model="form.module" placeholder="如 会员详情/预约记录"
              @input="refreshGuess"
            />
          </el-form-item>
          <el-form-item label="提出人">
            <el-input v-model="form.reporter" placeholder="如 王姐" />
          </el-form-item>
        </div>
        <el-form-item label="来源">
          <el-radio-group v-model="form.source">
            <el-radio-button value="wechat">微信</el-radio-button>
            <el-radio-button value="phone">电话</el-radio-button>
            <el-radio-button value="meeting">会议</el-radio-button>
            <el-radio-button value="manual">其他</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="create-foot">
          <el-checkbox v-model="autoQualify">保存后自动定性</el-checkbox>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitCreate">
            {{ autoQualify ? '创建并定性' : '创建并打开' }}
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchDeleteIssues, batchPatchIssues, createIssue, getProjects, getWeeklyReport,
  listIssues, patchIssue, uploadAttachments
} from '../api'
import { useMobile } from '../useMobile'

const route = useRoute()
const router = useRouter()
const isMobile = useMobile()

const data = ref<{
  list: any[]; counts: Record<string, number>; statuses: string[]; tags?: string[]
  projectCounts?: Record<string, number>; unassigned?: number
}>({ list: [], counts: {}, statuses: [], tags: [], projectCounts: {}, unassigned: 0 })

/** 项目列表（名字来自 /api/projects，计数来自列表接口） */
const projects = ref<{ id: number; name: string }[]>([])
const projectsWithCounts = computed(() =>
  projects.value
    .map((p) => ({ ...p, count: data.value.projectCounts?.[String(p.id)] || 0 }))
    // 有问题的排前面，没问题的沉底，但不隐藏（可能正要往里录第一条）
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
)

/* ---------- 分组视图 ---------- */
const grouped = ref(localStorage.getItem('ih-group-projects') === '1')

const toggleGrouped = () => {
  grouped.value = !grouped.value
  localStorage.setItem('ih-group-projects', grouped.value ? '1' : '0')
  // 两种模式的 limit 不同（分组要一次拉全），切换后必须重拉
  page.value = 1
  load()
}

/** 折叠状态：默认全展开 */
const collapsedGroups = ref<Set<number>>(new Set())

const toggleGroup = (gid: number) => {
  const next = new Set(collapsedGroups.value)
  if (next.has(gid)) next.delete(gid)
  else next.add(gid)
  collapsedGroups.value = next
}

/** 组内状态分布（只用当前显示的这些行算，够看个大概） */
const groupDist = (rows: any[]) => {
  const m = new Map<string, number>()
  for (const r of rows) m.set(r.status, (m.get(r.status) || 0) + 1)
  return [...m.entries()]
    .map(([status, n]) => ({ status, n }))
    .sort((a, b) => b.n - a.n)
}

/** 分组视图里也能勾选（表格的 checkbox 在分组视图里不存在） */
const toggleSelect = (id: number) => {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = [...next]
}

/** 按项目把当前页的数据分段（无项目归「未归属」） */
const groupedRows = computed(() => {
  const byId = new Map<number, { id: number; name: string; rows: any[] }>()
  const noProject = { id: 0, name: '未归属', rows: [] as any[] }
  for (const row of data.value.list) {
    const pid = row.project_id
    if (!pid) {
      noProject.rows.push(row)
      continue
    }
    if (!byId.has(pid)) {
      const meta = projects.value.find((p) => p.id === pid)
      byId.set(pid, { id: pid, name: meta?.name || `项目 ${pid}`, rows: [] })
    }
    byId.get(pid)!.rows.push(row)
  }
  const groups = [...byId.values()].sort((a, b) => b.rows.length - a.rows.length)
  if (noProject.rows.length) groups.push(noProject)
  return groups
})
const filters = reactive<{
  status: string; priority: string; module: string; q: string
  tag: string; due: string; mine: string; project_id: number
}>({
  status: '', priority: '', module: '', q: '', tag: '', due: '', mine: '',
  // 0 = 不筛；-1 = 未归属；其余是项目 id
  project_id: 0
})
const loading = ref(false)

const createVisible = ref(false)
const saving = ref(false)
const form = reactive<{
  raw_text: string; module: string; reporter: string; source: string
  project_id: number | null
}>({ raw_text: '', module: '', reporter: '', source: 'wechat', project_id: null })

/**
 * 按模块名猜项目（和后台同一套规则：项目名是模块名的子串且唯一命中）。
 * 只做提示，不自动填 —— 猜错比不猜更难发现。
 */
const guessProject = computed(() => {
  const m = (form.module || '').trim().toLowerCase()
  if (!m) return null
  const hits = projects.value.filter((p) => m.includes(p.name.toLowerCase()))
  return hits.length === 1 ? hits[0] : null
})

const guessHint = computed(() => {
  if (form.project_id || !guessProject.value) return ''
  return `看起来属于「${guessProject.value.name}」，保存时会自动归到这个项目`
})

/** 模块输入后让提示跟着变（computed 已经响应，这里只是占位避免 lint 抱怨） */
const refreshGuess = () => {}
const pendingFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)

const statusOrder = ['待定性', '待定级', '待处理', '处理中', '待验收', '已解决', '不修', '无法复现']
const totalCount = ref(0)

/* ---------- 分页 ---------- */
const pageSize = 50
const page = ref(1)
const total = ref(0)
const maxPage = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const goPage = (n: number) => {
  if (n < 1 || n > maxPage.value) return
  page.value = n
  load()
}

/** 改筛选条件必须回到第 1 页，否则会停在超出范围的空页 */
const applyFilter = () => {
  page.value = 1
  load()
}

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

const load = async () => {
  loading.value = true
  try {
    const res = await listIssues({
      ...filters,
      // 0 表示不筛，别把 0 传给后端（后端 0 也是不筛，但少个参数更干净）
      project_id: filters.project_id || undefined,
      // 分组时一次多拉些，否则同一项目会被翻页切断；分组模式下不翻页
      limit: grouped.value ? 200 : pageSize,
      offset: grouped.value ? 0 : (page.value - 1) * pageSize
    })
    data.value = res
    total.value = res.total ?? (res.list || []).length
    totalCount.value = Object.values(res.counts || {}).reduce((a: number, b: any) => a + Number(b), 0)
  } finally {
    loading.value = false
  }
}

/** 「我的」是个开关：点一次筛选，再点一次取消 */
/** 项目 chip：点一次筛选，再点同一项取消 */
const setProject = (pid: number) => {
  filters.project_id = filters.project_id === pid ? 0 : pid
  page.value = 1
  load()
}


const setMine = (mode: string) => {
  filters.mine = filters.mine === mode ? '' : mode
  page.value = 1
  load()
}

const setStatus = (s: string) => {
  filters.status = s
  page.value = 1
  load()
}
/** 搜索命中高亮：先转义再包 <mark>，标题是甲方输入，必须防 XSS */
const esc = (t: string) =>
  t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const highlight = (text: string) => {
  const q = (filters.q || '').trim()
  const safe = esc(text)
  if (!q) return safe
  try {
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
    return safe.replace(re, '<mark>$1</mark>')
  } catch {
    return safe
  }
}

/** 「待验收」超过 N 天没动静，提示一下（验收是流程最后一步，最容易忘） */
const ACCEPT_STALE_DAYS = 3

const staleAccept = (row: any) => {
  if (row.status !== '待验收') return null
  const t = new Date((row.updated_at || '').replace(' ', 'T')).getTime()
  if (!t) return null
  const days = Math.floor((Date.now() - t) / 86400000)
  return days >= ACCEPT_STALE_DAYS ? days : null
}

const parseTags = (raw: string | null) => {
  if (!raw) return []
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

/** 内联改状态：直接 PATCH，成功后本地更新那行（不整页重拉，保持滚动位置） */
const inlineStatus = async (row: any, status: string) => {
  if (status === row.status) return
  try {
    await patchIssue(row.id, { status })
    row.status = status
    ElMessage.success(`#${row.id} → ${status}`)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  }
}

/** 截止日期着色：逾期红、3 天内黄；已关闭的不提示 */
const dueClass = (row: any) => {
  if (!row.due_date) return ''
  if (['已解决', '不修', '无法复现'].includes(row.status)) return ''
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round(
    (new Date(row.due_date + 'T00:00:00').getTime() - today.getTime()) / 86400000
  )
  if (days < 0) return 'is-over'
  if (days <= 3) return 'is-soon'
  return ''
}

const goDetail = (row: any) => router.push(`/issues/${row.id}`)
/* ---------- 批量操作 ---------- */
const tableRef = ref<any>(null)
const selectedIds = ref<number[]>([])
const batchSaving = ref(false)
const batchForm = reactive<{ status: string; priority: string; project_id: number | null }>(
  { status: '', priority: '', project_id: null }
)

const onSelectionChange = (rows: any[]) => {
  selectedIds.value = rows.map((r) => r.id)
}

const clearSelection = () => {
  selectedIds.value = []
  tableRef.value?.clearSelection?.()
}

const applyBatch = async () => {
  const payload: Record<string, any> = { ids: selectedIds.value }
  if (batchForm.status) payload.status = batchForm.status
  if (batchForm.priority) payload.priority = batchForm.priority
  if (batchForm.project_id) payload.project_id = batchForm.project_id
  if (!payload.status && !payload.priority && !payload.project_id) {
    ElMessage.warning('请先选择要改成什么')
    return
  }
  batchSaving.value = true
  try {
    const r = await batchPatchIssues(payload)
    ElMessage.success(`已更新 ${r.updated} 条` + (r.skipped ? `，${r.skipped} 条无权限已跳过` : ''))
    batchForm.status = ''
    batchForm.priority = ''
    batchForm.project_id = null
    clearSelection()
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '批量修改失败')
  } finally {
    batchSaving.value = false
  }
}

const removeSelected = async () => {
  await ElMessageBox.confirm(
    `删除选中的 ${selectedIds.value.length} 条问题？附件和记录会一起删掉，不能撤销。`,
    '提示', { type: 'warning' })
  const r = await batchDeleteIssues(selectedIds.value)
  ElMessage.success(`已删除 ${r.deleted} 条` + (r.skipped ? `，${r.skipped} 条无权限已跳过` : ''))
  clearSelection()
  await load()
}

/* ---------- 周报 ---------- */
const weeklyVisible = ref(false)
const weeklyLoading = ref(false)
const weeklyText = ref('')
const weeklyDays = ref(0)

const loadWeekly = async () => {
  weeklyLoading.value = true
  try {
    weeklyText.value = await getWeeklyReport(weeklyDays.value)
  } catch (e: any) {
    weeklyText.value = `生成失败：${e?.response?.data?.detail || e?.message || '未知错误'}`
  } finally {
    weeklyLoading.value = false
  }
}

const openWeekly = async () => {
  weeklyVisible.value = true
  if (!weeklyText.value) await loadWeekly()
}

const copyWeekly = async () => {
  try {
    await navigator.clipboard.writeText(weeklyText.value)
    ElMessage.success('已复制，可直接粘到群里')
  } catch {
    // 非 https 下 clipboard 不可用，退回选中文本让用户手动复制
    ElMessage.warning('当前环境不支持自动复制，请手动选中文本复制')
  }
}

const downloadWeekly = () => {
  const blob = new Blob([weeklyText.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `问题周报-${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

/** 保存后自动定性：省「跳详情→点定性」两步 */
const autoQualify = ref(true)

/* ---------- 拖拽截图直接建问题 ---------- */
const dropActive = ref(false)

const onDropFiles = (e: DragEvent) => {
  dropActive.value = false
  const files = [...(e.dataTransfer?.files || [])]
  if (!files.length) return
  const ok = files.filter((f) => f.type.startsWith('image/') || f.type === 'application/pdf')
  const skipped = files.length - ok.length
  if (!ok.length) {
    ElMessage.warning('只支持图片和 PDF 附件')
    return
  }
  pendingFiles.value = [...pendingFiles.value, ...ok]
  openCreate()
  ElMessage.success(
    `已带 ${ok.length} 个附件` + (skipped ? `，${skipped} 个不支持的类型已忽略` : '')
  )
}

const openCreate = () => {
  form.project_id = null
  form.raw_text = ''
  form.module = ''
  form.reporter = ''
  form.source = 'wechat'
  pendingFiles.value = []
  createVisible.value = true
}

// 手机底部「＋」和桌面顶部按钮都通过 ?new=1 触发
watch(
  () => route.query.new,
  (v) => {
    if (v === '1') {
      openCreate()
      router.replace({ path: '/issues', query: {} })
    }
  },
  { immediate: true }
)

const onPaste = (e: ClipboardEvent) => {
  const files = Array.from(e.clipboardData?.files || [])
  if (files.length) {
    pendingFiles.value.push(...files)
    ElMessage.success(`已添加 ${files.length} 张截图`)
  }
}
const onPickFiles = (e: Event) => {
  const input = e.target as HTMLInputElement
  if (input.files?.length) pendingFiles.value.push(...Array.from(input.files))
  input.value = ''
}

const submitCreate = async () => {
  if (!form.raw_text.trim() && !pendingFiles.value.length) {
    ElMessage.warning('至少填一段描述或放一张截图')
    return
  }
  saving.value = true
  try {
    const guessed = !form.project_id && guessProject.value
    const { id } = await createIssue({ ...form })
    if (pendingFiles.value.length) await uploadAttachments(id, pendingFiles.value)
    if (guessed) ElMessage.success(`已自动归到「${guessProject.value!.name}」`)
    createVisible.value = false
    // 连招：带 autostart 参数，详情页落地即跑定性
    router.push(`/issues/${id}${autoQualify.value ? '?autostart=qualify' : ''}`)
  } finally {
    saving.value = false
  }
}

const loadProjects = async () => {
  try {
    const r = await getProjects()
    projects.value = (r.projects || []).map((p: any) => ({ id: p.id, name: p.name }))
  } catch {
    projects.value = []
  }
}

onMounted(async () => {
  await Promise.all([load(), loadProjects()])
})
</script>

<style scoped>
.list-page { display: flex; flex-direction: column; gap: 14px; }

.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
.page-title { margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.2px; }
.page-sub { margin: 4px 0 0; font-size: 13px; color: var(--ih-sub); }
.head-actions { display: flex; gap: 8px; }

.filter-card { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chip {
  flex: 0 0 auto; border: 1px solid var(--ih-line); background: var(--ih-card);
  color: var(--ih-sub); border-radius: 999px; padding: 6px 14px; font-size: 13px;
  cursor: pointer; transition: all 0.16s ease; white-space: nowrap;
}
.chip b { font-weight: 600; margin-left: 2px; color: var(--ih-sub); }
.chip:hover { border-color: var(--ih-line-strong); }
.chip.is-on {
  color: #fff; border-color: transparent;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  box-shadow: 0 6px 14px rgba(79, 70, 229, 0.25);
}
.chip.is-on b { color: rgba(255, 255, 255, 0.85); }

.filter-row {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
/* el-select 默认 flex-shrink:1 会被挤成「优...」，固定住宽度 */
.filter-row :deep(.el-select),
.filter-row :deep(.el-input) { flex: 0 0 auto; }
/* 搜索框吃剩余空间，但别小于 180px */
.filter-row :deep(.w-240) { flex: 1 1 180px; min-width: 180px; }
.count-label { white-space: nowrap; flex: 0 0 auto; }
.filter-row--mobile { justify-content: space-between; }
.spacer { flex: 1; }
.w-110 { width: 110px; }
.w-120 { width: 120px; }
.w-140 { width: 140px; }
.w-200 { width: 200px; }
.w-260 { width: 260px; }
.w-full { width: 100%; }

@media (max-width: 768px) {
  /* 「按项目分组」在横向滑动条里容易被挤出去，单独一行更稳 */
  .proj-chips { flex-wrap: wrap; overflow-x: visible; }
  .chip--view { margin-left: auto; }

  /* 分组行在窄屏放不下全部列，隐藏负责人和标签，保留标题+优先级+状态 */
  .g-assignee, .g-tags { display: none; }
  .g-row { padding: 9px 12px; gap: 8px; }
  .group-head { padding: 10px 12px; }
  .group-dist { margin-left: 0; flex: 1 1 100%; }
}

@media (max-width: 1240px) {
  /* 一行放不下 6 个控件，让搜索框独占第二排 */
  .filter-row :deep(.w-240) { flex: 1 1 100%; }
}

.guess-hint { color: var(--ih-primary); }

/* 项目 chips：横向滑动，不换行占两排 */
.proj-chips {
  display: flex; align-items: center; gap: 6px;
  overflow-x: auto; padding-bottom: 2px;
  scrollbar-width: none;
}
.proj-chips::-webkit-scrollbar { display: none; }
.chip--proj { white-space: nowrap; flex: 0 0 auto; }
.chip--warn { color: #f79009; }
.chip--view { flex: 0 0 auto; white-space: nowrap; }

/* 分组视图 */
.group-list { display: flex; flex-direction: column; gap: 10px; }
.group-block { padding: 0; overflow: hidden; }
.group-head {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 12px 16px; cursor: pointer; user-select: none;
  border-bottom: 1px solid var(--ih-line);
}
.group-head:hover { background: var(--ih-soft); }
.group-arrow {
  flex: 0 0 auto; width: 8px; height: 8px;
  border-right: 2px solid var(--ih-sub); border-bottom: 2px solid var(--ih-sub);
  transform: rotate(-45deg); transition: transform 0.16s ease;
}
.group-arrow.is-open { transform: rotate(45deg); }
.group-name { font-size: 14px; font-weight: 700; color: var(--ih-ink); }
.group-count {
  font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: var(--ih-primary-soft); color: var(--ih-primary);
}
.group-dist { display: flex; gap: 10px; flex-wrap: wrap; margin-left: auto; font-size: 11px; color: var(--ih-sub); }
.group-dist-item { display: inline-flex; align-items: center; gap: 4px; }
.group-body { padding: 4px 0; }
.g-row {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 16px; cursor: pointer; font-size: 13px;
  border-bottom: 1px solid var(--ih-line);
}
.g-row:last-child { border-bottom: none; }
.g-row:hover { background: var(--ih-soft); }
.g-check { flex: 0 0 auto; }
.g-id { flex: 0 0 auto; font-size: 11.5px; }
.g-title {
  flex: 1 1 auto; min-width: 0; color: var(--ih-ink);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.g-status { flex: 0 0 auto; font-size: 11.5px; }
.g-assignee { flex: 0 0 auto; font-size: 11.5px; }
.g-tags { flex: 0 0 auto; }
.group-hint { font-size: 12px; text-align: center; padding: 8px 0; }

/* 状态 chips 里的「我的」快捷入口 */
.chip-sep { width: 1px; height: 18px; background: var(--ih-line); margin: 0 4px; }
.chip--mine { font-size: 12px; }

mark { background: rgba(247, 144, 9, 0.35); color: inherit; padding: 0 1px; border-radius: 3px; }
html.dark mark { background: rgba(247, 144, 9, 0.45); }
.stale-mark {
  font-style: normal; font-size: 10px; padding: 0 5px; border-radius: 999px;
  background: rgba(247, 144, 9, 0.15); color: #f79009; font-weight: 600;
}

/* 内联状态下拉 */
.status-cell { display: inline-flex; align-items: center; }
.status.inline { cursor: pointer; border-radius: 8px; padding: 2px 6px; transition: background 0.15s; }
.status.inline:hover { background: var(--ih-soft); }
.status.inline .caret {
  width: 6px; height: 6px; border-right: 1.5px solid var(--ih-sub);
  border-bottom: 1.5px solid var(--ih-sub);
  transform: rotate(45deg) translateY(-2px); margin-left: 4px; opacity: 0.6;
}

/* 标签与截止 */
.cell-tag {
  display: inline-block; margin-left: 5px; padding: 0 6px;
  border-radius: 999px; font-size: 10.5px;
  background: var(--ih-primary-soft); color: var(--ih-primary);
}
.due-cell { font-size: 11.5px; }
.due-cell.is-over { color: #f04438; font-weight: 600; }
.due-cell.is-soon { color: #f79009; font-weight: 600; }

/* 批量操作条 */
.batch-bar {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 14px; margin-bottom: 10px;
  border: 1px solid var(--ih-primary);
  background: var(--ih-primary-soft);
}
.batch-count { font-size: 13px; color: var(--ih-ink); }
.batch-count b { color: var(--ih-primary); }
.batch-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.batch-select { width: 130px; }

/* 周报 */
.weekly-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.weekly-pre {
  margin: 0; padding: 14px 16px; max-height: 56vh; overflow: auto;
  border-radius: 12px; border: 1px solid var(--ih-line); background: var(--ih-soft);
  font-size: 12.5px; line-height: 1.75; color: var(--ih-ink);
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* 分页条 */
.drop-mask {
  position: fixed; inset: 0; z-index: 40;
  background: rgba(79, 70, 229, 0.08);
  border: 2px dashed var(--ih-primary);
  border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  pointer-events: none;
}
.drop-hint {
  padding: 14px 26px; border-radius: 12px; font-size: 14px; font-weight: 600;
  background: var(--ih-card); color: var(--ih-primary);
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.18);
}
.create-foot { display: flex; align-items: center; flex: 1; }
.create-foot .el-checkbox { margin-right: auto; }
.pager {
  display: flex; align-items: center; justify-content: center;
  gap: 12px; padding: 14px 0 4px; font-size: 12px;
}

.table-card { padding: 6px 10px 10px; overflow: hidden; }
.clickable :deep(tbody tr) { cursor: pointer; }
.clickable :deep(tbody tr:hover) { background: var(--ih-soft); }
.cell-title { font-weight: 600; font-size: 14px; color: var(--ih-ink); }
.cell-sub { font-size: 12px; color: var(--ih-sub); margin-top: 2px; }
.severity { font-size: 13px; color: var(--ih-ink); }
.severity i { color: var(--ih-sub); font-style: normal; }
.status { display: inline-flex; align-items: center; font-size: 13px; color: var(--ih-ink); }

/* 手机卡片 */
.mobile-list { display: flex; flex-direction: column; gap: 10px; }
.m-card {
  background: var(--ih-card); border-radius: 14px; padding: 14px;
  box-shadow: var(--ih-shadow); border: 1px solid var(--ih-line);
  transition: transform 0.14s ease, box-shadow 0.14s ease;
}
.m-card:active { transform: scale(0.99); box-shadow: var(--ih-shadow-hover); }
.m-card-top { display: flex; align-items: flex-start; gap: 8px; }
.m-title { margin: 0; font-size: 15px; font-weight: 650; line-height: 1.35; flex: 1; }
.m-meta {
  display: flex; align-items: center; gap: 12px; margin-top: 8px;
  font-size: 12px; color: var(--ih-sub); flex-wrap: wrap;
}
.m-id { margin-left: auto; color: var(--ih-sub); opacity: 0.85; }
.m-foot {
  display: flex; gap: 10px; margin-top: 10px; padding-top: 10px;
  border-top: 1px dashed var(--ih-line);
  font-size: 12px; color: var(--ih-sub);
}
.m-foot span:last-child { margin-left: auto; }

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field-hint { font-size: 12px; color: var(--ih-sub); margin-top: 4px; }
.upload-box { display: flex; align-items: center; gap: 10px; }
.pending { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.search-row { width: 100%; }
.search-ico { color: var(--ih-sub); font-size: 16px; }

@media (max-width: 768px) {
  .page-title { font-size: 20px; }
  .page-sub { display: none; }
  .head-actions { display: none; }
  .form-grid { grid-template-columns: 1fr; }
}
</style>
