import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 暗色变量（html.dark 生效）
import 'element-plus/theme-chalk/dark/css-vars.css'
// 全局设计令牌要放在 Element Plus 样式之后，才能覆盖它的主题变量
import './styles.css'
// 引入即应用主题（内部 watchEffect 会同步 html.dark）
import './useTheme'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import IssueList from './views/IssueList.vue'
import IssueDetail from './views/IssueDetail.vue'
import Settings from './views/Settings.vue'
import Login from './views/Login.vue'
import ShareView from './views/ShareView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/issues' },
    { path: '/login', component: Login, meta: { bare: true } },
    // 甲方只读分享页：不带顶栏/tabbar
    { path: '/share/:token', component: ShareView, meta: { bare: true } },
    { path: '/issues', component: IssueList },
    { path: '/issues/:id', component: IssueDetail, props: true },
    { path: '/settings', component: Settings }
  ]
})

createApp(App)
  .use(ElementPlus, { locale: zhCn })
  .use(router)
  .mount('#app')
