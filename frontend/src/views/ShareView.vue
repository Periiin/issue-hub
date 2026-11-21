<template>
  <div class="share-page">
    <div v-if="error" class="ih-card err-card">
      <div class="err-icon">🔗</div>
      <h2>链接无效或已过期</h2>
      <p>这个分享链接可能已被撤销、过期或输入有误。<br />请联系反馈方重新获取。</p>
    </div>

    <template v-else-if="data">
      <div class="share-head">
        <div class="brand">
          <div class="logo"><span class="logo-dot" /></div>
          <div class="brand-text">
            <span class="brand-name">Issue Hub</span>
            <span class="brand-sub">问题进度（只读）</span>
          </div>
        </div>
      </div>

      <div class="ih-card hero">
        <div class="hero-eyebrow">
          <span class="ih-mono">#{{ data.issue.id }}</span>
          <span class="status"><i :class="['dot', dotClass(data.issue.status)]" />{{ data.issue.status }}</span>
        </div>
        <h1>{{ data.issue.title }}</h1>
        <div class="hero-meta">
          <span v-if="data.issue.module">模块 {{ data.issue.module }}</span>
          <span v-if="data.issue.reporter">提出人 {{ data.issue.reporter }}</span>
          <span>创建 {{ fmtTime(data.issue.createdAt) }}</span>
          <span>最近更新 {{ fmtTime(data.issue.updatedAt) }}</span>
        </div>
        <div class="badges">
          <span :class="priorityClass(data.issue.priority)">{{ data.issue.priority || '未定级' }}</span>
          <span v-if="data.issue.severity" class="badge">{{ data.issue.severity }}</span>
          <span v-if="data.issue.complexity" class="badge">{{ data.issue.complexity }}</span>
        </div>
      </div>

      <div v-if="data.issue.phenomenon" class="ih-card sec">
        <h3>问题描述</h3>
        <p class="pre">{{ data.issue.phenomenon }}</p>
        <template v-if="data.issue.reproSteps.length">
          <h4>复现步骤</h4>
          <ol class="steps"><li v-for="(s, i) in data.issue.reproSteps" :key="i">{{ s }}</li></ol>
        </template>
        <p v-if="data.issue.expected" class="kv"><b>期望</b>：{{ data.issue.expected }}</p>
        <p v-if="data.issue.actual" class="kv"><b>实际</b>：{{ data.issue.actual }}</p>
      </div>

      <div v-if="data.issue.rawText" class="ih-card sec">
        <h3>原始反馈</h3>
        <p class="pre">{{ data.issue.rawText }}</p>
      </div>

      <div class="ih-card sec">
        <h3>处理进度</h3>
        <el-timeline class="timeline">
          <el-timeline-item
            v-for="(e, i) in data.events" :key="i" :timestamp="fmtTime(e.created_at)"
            placement="top"
            :color="e.type === 'status' ? '#7c3aed' : e.type === 'create' ? '#12b76a' : '#c7cbe0'"
          >
            <div class="ev">
              <span class="ev-type">{{ eventLabel(e.type) }}</span>
              <span v-if="e.from_status || e.to_status" class="ih-muted">
                {{ e.from_status || '-' }} → {{ e.to_status || '-' }}
              </span>
              <span v-if="e.note" class="ev-note">{{ e.note }}</span>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>

      <div v-if="data.attachments.length" class="ih-card sec">
        <h3>附件（{{ data.attachments.length }}）</h3>
        <div class="atts">
          <div v-for="a in data.attachments" :key="a.id" class="att">
            <template v-if="isImage(a)">
              <img :src="`/files/${data.issue.id}/${attName(a)}`" :alt="a.filename" loading="lazy" @click="preview = `/files/${data.issue.id}/${attName(a)}`" />
            </template>
            <a v-else :href="`/files/${data.issue.id}/${attName(a)}`" target="_blank">📄 {{ a.filename }}</a>
          </div>
        </div>
      </div>

      <p class="foot">此页面为只读视图 · 更新后会自动反映最新状态</p>
    </template>

    <el-skeleton v-else :rows="6" animated class="loading" />

    <el-image-viewer
      v-if="preview" :url-list="[preview]" @close="preview = ''"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const data = ref<any>(null)
const error = ref(false)
const preview = ref('')

/** 分享页不登录，直接裸 axios（带 token 也没用，接口本来就是公开的） */
const load = async () => {
  try {
    const r = await axios.get(`/api/share/${route.params.token}`)
    data.value = r.data
  } catch {
    error.value = true
  }
}

const isImage = (a: any) => (a.mime || '').startsWith('image/')
const attName = (a: any) => (a.filename || '').split('/').pop() || a.filename
const fmtTime = (t: string) => (t || '').slice(0, 16)

const dotClass = (s: string) => {
  const map: Record<string, string> = {
    '待定性': 'dot--draft', '待定级': 'dot--triage', '待处理': 'dot--todo',
    '处理中': 'dot--doing', '待验收': 'dot--accept', '已解决': 'dot--done',
  }
  return map[s] || 'dot--drop'
}
const priorityClass = (p: string | null) =>
  `pill ${p === 'P0' ? 'pill--p0' : p === 'P1' ? 'pill--p1' : p === 'P2' ? 'pill--p2' : p ? 'pill--p3' : 'pill--none'}`
const eventLabel = (t: string) => {
  const map: Record<string, string> = {
    create: '新建', qualify: 'AI 定性', confirm: '人工确认', triage: 'AI 定级',
    fix: '生成方案', fix_apply: '开始修改', fix_accept: '采纳', fix_reject: '驳回',
    status: '状态变更', note: '备注', link: '关联',
  }
  return map[t] || t
}

onMounted(load)
</script>

<style scoped>
.share-page {
  min-height: 100vh; padding: 20px 16px calc(40px + env(safe-area-inset-bottom));
  background:
    radial-gradient(900px 400px at 50% -10%, var(--ih-hero-glow-a), transparent 70%),
    var(--ih-bg);
  max-width: 760px; margin: 0 auto;
}
.share-head { margin-bottom: 16px; }
.brand { display: flex; align-items: center; gap: 10px; }
.logo {
  width: 32px; height: 32px; border-radius: 10px;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  display: flex; align-items: center; justify-content: center;
}
.logo-dot { width: 10px; height: 10px; border-radius: 50%; background: #fff; opacity: 0.92; }
.brand-text { display: flex; flex-direction: column; line-height: 1.15; }
.brand-name { font-size: 16px; font-weight: 700; color: var(--ih-ink); }
.brand-sub { font-size: 11px; color: var(--ih-sub); }

.hero { padding: 18px 20px; margin-bottom: 12px; }
.hero-eyebrow { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--ih-sub); }
.hero h1 { margin: 8px 0 0; font-size: 22px; font-weight: 750; line-height: 1.3; color: var(--ih-ink); }
.hero-meta { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 8px; font-size: 12px; color: var(--ih-sub); }
.badges { display: flex; gap: 8px; margin-top: 12px; }

.sec { padding: 16px 20px; margin-bottom: 12px; }
.sec h3 { margin: 0 0 10px; font-size: 15px; color: var(--ih-ink); }
.sec h4 { margin: 14px 0 6px; font-size: 13px; color: var(--ih-sub); }
.pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 13.5px; line-height: 1.7; color: var(--ih-ink); }
.kv { font-size: 13px; color: var(--ih-ink); margin: 8px 0 0; }
.kv b { color: var(--ih-sub); font-weight: 600; }
.steps { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.8; color: var(--ih-ink); }

.timeline { padding-left: 4px; }
.ev { display: flex; gap: 8px; flex-wrap: wrap; font-size: 12.5px; align-items: center; }
.ev-type { font-weight: 600; color: var(--ih-ink); }
.ev-note { color: var(--ih-sub); }

.atts { display: flex; gap: 10px; flex-wrap: wrap; }
.att img { max-width: 220px; max-height: 160px; border-radius: 10px; cursor: zoom-in; border: 1px solid var(--ih-line); }
.att a { font-size: 12.5px; color: var(--ih-primary); }

.foot { text-align: center; font-size: 11.5px; color: var(--ih-sub); margin-top: 18px; }
.loading { margin-top: 40px; }
.err-card { text-align: center; padding: 40px 24px; }
.err-icon { font-size: 34px; }
.err-card h2 { margin: 12px 0 8px; font-size: 17px; color: var(--ih-ink); }
.err-card p { color: var(--ih-sub); font-size: 13px; line-height: 1.7; }

.status { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ih-ink); }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.dot--draft { background: #98a2b3; } .dot--triage { background: #f79009; }
.dot--todo { background: #2e90fa; } .dot--doing { background: #7c3aed; }
.dot--accept { background: #f79009; } .dot--done { background: #12b76a; }
.dot--drop { background: #98a2b3; }
.pill { font-size: 11px; padding: 2px 9px; border-radius: 999px; font-weight: 600; }
.pill--p0 { background: rgba(240, 68, 56, 0.12); color: #f04438; }
.pill--p1 { background: rgba(247, 144, 9, 0.14); color: #f79009; }
.pill--p2 { background: rgba(46, 144, 250, 0.12); color: #2e90fa; }
.pill--p3 { background: var(--ih-chip); color: var(--ih-sub); }
.pill--none { background: var(--ih-chip); color: var(--ih-sub); }
.badge { font-size: 11px; padding: 2px 9px; border-radius: 999px; background: var(--ih-chip); color: var(--ih-sub); }

@media (max-width: 600px) {
  .share-page { padding: 14px 12px calc(30px + env(safe-area-inset-bottom)); }
  .hero h1 { font-size: 18px; }
  .att img { max-width: 100%; max-height: 200px; }
}
</style>
