<template>
  <div class="settings">
    <div class="page-head">
      <div>
        <h1 class="page-title">设置</h1>
        <p class="page-sub">选择 AI 执行器、填 API Key、配置代码仓库路径</p>
      </div>
      <el-button type="primary" round :loading="saving" @click="save">保存配置</el-button>
    </div>

    <!-- 安全与限流 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">🔒</span>
          <div>
            <h2>安全与限流</h2>
            <p>防密码爆破与接口滥用；被锁的账号可在这里手工解锁</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button round :loading="rateLoading" @click="loadRate">刷新</el-button>
        </div>
      </div>

      <div v-if="rate" class="rate-grid">
        <div class="rate-cell">
          <span class="rate-label">登录尝试</span>
          <span class="rate-value">{{ rate.loginPerIpPerMin }} 次 / 分钟 / IP</span>
        </div>
        <div class="rate-cell">
          <span class="rate-label">失败锁定</span>
          <span class="rate-value">{{ rate.failLimit }} 次 → 锁 {{ rate.failLockMinutes }} 分钟</span>
        </div>
        <div class="rate-cell">
          <span class="rate-label">普通请求</span>
          <span class="rate-value">{{ rate.apiPerMin }} 次 / 分钟</span>
        </div>
        <div class="rate-cell">
          <span class="rate-label">重操作</span>
          <span class="rate-value">{{ rate.heavyPerHour }} 次 / 小时</span>
        </div>
      </div>

      <div class="rate-locks">
        <div class="rate-locks-head">
          <span class="field-label">当前锁定</span>
          <span class="ih-muted">{{ activeLocks.length }} 个生效中</span>
          <el-button
            v-if="activeLocks.length" link type="danger" class="field-head-btn"
            @click="doClearRate"
          >全部清空</el-button>
        </div>
        <div v-if="!activeLocks.length" class="ih-muted rate-empty">
          没有账号被锁定。
        </div>
        <div v-for="l in activeLocks" :key="l.lock_key" class="rate-lock-row">
          <code class="rate-lock-key">{{ l.lock_key }}</code>
          <span class="ih-muted">{{ l.reason }}</span>
          <span class="rate-lock-remain">剩余 {{ Math.ceil(l.remainSeconds / 60) }} 分钟</span>
          <el-button link type="primary" size="small" @click="doUnlock(l.lock_key)">解锁</el-button>
        </div>
      </div>

      <div class="ih-muted rate-hint">
        阈值可在服务端配置项调整（rate.login_per_ip / rate.fail_limit / rate.api_per_min / rate.heavy_per_hour）。
        重操作指改代码、定性、定级、拉模型等会消耗额度的接口。
      </div>
    </section>

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

      <!-- 已有项目：紧凑列表，点行展开看完整路径与说明 -->
      <div class="proj-toolbar">
        <span class="field-label">已有项目</span>
        <span class="ih-muted">{{ projects.length }} 个 · 点名称展开详情</span>
        <el-input
          v-model="projFilter" size="small" clearable placeholder="筛选项目"
          class="proj-filter"
        >
          <template #prefix><span class="proj-filter-icon">⌕</span></template>
        </el-input>
      </div>

      <div class="proj-list">
        <div
          v-for="p in filteredProjects" :key="p.id"
          class="proj-row" :class="{ 'is-ignored': p.ignored, 'is-open': openProjIds.includes(p.id) }"
        >
          <!-- 折叠态：一行 -->
          <div class="proj-row-main" @click="toggleProjOpen(p.id)">
            <span class="proj-caret" />
            <div class="proj-row-name">
              <el-input
                v-if="editingId === p.id" v-model="editName" size="small" class="proj-name-input"
                @keyup.enter="saveName(p)" @blur="saveName(p)" @click.stop
              />
              <b v-else class="proj-name" @click.stop="startEdit(p)">{{ p.name }}</b>
              <span class="proj-count">{{ p.repos.length }}</span>
              <span v-if="p.ignored" class="proj-tag">已忽略</span>
            </div>
            <div class="proj-row-repos">
              <code v-for="r in p.repos.slice(0, 4)" :key="r" class="proj-repo-chip">{{ repoName(r) }}</code>
              <span v-if="p.repos.length > 4" class="proj-repo-more">+{{ p.repos.length - 4 }}</span>
            </div>
            <div class="proj-row-actions" @click.stop>
              <el-button size="small" round @click="toggleIgnore(p)">
                {{ p.ignored ? '恢复' : '忽略' }}
              </el-button>
              <el-button size="small" round type="danger" plain @click="removeProject(p)">删除</el-button>
            </div>
          </div>

          <!-- 展开态：完整路径 + 说明 -->
          <div v-if="openProjIds.includes(p.id)" class="proj-row-detail">
            <div class="proj-detail-block">
              <span class="proj-detail-label">仓库路径</span>
              <div class="proj-detail-paths">
                <code v-for="r in p.repos" :key="r">{{ r }}</code>
              </div>
            </div>
            <div class="proj-detail-block">
              <span class="proj-detail-label">给 AI 的说明</span>
              <el-input
                v-model="p._notes" size="small"
                placeholder="可选，如：后端 Spring Boot，前端 Vue3；会拼进提示词"
                @blur="saveNotes(p)"
              />
            </div>
            <div class="proj-detail-block">
              <span class="proj-detail-label">采纳前的验证命令</span>
              <el-input
                v-model="p._verifyCmd" size="small"
                placeholder="留空则自动推断，如 mvn -q -DskipTests compile / npm run type-check"
                @blur="saveVerifyCmd(p)"
              />
              <span class="field-hint">
                在 worktree 里跑，失败会阻止采纳。留空时按仓库特征自动选（pom.xml → Maven，package.json → npm 脚本）
              </span>
            </div>
          </div>
        </div>
        <div v-if="!filteredProjects.length" class="ih-muted proj-empty">
          {{ projects.length ? '没有匹配的项目' : '还没有项目。填好扫描根后点「扫描仓库」。' }}
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
          <el-button round :loading="magpieLoading" @click="openMagpie">从本地 Magpie 导入</el-button>
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

    <!-- 新问题通知（Webhook） -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">🔔</span>
          <div>
            <h2>新问题通知</h2>
            <p>有新问题或新讨论时，推一条消息到群机器人；不发通知可随时关</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button round :loading="notifyTesting" @click="doTestNotify">发送测试</el-button>
        </div>
      </div>

      <div class="notify-grid">
        <label class="notify-switch">
          <el-switch v-model="form['notify.enabled']" active-value="1" inactive-value="0" />
          <span>启用通知</span>
        </label>
        <label class="field">
          <span class="field-label">机器人类型</span>
          <el-select v-model="form['notify.webhook_kind']" class="w-140">
            <el-option label="企业微信群机器人" value="wecom" />
            <el-option label="飞书自定义机器人" value="feishu" />
            <el-option label="钉钉自定义机器人" value="dingtalk" />
          </el-select>
        </label>
        <label class="field field--wide">
          <span class="field-label">Webhook 地址</span>
          <el-input
            v-model="form['notify.webhook_url']"
            placeholder="群机器人 Webhook 完整地址（含 key 参数）"
          />
        </label>
        <label class="field field--wide">
          <span class="field-label">对外访问地址（通知里拼详情页链接用）</span>
          <el-input
            v-model="form['notify.base_url']"
            placeholder="如 http://192.168.110.12:8090，不填则群消息不带链接"
          />
        </label>
      </div>
      <p class="field-hint">
        通知在新问题、新讨论时发出；启用前点「发送测试」确认机器人能收到。
        发送失败不影响任何主流程，只是群里少一条消息。
      </p>
    </section>

    <!-- 账号：用户管理 + 登录记录（拆成独立组件，这里已经很长了） -->
    <AccountPanel v-if="me?.role === 'admin'" />



    <!-- 从本地 Magpie 导入 -->
    <el-drawer
      v-model="magpieDrawer" title="从本地 Magpie 导入"
      :size="isMobile ? '100%' : '620px'" append-to-body
    >
      <div v-if="magpieError" class="magpie-error">
        <b>没能连上 Magpie</b>
        <p>{{ magpieError }}</p>
        <el-button size="small" round @click="loadMagpie">重试</el-button>
      </div>

      <template v-else-if="magpie">
        <div class="magpie-head">
          <div class="magpie-meta">
            <span class="magpie-ok">已连接</span>
            <code>{{ magpie.baseUrl }}</code>
            <span v-if="magpie.version" class="ih-muted">v{{ magpie.version }}</span>
          </div>
          <p class="field-hint">
            选中要用的模型，会各建一条通道。Magpie 是本机网关、不校验 Key，
            导入后不用填任何凭证。
          </p>
        </div>

        <div class="magpie-toolbar">
          <el-checkbox
            :model-value="magpiePick.length === magpie.models.length && magpie.models.length > 0"
            :indeterminate="magpiePick.length > 0 && magpiePick.length < magpie.models.length"
            @change="toggleAllMagpie"
          >全选</el-checkbox>
          <span class="ih-muted">已选 {{ magpiePick.length }} / {{ magpie.models.length }}</span>
        </div>

        <div class="magpie-list">
          <label v-for="m in magpie.models" :key="m.id" class="magpie-item">
            <el-checkbox :model-value="magpiePick.includes(m.id)" @change="toggleMagpie(m.id)" />
            <div class="magpie-item-main">
              <div class="magpie-item-name">{{ m.label }}</div>
              <div class="magpie-item-id">{{ m.id }}</div>
            </div>
            <div class="magpie-badges">
              <span v-if="m.tools" class="mbadge mbadge--ok" title="支持 function calling，能用来改代码">改代码</span>
              <span v-if="m.vision" class="mbadge" title="能看图">看图</span>
              <span v-if="m.contextLength" class="mbadge mbadge--ghost">{{ Math.round(m.contextLength / 1000) }}k</span>
            </div>
          </label>
        </div>
      </template>

      <el-skeleton v-else :rows="5" animated />

      <template #footer>
        <el-button @click="magpieDrawer = false">取消</el-button>
        <el-button
          type="primary" :loading="magpieImporting"
          :disabled="!magpiePick.length" @click="doMagpieImport"
        >导入 {{ magpiePick.length }} 个</el-button>
      </template>
    </el-drawer>

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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  changePassword, clearRate, createChannel, createProject,
  deleteChannel, deleteProject, detectMagpie, getChannels, getMe, getProjects, getRateStatus,
  getSettings, importMagpieModels, listChannelModels, mergeProjects, saveSettings,
  scanRepos, testNotify, testChannel, unlockRate, updateChannel, updateProject,
  type AuthUser, type Channel, type MagpieDetect, type Project, type ScanResult
} from '../api'
import AccountPanel from './AccountPanel.vue'
import { useTheme } from '../useTheme'
import { useMobile } from '../useMobile'

const { mode, setMode } = useTheme()
const isMobile = useMobile()
const form = reactive<Record<string, any>>({})
const rubricVersion = ref('')
const saving = ref(false)
/** 当前用户：只用来判断「账号」区块要不要渲染 */
const me = ref<AuthUser | null>(null)

/* ===== 安全与限流 ===== */
const rate = ref<any>(null)
const rateLoading = ref(false)

const activeLocks = computed(() =>
  ((rate.value?.locks || []) as any[]).filter((l) => l.active)
)

/* ---------- 从本地 Magpie 导入 ---------- */
const magpieDrawer = ref(false)
const magpieLoading = ref(false)
const magpieImporting = ref(false)
const magpie = ref<MagpieDetect | null>(null)
const magpieError = ref('')
const magpiePick = ref<string[]>([])

const loadMagpie = async () => {
  magpieLoading.value = true
  magpieError.value = ''
  try {
    const d = await detectMagpie()
    if (!d.running) {
      magpieError.value = d.error || 'Magpie 没有运行'
      magpie.value = null
    } else {
      magpie.value = d
      // 默认只选「能改代码」的，避免一上来全选一堆用不上的
      magpiePick.value = d.models.filter((m) => m.tools).map((m) => m.id)
    }
  } catch (e: any) {
    magpieError.value = e?.response?.data?.detail || e?.message || '探测失败'
    magpie.value = null
  } finally {
    magpieLoading.value = false
  }
}

const openMagpie = async () => {
  magpieDrawer.value = true
  await loadMagpie()
}

const toggleMagpie = (id: string) => {
  magpiePick.value = magpiePick.value.includes(id)
    ? magpiePick.value.filter((x) => x !== id)
    : [...magpiePick.value, id]
}

const toggleAllMagpie = (checked: any) => {
  magpiePick.value = checked && magpie.value
    ? magpie.value.models.map((m) => m.id)
    : []
}

const doMagpieImport = async () => {
  magpieImporting.value = true
  try {
    const r = await importMagpieModels(magpiePick.value)
    const skipped = r.skipped?.length || 0
    ElMessage.success(
      `已导入 ${r.created.length} 个` + (skipped ? `，${skipped} 个之前导过已跳过` : '')
    )
    magpieDrawer.value = false
    await loadChannels()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '导入失败')
  } finally {
    magpieImporting.value = false
  }
}

const notifyTesting = ref(false)

const doTestNotify = async () => {
  // 先保存当前填的配置再测，否则测的是旧值
  await save(true)
  notifyTesting.value = true
  try {
    const r = await testNotify()
    if (r.ok) ElMessage.success('已发出，去群里看看')
    else ElMessage.error(r.error || '发送失败')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '发送失败')
  } finally {
    notifyTesting.value = false
  }
}

const loadRate = async () => {
  rateLoading.value = true
  try {
    rate.value = await getRateStatus()
  } catch {
    rate.value = null
  } finally {
    rateLoading.value = false
  }
}

const doUnlock = async (key: string) => {
  await unlockRate(key)
  await loadRate()
  ElMessage.success('已解锁')
}

const doClearRate = async () => {
  await ElMessageBox.confirm('清空所有限流计数与锁定？', '提示', { type: 'warning' })
  await clearRate()
  await loadRate()
  ElMessage.success('已清空')
}

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
/** 展开的项目 id：默认全收起，只有点开才显示完整路径与说明 */
const openProjIds = ref<number[]>([])
const projFilter = ref('')

const toggleProjOpen = (id: number) => {
  openProjIds.value = openProjIds.value.includes(id)
    ? openProjIds.value.filter((x) => x !== id)
    : [...openProjIds.value, id]
}

/** 折叠态只显示仓库目录名，完整路径在展开后看 */
const repoName = (path: string) => path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path

const filteredProjects = computed(() => {
  const kw = projFilter.value.trim().toLowerCase()
  if (!kw) return projects.value
  return projects.value.filter(
    (p) => p.name.toLowerCase().includes(kw)
      || p.repos.some((r) => r.toLowerCase().includes(kw))
  )
})

const loadProjects = async () => {
  const r = await getProjects().catch(() => null)
  if (r) {
    projects.value = (r.projects || []).map((p) => ({
      ...p, _notes: p.notes || '', _verifyCmd: p.verify_cmd || ''
    }))
  }
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

const saveVerifyCmd = async (p: Project & { _verifyCmd?: string }) => {
  if ((p._verifyCmd || '') === (p.verify_cmd || '')) return
  await updateProject(p.id, { verify_cmd: p._verifyCmd || '' } as any)
  p.verify_cmd = p._verifyCmd
  ElMessage.success('已保存')
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
  await loadRate()
  // 当前用户：决定「账号」区块是否渲染（数据由 AccountPanel 自己拉）
  const m = await getMe().catch(() => null)
  me.value = m?.user || null
})
</script>

<style scoped>

/* ===== 通知区块 ===== */
.notify-grid { display: grid; grid-template-columns: auto 200px 1fr; gap: 14px; align-items: end; }
.notify-switch { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ih-ink); padding-bottom: 8px; }
/* URL 单独占满一整行，太长会被压 */
.notify-grid .field--wide { grid-column: 1 / -1; }

/* ===== AI 通道卡片 ===== */
.ch-list { display: flex; flex-direction: column; gap: 8px; }
.ch-card {
  padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--ih-line); background: var(--ih-surface);
}
.ch-card.is-default { border-color: var(--ih-primary); }
.ch-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 10px; flex-wrap: wrap;
}
.ch-title { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; }
.ch-title b { font-size: 13.5px; color: var(--ih-ink); }
.ch-kind {
  font-size: 10px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-chip); color: var(--ih-sub);
}
.ch-kind.is-api { background: var(--ih-primary-soft); color: var(--ih-primary); }
.ch-kind.is-agent { background: rgba(247, 144, 9, 0.14); color: #f79009; }
.ch-tag {
  font-size: 10px; padding: 1px 7px; border-radius: 999px;
  background: rgba(18, 183, 106, 0.12); color: #12b76a;
}
.ch-actions { display: flex; gap: 6px; flex: 0 0 auto; }
.ch-meta {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-top: 6px; font-size: 11.5px; color: var(--ih-sub);
}
.ch-meta code { font-size: 11.5px; color: var(--ih-ink); word-break: break-all; }
.ch-model { color: var(--ih-ink); }
.ch-key { color: #f04438; }
.ch-key.is-ok { color: #12b76a; }
.ch-empty { padding: 16px 12px; }
.ch-globals { margin-top: 14px; }

/* ===== 从 Magpie 导入 ===== */
.magpie-error {
  padding: 16px; border-radius: 12px;
  border: 1px solid rgba(240, 68, 56, 0.3); background: rgba(240, 68, 56, 0.06);
}
.magpie-error b { font-size: 13.5px; color: #f04438; }
.magpie-error p { margin: 6px 0 12px; font-size: 12.5px; color: var(--ih-sub); line-height: 1.6; }
.magpie-head { margin-bottom: 14px; }
.magpie-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.magpie-meta code { font-size: 11.5px; color: var(--ih-ink); }
.magpie-ok {
  font-size: 11px; padding: 1px 8px; border-radius: 999px;
  background: rgba(18, 183, 106, 0.12); color: #12b76a; font-weight: 600;
}
.magpie-toolbar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 0; margin-bottom: 8px; border-bottom: 1px solid var(--ih-line);
  font-size: 12.5px;
}
.magpie-list { display: flex; flex-direction: column; gap: 6px; }
.magpie-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--ih-line); background: var(--ih-surface);
}
.magpie-item:hover { border-color: var(--ih-primary); }
.magpie-item-main { flex: 1 1 auto; min-width: 0; }
.magpie-item-name { font-size: 13px; font-weight: 600; color: var(--ih-ink); }
.magpie-item-id {
  font-size: 11px; color: var(--ih-sub); margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.magpie-badges { display: flex; gap: 5px; flex: 0 0 auto; }
.mbadge {
  font-size: 10px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-chip); color: var(--ih-sub); white-space: nowrap;
}
.mbadge--ok { background: var(--ih-primary-soft); color: var(--ih-primary); }
.mbadge--ghost { background: transparent; border: 1px solid var(--ih-line); }

.settings { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
.page-title { margin: 0; font-size: 24px; font-weight: 700; }
.page-sub { margin: 4px 0 0; font-size: 13px; color: var(--ih-sub); }

.panel { padding: 18px 20px; }

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

/* ---------- 安全与限流 ---------- */
.rate-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
.rate-cell {
  background: var(--ih-soft); border: 1px solid var(--ih-line); border-radius: 10px;
  padding: 10px 12px; display: flex; flex-direction: column; gap: 4px;
}
.rate-label { font-size: 11.5px; color: var(--ih-sub); }
.rate-value { font-size: 13px; color: var(--ih-ink); font-weight: 500; }

.rate-locks { display: flex; flex-direction: column; gap: 8px; }
.rate-locks-head { display: flex; align-items: baseline; gap: 8px; }
.rate-lock-row {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 12px; border-radius: 10px; background: var(--ih-warn-soft);
  font-size: 12px;
}
.rate-lock-key { color: var(--ih-warn-ink); font-size: 12px; }
.rate-lock-remain { margin-left: auto; color: var(--ih-warn-ink); font-size: 11.5px; }
.rate-empty { padding: 6px 0; }
.rate-hint { margin-top: 12px; font-size: 11.5px; line-height: 1.6; }

/* ---------- 项目（紧凑列表） ---------- */
.scan-result { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
.scan-line { font-size: 12.5px; color: var(--ih-sub); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.scan-line code { background: var(--ih-soft-2); padding: 1px 7px; border-radius: 5px; font-size: 11.5px; }
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

.proj-toolbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin: 16px 0 8px;
}
.proj-filter { width: 160px; margin-left: auto; }
.proj-filter-icon { color: var(--ih-sub); font-size: 13px; }

.proj-list {
  display: flex; flex-direction: column;
  border: 1px solid var(--ih-line); border-radius: 12px; overflow: hidden;
  background: var(--ih-card);
}
/* 每行只有 1 行高，比原来一张卡 100~150px 省一个数量级 */
.proj-row { border-bottom: 1px solid var(--ih-line); }
.proj-row:last-child { border-bottom: none; }
.proj-row.is-ignored { opacity: 0.55; }
.proj-row.is-open { background: var(--ih-soft); }

.proj-row-main {
  display: flex; align-items: center; gap: 12px;
  padding: 9px 12px; cursor: pointer; transition: background-color 0.14s ease;
}
.proj-row-main:hover { background: var(--ih-soft); }
.proj-row.is-open .proj-row-main:hover { background: transparent; }

/* 展开箭头：用边框拼，open 时转 90° */
.proj-caret {
  flex: 0 0 auto; width: 7px; height: 7px;
  border-right: 2px solid var(--ih-sub); border-bottom: 2px solid var(--ih-sub);
  transform: rotate(-45deg); transition: transform 0.16s ease;
}
.proj-row.is-open .proj-caret { transform: rotate(45deg); }

.proj-row-name { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; min-width: 0; }
.proj-name { font-size: 13.5px; color: var(--ih-ink); cursor: text; }
.proj-name:hover { color: var(--el-color-primary); }
.proj-name-input { width: 160px; }
.proj-count {
  font-size: 11px; padding: 0 6px; border-radius: 999px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}
.proj-tag {
  font-size: 11px; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-soft-2); color: var(--ih-sub);
}

/* 仓库目录名小标签：折叠态只给名字，不给全路径 */
.proj-row-repos { display: flex; align-items: center; gap: 6px; flex: 1 1 auto; min-width: 0; overflow: hidden; }
.proj-repo-chip {
  flex: 0 0 auto; font-size: 11px; padding: 1px 7px; border-radius: 6px;
  background: var(--ih-soft-2); color: var(--ih-sub);
  max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.proj-repo-more { flex: 0 0 auto; font-size: 11px; color: var(--ih-sub); }
.proj-row-actions { display: flex; gap: 6px; flex: 0 0 auto; }

.proj-row-detail {
  display: flex; flex-direction: column; gap: 10px;
  padding: 0 12px 14px 31px;
}
.proj-detail-block { display: flex; flex-direction: column; gap: 4px; }
.proj-detail-label { font-size: 11.5px; color: var(--ih-sub); }
.proj-detail-paths { display: flex; flex-direction: column; gap: 2px; }
.proj-detail-paths code { font-size: 11.5px; color: var(--ih-ink); word-break: break-all; }
.proj-empty { padding: 16px 12px; }

.footer { display: flex; justify-content: space-between; align-items: center; padding: 4px 2px 10px; }


@media (max-width: 768px) {

}

@media (max-width: 768px) {
  .notify-grid { grid-template-columns: 1fr; align-items: stretch; }
  .notify-switch { padding-bottom: 0; }
  .page-head .el-button { display: none; }
  .panel { padding: 14px; }
  .field-grid { grid-template-columns: 1fr; }
  .field--wide { grid-column: span 1; }
  .footer { position: sticky; bottom: calc(64px + env(safe-area-inset-bottom)); }
  /* footer 是 sticky 的，会盖住页面最后一段内容，补足留白 */
  .settings { padding-bottom: calc(64px + env(safe-area-inset-bottom)); }

  /* 区块头部：窄屏下标题与按钮各占一行，别挤成一团 */

  /* 项目行：手机上横向放不下「名称+标签+两按钮」，改成两行 */
  .proj-toolbar { gap: 8px; }
  .proj-filter { width: 100%; margin-left: 0; }
  .proj-row-main { flex-wrap: wrap; gap: 6px; padding: 10px 12px; }
  .proj-row-name { flex: 1 1 auto; }
  .proj-row-actions { margin-left: auto; }
  .proj-row-repos { flex: 1 1 100%; padding-left: 15px; }
  .proj-repo-chip { max-width: 140px; }
  .proj-row-detail { padding-left: 27px; }
}
</style>
