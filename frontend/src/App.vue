<template>
  <!-- 登录页这类独立页面不套壳：没有顶栏和底部导航 -->
  <router-view v-if="$route.meta?.bare" />
  <div v-else class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand" @click="$router.push('/issues')">
          <div class="logo">
            <span class="logo-dot" />
          </div>
          <div class="brand-text">
            <span class="brand-name">Issue Hub</span>
            <span class="brand-sub">甲方问题跟踪</span>
          </div>
        </div>

        <nav v-if="!isMobile" class="nav">
          <router-link to="/issues" class="nav-link" active-class="is-on">问题列表</router-link>
          <router-link to="/settings" class="nav-link" active-class="is-on">设置</router-link>
        </nav>

        <div class="topbar-right">
          <button class="theme-btn" :title="isDark ? '切换到浅色' : '切换到深色'" @click="toggleTheme">
            <!-- 浅色时显示月亮（点了变深色），深色时显示太阳 -->
            <svg v-if="!isDark" viewBox="0 0 24 24" width="18" height="18" fill="none"
                 stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none"
                 stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <circle cx="12" cy="12" r="4.2" />
              <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4" />
            </svg>
          </button>
          <el-button v-if="!isMobile" type="primary" round @click="goCreate">＋ 新建问题</el-button>
        </div>
      </div>
    </header>

    <main class="content">
      <router-view />
    </main>

    <!-- 手机端底部导航 -->
    <nav v-if="isMobile" class="tabbar">
      <router-link to="/issues" class="tab" active-class="is-on">
        <span class="tab-icon">☰</span>
        <span class="tab-text">列表</span>
      </router-link>
      <button class="tab tab--main" @click="goCreate">
        <span class="tab-plus">＋</span>
        <span class="tab-text">新建</span>
      </button>
      <router-link to="/settings" class="tab" active-class="is-on">
        <span class="tab-icon">⚙</span>
        <span class="tab-text">设置</span>
      </router-link>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useMobile } from './useMobile'
import { useTheme } from './useTheme'

const router = useRouter()
const isMobile = useMobile()
const { isDark, toggle: toggleTheme } = useTheme()

/** 新建入口统一走列表页的弹窗（?new=1 由列表页消费） */
const goCreate = () => router.push({ path: '/issues', query: { new: '1' } })
</script>

<style scoped>
.shell { min-height: 100vh; padding-bottom: calc(64px + env(safe-area-inset-bottom)); }
@media (min-width: 769px) { .shell { padding-bottom: 0; } }

.topbar {
  position: sticky; top: 0; z-index: 20;
  background: var(--ih-topbar);
  backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--ih-line);
  transition: background-color 0.2s ease, border-color 0.2s ease;
}
.topbar-inner {
  max-width: 1120px; margin: 0 auto; padding: 0 20px;
  height: 60px; display: flex; align-items: center; gap: 20px;
}
.brand { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.logo {
  width: 32px; height: 32px; border-radius: 10px;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 14px rgba(79, 70, 229, 0.28);
}
.logo-dot { width: 10px; height: 10px; border-radius: 50%; background: #fff; opacity: 0.92; }
.brand-text { display: flex; flex-direction: column; line-height: 1.15; }
.brand-name { font-size: 16px; font-weight: 700; letter-spacing: 0.2px; color: var(--ih-ink); }
.brand-sub { font-size: 11px; color: var(--ih-sub); }

.nav { display: flex; gap: 6px; margin-left: 8px; }
.nav-link {
  padding: 7px 14px; border-radius: 999px; font-size: 14px;
  color: var(--ih-sub); text-decoration: none; transition: all 0.16s ease;
}
.nav-link:hover { background: var(--ih-soft); color: var(--ih-ink); }
.nav-link.is-on {
  background: var(--ih-primary-soft); color: var(--ih-primary); font-weight: 600;
}

.topbar-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }

/* 主题切换按钮 */
.theme-btn {
  width: 36px; height: 36px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--ih-line); background: var(--ih-card);
  color: var(--ih-sub); cursor: pointer; transition: all 0.16s ease;
}
.theme-btn:hover { color: var(--ih-primary); border-color: var(--ih-primary); transform: rotate(8deg); }
.theme-btn:active { transform: scale(0.94); }

.content { max-width: 1400px; margin: 0 auto; padding: 20px; }
/* 列表页内容比详情页窄，单独收一下，避免表格被拉得过长 */
.content:has(.list-page) { max-width: 1180px; }

/* ---------- 手机底部导航 ---------- */
.tabbar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
  display: flex; align-items: stretch;
  padding-bottom: env(safe-area-inset-bottom);
  background: var(--ih-tabbar);
  backdrop-filter: saturate(180%) blur(12px);
  border-top: 1px solid var(--ih-line);
  transition: background-color 0.2s ease, border-color 0.2s ease;
}
.tab {
  flex: 1; height: 56px; border: none; background: transparent;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; color: var(--ih-sub); text-decoration: none; font-size: 11px;
  -webkit-appearance: none;
}
.tab.is-on { color: var(--ih-primary); }
.tab-icon { font-size: 18px; line-height: 1; }
.tab-text { font-size: 11px; }
.tab--main { position: relative; top: -12px; flex: 0 0 72px; }
.tab-plus {
  width: 48px; height: 48px; border-radius: 50%;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
  color: #fff; font-size: 26px; line-height: 46px; text-align: center;
  box-shadow: 0 10px 22px rgba(79, 70, 229, 0.35);
}
.tab--main .tab-text { color: var(--ih-primary); font-weight: 600; margin-top: 2px; }

@media (max-width: 768px) {
  .topbar-inner { height: 52px; padding: 0 14px; gap: 10px; }
  .content { padding: 14px 12px 20px; }
}
</style>
