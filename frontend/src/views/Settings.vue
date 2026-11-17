<template>
  <div class="settings">
    <div class="page-head">
      <div>
        <h1 class="page-title">设置</h1>
        <p class="page-sub">选择 AI 执行器、填 API Key、配置代码仓库路径</p>
      </div>
      <el-button type="primary" round :loading="saving" @click="save">保存配置</el-button>
    </div>

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

    <!-- 执行器 -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge">AI</span>
          <div>
            <h2>默认执行器</h2>
            <p>单次操作也可以在详情页临时切换</p>
          </div>
        </div>
      </div>

      <div class="provider-grid">
        <button
          v-for="p in providers"
          :key="p"
          class="provider-card"
          :class="{ 'is-on': form['ai.provider'] === p }"
          @click="form['ai.provider'] = p"
        >
          <span class="provider-name">{{ label(p) }}</span>
          <span class="provider-desc">{{ desc(p) }}</span>
        </button>
      </div>

      <div class="field-grid">
        <label class="field">
          <span class="field-label">超时（秒）</span>
          <el-input v-model="form['ai.timeout']" />
        </label>
        <label class="field field--wide">
          <span class="field-label">代码仓库根目录</span>
          <el-input v-model="form['repo.root']" placeholder="/src/gym-fold" />
          <span class="field-hint">dsh / claude 在这个目录下分析代码；多个仓库时填父目录</span>
        </label>
      </div>
    </section>

    <!-- DeepSeek -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--blue">DS</span>
          <div>
            <h2>DeepSeek API</h2>
            <p>最快的定性/定级通道，看不到代码</p>
          </div>
        </div>
        <el-tag v-if="form['deepseek.api_key_set']" type="success" effect="light">已配置 Key</el-tag>
      </div>

      <div class="field-grid">
        <label class="field field--wide">
          <span class="field-label">Base URL</span>
          <el-input v-model="form['deepseek.base_url']" />
        </label>
        <label class="field">
          <span class="field-label">模型</span>
          <el-input v-model="form['deepseek.model']" placeholder="deepseek-chat" />
        </label>
        <label class="field field--wide">
          <span class="field-label">API Key</span>
          <el-input
            v-model="form['deepseek.api_key']"
            type="password"
            show-password
            :placeholder="form['deepseek.api_key_set'] ? '已配置，留空表示不修改' : 'sk-...'"
          />
        </label>
      </div>
    </section>

    <!-- CLI -->
    <section class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">&gt;_</span>
          <div>
            <h2>命令行执行器</h2>
            <p>同机运行，能读仓库；只做只读分析，不改文件</p>
          </div>
        </div>
      </div>

      <div class="field-grid">
        <label class="field">
          <span class="field-label">dsh 命令</span>
          <el-input v-model="form['dsh.bin']" placeholder="dsh" />
        </label>
        <label class="field">
          <span class="field-label">dsh profile</span>
          <el-input v-model="form['dsh.profile']" placeholder="headless" />
        </label>
        <label class="field">
          <span class="field-label">claude 命令</span>
          <el-input v-model="form['claude.bin']" placeholder="claude" />
        </label>
        <label class="field">
          <span class="field-label">claude 模型</span>
          <el-input v-model="form['claude.model']" placeholder="留空用默认" />
        </label>
      </div>

      <p class="tip">
        命令不在默认 PATH 时填绝对路径（如 <code>~/.nvm/versions/node/v24.16.0/bin/claude</code>）。
        用 <code>./start.sh</code> 启动会自动补 nvm PATH。
      </p>
    </section>

    <div class="footer">
      <span class="ih-muted">定级规则版本：{{ rubricVersion }}</span>
      <el-button type="primary" round :loading="saving" @click="save">保存配置</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSettings, saveSettings } from '../api'
import { useTheme } from '../useTheme'

const { mode, setMode } = useTheme()
const form = reactive<Record<string, any>>({})
const providers = ref<string[]>([])
const rubricVersion = ref('')
const saving = ref(false)

const label = (p: string) =>
  ({ mock: 'Mock', deepseek: 'DeepSeek API', dsh: 'dsh harness', claude: 'Claude Code' } as any)[p] || p
const desc = (p: string) =>
  ({
    mock: '假数据，验证流程，不花额度',
    deepseek: '快、便宜，仅看文字',
    dsh: '同机读仓库，DeepSeek 驱动',
    claude: '同机读仓库，适合深析'
  } as any)[p] || ''

const load = async () => {
  const res = await getSettings()
  Object.assign(form, res.settings)
  providers.value = res.providers
  rubricVersion.value = res.rubricVersion
}

const save = async () => {
  saving.value = true
  try {
    const values: Record<string, any> = {}
    for (const [k, v] of Object.entries(form)) {
      if (k.endsWith('_set')) continue
      values[k] = v
    }
    await saveSettings(values)
    ElMessage.success('已保存')
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
.page-title { margin: 0; font-size: 24px; font-weight: 700; }
.page-sub { margin: 4px 0 0; font-size: 13px; color: var(--ih-sub); }

.panel { padding: 18px 20px; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.panel-title { display: flex; gap: 12px; align-items: flex-start; }
.panel-title h2 { margin: 0; font-size: 16px; font-weight: 700; }
.panel-title p { margin: 3px 0 0; font-size: 12px; color: var(--ih-sub); }
.step-badge {
  flex: 0 0 auto; min-width: 30px; height: 28px; padding: 0 8px; border-radius: 9px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, var(--ih-primary), var(--ih-primary-2));
}
.step-badge--blue { background: linear-gradient(135deg, #1570ef, #2e90fa); }
.step-badge--gray { background: var(--ih-soft-2); color: var(--ih-sub); }

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

.footer { display: flex; justify-content: space-between; align-items: center; padding: 4px 2px 10px; }

@media (max-width: 768px) {
  .page-head .el-button { display: none; }
  .panel { padding: 14px; }
  .provider-grid { grid-template-columns: 1fr 1fr; }
  .field-grid { grid-template-columns: 1fr; }
  .field--wide { grid-column: span 1; }
  .footer { position: sticky; bottom: calc(64px + env(safe-area-inset-bottom)); }
}
</style>
