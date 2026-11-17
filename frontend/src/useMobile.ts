import { onMounted, onUnmounted, ref } from 'vue'

/** 响应式断点：768px 以下按手机布局渲染（列表换卡片、对话框全屏等）。 */
export const useMobile = (breakpoint = 768) => {
  const isMobile = ref(false)
  let mql: MediaQueryList | null = null
  const update = (e: MediaQueryList | MediaQueryListEvent) => (isMobile.value = e.matches)

  onMounted(() => {
    mql = window.matchMedia(`(max-width: ${breakpoint}px)`)
    update(mql)
    mql.addEventListener('change', update)
  })
  onUnmounted(() => mql?.removeEventListener('change', update))
  return isMobile
}
