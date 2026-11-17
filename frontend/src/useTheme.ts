import { computed, ref, watchEffect } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'ih-theme'

/** 模块级单例：任意组件 import 都拿到同一份状态 */
const stored = (localStorage.getItem(STORAGE_KEY) as ThemeMode | null) || 'system'
const mode = ref<ThemeMode>(stored)
const media = window.matchMedia('(prefers-color-scheme: dark)')
const systemDark = ref(media.matches)
media.addEventListener('change', (e) => (systemDark.value = e.matches))

const isDark = computed(() => mode.value === 'dark' || (mode.value === 'system' && systemDark.value))

// <html class="dark"> 是 Element Plus 暗色主题的开关，同时也是我们自定义变量的作用域
watchEffect(() => {
  document.documentElement.classList.toggle('dark', isDark.value)
  document.documentElement.style.colorScheme = isDark.value ? 'dark' : 'light'
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', isDark.value ? '#0f1117' : '#ffffff')
})

export const useTheme = () => ({
  mode,
  isDark,
  setMode(next: ThemeMode) {
    mode.value = next
    localStorage.setItem(STORAGE_KEY, next)
  },
  toggle() {
    const next: ThemeMode = isDark.value ? 'light' : 'dark'
    mode.value = next
    localStorage.setItem(STORAGE_KEY, next)
  }
})
