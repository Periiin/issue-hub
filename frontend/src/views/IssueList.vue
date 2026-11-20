<template>
  <div class="list-page">
    <!-- 页头 -->
    <div class="page-head">
      <div>
        <h1 class="page-title">问题列表</h1>
        <p class="page-sub">甲方反馈 → AI 定性 → 人工确认 → 定级 → 修复</p>
      </div>
      <div class="head-actions">
        <el-button round @click="downloadWeekly">导出周报</el-button>
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
      </div>

      <div v-if="!isMobile" class="filter-row">
        <el-select v-model="filters.priority" placeholder="优先级" clearable class="w-120">
          <el-option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :label="p" :value="p" />
        </el-select>
        <el-input v-model="filters.module" placeholder="模块" clearable class="w-140" />
        <el-input
          v-model="filters.q" placeholder="搜标题/原文/描述/模块/提出人"
          clearable class="w-260" @keyup.enter="applyFilter"
        />
        <el-button type="primary" plain @click="applyFilter">查询</el-button>
        <div class="spacer" />
        <span class="ih-muted">共 {{ total }} 条</span>
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

    <!-- 列表：桌面表格 -->
    <div v-if="!isMobile" class="table-card ih-card">
      <el-table :data="data.list" row-key="id" class="clickable" @row-click="goDetail">
        <el-table-column label="#" width="64">
          <template #default="{ row }"><span class="ih-mono ih-muted">#{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column label="问题" min-width="280">
          <template #default="{ row }">
            <div class="cell-title">{{ row.title }}</div>
            <div class="cell-sub">{{ row.module || '未标注模块' }} · {{ row.created_at }}</div>
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
        <el-table-column label="提出人" width="110">
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
            <span>{{ row.reporter || '—' }}</span>
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
import { ElMessage } from 'element-plus'
import { createIssue, listIssues, uploadAttachments } from '../api'
import { useMobile } from '../useMobile'

const route = useRoute()
const router = useRouter()
const isMobile = useMobile()

const data = ref<{ list: any[]; counts: Record<string, number>; statuses: string[] }>({
  list: [], counts: {}, statuses: []
})
const filters = reactive({ status: '', priority: '', module: '', q: '' })
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

const setStatus = (s: string) => {
  filters.status = s
  page.value = 1
  load()
}
const goDetail = (row: any) => router.push(`/issues/${row.id}`)
const downloadWeekly = () => window.open('/api/report/weekly', '_blank')

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

.filter-row { display: flex; gap: 8px; align-items: center; }
.filter-row--mobile { justify-content: space-between; }
.spacer { flex: 1; }
.w-110 { width: 110px; }
.w-120 { width: 120px; }
.w-140 { width: 140px; }
.w-200 { width: 200px; }
.w-260 { width: 260px; }
.w-full { width: 100%; }

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
