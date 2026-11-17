<template>
  <div class="mermaid-box">
    <div v-if="error" class="mermaid-error">
      <div class="mermaid-error-head">流程图渲染失败</div>
      <pre class="mermaid-error-detail">{{ error }}</pre>
      <el-button size="small" round @click="showSource = !showSource">
        {{ showSource ? '收起源码' : '查看源码' }}
      </el-button>
      <pre v-if="showSource" class="mermaid-source">{{ code }}</pre>
    </div>
    <div v-else ref="host" v-loading="loading" class="mermaid-host" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ code: string; dark?: boolean }>()

const host = ref<HTMLElement | null>(null)
const error = ref('')
const loading = ref(false)
const showSource = ref(false)

/**
 * mermaid 体积较大，按需动态 import：只有真正展开折叠面板时才加载，
 * 不影响列表页和其它页面的首屏。
 */
let mermaidApi: any = null
let renderSeq = 0

const loadMermaid = async () => {
  if (mermaidApi) return mermaidApi
  const mod: any = await import('mermaid')
  mermaidApi = mod.default || mod
  return mermaidApi
}

/** 把 computed fill（rgb/rgba/#hex）解析成 [r,g,b]，解析不了返回 null */
const parseRgb = (value: string): [number, number, number] | null => {
  if (!value) return null
  const v = value.trim()
  if (v.startsWith('#')) {
    const hex = v.slice(1)
    const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex
    if (full.length < 6) return null
    return [parseInt(full.slice(0, 2), 16), parseInt(full.slice(2, 4), 16), parseInt(full.slice(4, 6), 16)]
  }
  const m = v.match(/rgba?\(([^)]+)\)/)
  if (!m) return null
  const parts = m[1].split(',').map((s) => parseFloat(s.trim()))
  if (parts.length < 3 || parts.some((n) => Number.isNaN(n))) return null
  return [parts[0], parts[1], parts[2]]
}

/**
 * AI 生成的流程图常带硬编码的浅色 style（如 fill:#ffe0e0）。
 * 暗色主题下文字会变白，与浅底撞色导致看不清。
 * 这里按节点实际背景亮度反向决定文字颜色，保证两种主题都清晰。
 */
const applyContrastFix = () => {
  if (!host.value) return
  host.value.querySelectorAll('g.node').forEach((node) => {
    const shape = node.querySelector('rect, polygon, circle, ellipse, path')
    if (!shape) return
    const rgb = parseRgb(getComputedStyle(shape).fill)
    if (!rgb) return
    // 相对亮度：0 黑 ~ 1 白
    const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255
    const ink = lum > 0.55 ? '#101828' : '#ffffff'
    node.querySelectorAll('foreignObject, foreignObject div, foreignObject span, text, tspan, .label')
      .forEach((el) => {
        const node2 = el as HTMLElement
        node2.style.color = ink
        node2.style.fill = ink
      })
  })
}

const render = async () => {
  const code = (props.code || '').trim()
  if (!code || !host.value) return
  const seq = ++renderSeq
  loading.value = true
  error.value = ''
  try {
    const mermaid = await loadMermaid()
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: props.dark ? 'dark' : 'base',
      flowchart: { curve: 'basis', padding: 12, nodeSpacing: 34, rankSpacing: 40, useMaxWidth: true },
      themeVariables: {
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif',
        fontSize: '13px',
      },
    })
    // 每次渲染用唯一 id，避免同一页面多条流程图互相覆盖
    const { svg } = await mermaid.render(`ih-mmd-${seq}`, code)
    // 异步返回时组件可能已卸载，或已被更新的渲染取代
    if (seq !== renderSeq || !host.value) return
    host.value.innerHTML = svg
    applyContrastFix()
  } catch (e: any) {
    if (seq !== renderSeq) return
    error.value = String(e?.message || e).slice(0, 500)
  } finally {
    if (seq === renderSeq) loading.value = false
  }
}

watch(
  () => [props.code, props.dark],
  async () => {
    await nextTick()
    render()
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  // 让进行中的渲染结果作废，防止卸载后写 DOM
  renderSeq++
})
</script>

<style scoped>
.mermaid-box { width: 100%; }
.mermaid-host {
  overflow-x: auto;
  padding: 4px 0;
  text-align: center;
}
.mermaid-host :deep(svg) { max-width: 100%; height: auto; }
.mermaid-error {
  border: 1px solid var(--ih-line);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--ih-soft);
}
.mermaid-error-head { color: #b42318; font-weight: 600; margin-bottom: 8px; font-size: 13px; }
.mermaid-error-detail {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--ih-sub);
  white-space: pre-wrap;
  word-break: break-word;
}
.mermaid-source {
  margin: 10px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--ih-card);
  border: 1px solid var(--ih-line);
  font-size: 12px;
  overflow-x: auto;
  white-space: pre;
}
</style>
