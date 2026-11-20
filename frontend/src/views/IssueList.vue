<template>
  <div class="list-page">
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
        <el-button size="small" type="primary" round :loading="batchSaving" @click="applyBatch">应用</el-button>
        <el-button size="small" round @click="clearSelection">取消选择</el-button>
        <el-button size="small" type="danger" plain round @click="removeSelected">删除</el-button>
      </div>
    </div>

    <!-- 列表：桌面表格 -->
    <div v-if="!isMobile" class="table-card ih-card">
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
            <div class="cell-title">{{ row.title }}</div>
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
            <span class="status"><i :class="['dot', dotClass(row.status)]" />{{ row.status }}</span>
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
      <div v-if="total > pageSize" class="pager">
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
            <h3 class="m-title">{{ row.title }}</h3>
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
        <div class="form-grid">
          <el-form-item label="归属模块">
            <el-input v-model="form.module" placeholder="如 会员详情/预约记录" />
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
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">创建并打开</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchDeleteIssues, batchPatchIssues, createIssue, getWeeklyReport,
  listIssues, uploadAttachments
} from '../api'
import { useMobile } from '../useMobile'

const route = useRoute()
const router = useRouter()
const isMobile = useMobile()

const data = ref<{
  list: any[]; counts: Record<string, number>; statuses: string[]; tags?: string[]
}>({ list: [], counts: {}, statuses: [], tags: [] })
const filters = reactive({
  status: '', priority: '', module: '', q: '', tag: '', due: '', mine: ''
})
const loading = ref(false)

const createVisible = ref(false)
const saving = ref(false)
const form = reactive({ raw_text: '', module: '', reporter: '', source: 'wechat' })
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
      limit: pageSize,
      offset: (page.value - 1) * pageSize
    })
    data.value = res
    total.value = res.total ?? (res.list || []).length
    totalCount.value = Object.values(res.counts || {}).reduce((a: number, b: any) => a + Number(b), 0)
  } finally {
    loading.value = false
  }
}

/** 「我的」是个开关：点一次筛选，再点一次取消 */
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
const parseTags = (raw: string | null) => {
  if (!raw) return []
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : []
  } catch {
    return []
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
const batchForm = reactive<{ status: string; priority: string }>({ status: '', priority: '' })

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
  if (!payload.status && !payload.priority) {
    ElMessage.warning('请先选择要改成什么')
    return
  }
  batchSaving.value = true
  try {
    const r = await batchPatchIssues(payload)
    ElMessage.success(`已更新 ${r.updated} 条` + (r.skipped ? `，${r.skipped} 条无权限已跳过` : ''))
    batchForm.status = ''
    batchForm.priority = ''
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

const openCreate = () => {
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
    const { id } = await createIssue({ ...form })
    if (pendingFiles.value.length) await uploadAttachments(id, pendingFiles.value)
    createVisible.value = false
    router.push(`/issues/${id}`)
  } finally {
    saving.value = false
  }
}

onMounted(load)
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

@media (max-width: 1240px) {
  /* 一行放不下 6 个控件，让搜索框独占第二排 */
  .filter-row :deep(.w-240) { flex: 1 1 100%; }
}

/* 状态 chips 里的「我的」快捷入口 */
.chip-sep { width: 1px; height: 18px; background: var(--ih-line); margin: 0 4px; }
.chip--mine { font-size: 12px; }

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
