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

    <!-- 账号（仅管理员可见）：用户管理 + 登录记录 -->
    <section v-if="me?.role === 'admin'" class="panel ih-card">
      <div class="panel-head">
        <div class="panel-title">
          <span class="step-badge step-badge--gray">👥</span>
          <div>
            <h2>账号</h2>
            <p>每人只能看到自己的问题、项目和通道；管理员可以管所有人和所有通道</p>
          </div>
        </div>
        <div class="panel-actions">
          <el-button v-if="accountTab === 'users'" round :loading="usersLoading" @click="loadUsers">刷新</el-button>
          <el-button v-if="accountTab === 'users'" type="primary" round @click="openCreateUser">＋ 新建用户</el-button>
          <el-button v-else round :loading="logsLoading" @click="loadLogs">刷新</el-button>
        </div>
      </div>

      <div class="acct-tabs">
        <button
          class="acct-tab" :class="{ 'is-on': accountTab === 'users' }"
          @click="switchAccountTab('users')"
        >用户管理 <span class="acct-count">{{ users.length }}</span></button>
        <button
          class="acct-tab" :class="{ 'is-on': accountTab === 'logs' }"
          @click="switchAccountTab('logs')"
        >登录记录 <span class="acct-count">{{ logs.total }}</span></button>
      </div>

      <!-- 用户管理 -->
      <div v-show="accountTab === 'users'" class="user-list">
        <div v-for="u in users" :key="u.id" class="user-row">
          <div class="user-main">
            <div class="user-name">
              {{ u.display_name || u.username }}
              <span class="user-role" :class="`is-${u.role}`">{{ u.role === 'admin' ? '管理员' : '普通' }}</span>
              <span v-if="!u.enabled" class="user-tag">已停用</span>
              <span v-if="me && u.id === me.id" class="user-tag is-me">当前登录</span>
            </div>
            <div class="user-account">
              <code>{{ u.username }}</code>
              <span v-if="u.created_at" class="ih-muted">创建于 {{ u.created_at }}</span>
            </div>
          </div>
          <div class="user-actions">
            <el-button size="small" round @click="openResetPassword(u)">改密码</el-button>
            <el-button
              size="small" round :disabled="me && u.id === me.id"
              @click="doToggleUser(u)"
            >{{ u.enabled ? '停用' : '启用' }}</el-button>
            <el-button
              size="small" round type="danger" plain :disabled="me && u.id === me.id"
              @click="doDeleteUser(u)"
            >删除</el-button>
          </div>
        </div>
        <div v-if="!users.length" class="ih-muted user-empty">
          还没有用户。
        </div>
      </div>

      <!-- 登录记录 -->
      <div v-show="accountTab === 'logs'" class="log-wrap">
        <div class="log-filter">
          <el-input
            v-model="logKeyword" placeholder="搜用户名 / IP / 归属地"
            clearable class="log-search" @keyup.enter="applyLogFilter"
          >
            <template #prefix><span class="log-search-icon">⌕</span></template>
          </el-input>
          <el-select v-model="logResult" placeholder="全部结果" clearable class="log-select" @change="applyLogFilter">
            <el-option label="登录成功" value="ok" />
            <el-option label="密码错误" value="bad_password" />
            <el-option label="用户不存在" value="no_user" />
            <el-option label="账号已停用" value="disabled" />
            <el-option label="被限流锁定" value="locked" />
            <el-option label="IP 不在白名单" value="bad_ip" />
            <el-option label="退出登录" value="logout" />
          </el-select>
          <el-button round @click="applyLogFilter">查询</el-button>
          <el-button round type="danger" plain class="log-clear" @click="doClearLogs">清空</el-button>
        </div>

        <!-- 桌面：表格 -->
        <div v-if="!isMobile" class="log-table-wrap">
          <table class="log-table">
            <thead>
              <tr>
                <th class="col-time">时间</th>
                <th class="col-user">账号</th>
                <th class="col-result">结果</th>
                <th class="col-ip">IP</th>
                <th class="col-region">归属地</th>
                <th class="col-agent">客户端</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in logs.items" :key="l.id">
                <td class="col-time">{{ l.created_at }}</td>
                <td class="col-user">
                  <b>{{ l.display_name || l.username }}</b>
                  <span v-if="l.display_name && l.display_name !== l.username" class="log-account">{{ l.username }}</span>
                </td>
                <td class="col-result">
                  <span class="log-result" :class="l.success ? 'is-ok' : 'is-bad'">{{ l.resultLabel }}</span>
                </td>
                <td class="col-ip"><code>{{ l.ip || '—' }}</code></td>
                <td class="col-region">{{ l.ip_region || '—' }}</td>
                <td class="col-agent">
                  <span class="log-agent" :title="l.user_agent">{{ shortAgent(l.user_agent) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="!logs.items.length" class="ih-muted user-empty">没有匹配的登录记录。</div>
        </div>

        <!-- 手机：卡片 -->
        <div v-else class="log-cards">
          <div v-for="l in logs.items" :key="l.id" class="log-card">
            <div class="log-card-head">
              <span class="log-result" :class="l.success ? 'is-ok' : 'is-bad'">{{ l.resultLabel }}</span>
              <span class="log-time">{{ l.created_at }}</span>
            </div>
            <div class="log-card-user">{{ l.display_name || l.username }}</div>
            <div class="log-card-line">
              <code>{{ l.ip || '—' }}</code>
              <span class="log-region">{{ l.ip_region || '未知' }}</span>
            </div>
            <div v-if="l.user_agent" class="log-card-agent">{{ shortAgent(l.user_agent) }}</div>
          </div>
          <div v-if="!logs.items.length" class="ih-muted user-empty">没有匹配的登录记录。</div>
        </div>

        <div v-if="logs.total > logsPageSize" class="log-pager">
          <el-button size="small" round :disabled="logsPage === 0" @click="logsPrev">上一页</el-button>
          <span class="ih-muted">
            {{ logsPage + 1 }} / {{ Math.max(1, Math.ceil(logs.total / logsPageSize)) }} 页 · 共 {{ logs.total }} 条
          </span>
          <el-button size="small" round :disabled="logsPage + 1 >= Math.ceil(logs.total / logsPageSize)" @click="logsNext">下一页</el-button>
        </div>
      </div>

      <p v-if="accountTab === 'users'" class="field-hint user-hint">
        登录开关在「其他代码设置」里。开之前先确认已配好 IP 白名单，
        否则换网络就登不进来了。
      </p>
    </section>


    <!-- 用户编辑抽屉 -->
    <el-drawer
      v-model="userDrawer" :title="userForm.id ? '重置密码' : '新建用户'"
      :size="isMobile ? '100%' : '460px'" append-to-body
    >
      <el-form label-position="top">
        <template v-if="!userForm.id">
          <el-form-item label="用户名">
            <el-input v-model="userForm.username" placeholder="登录用，字母数字" />
          </el-form-item>
          <el-form-item label="显示名">
            <el-input v-model="userForm.display_name" placeholder="可选，列表里显示的名字" />
          </el-form-item>
          <el-form-item label="角色">
            <el-radio-group v-model="userForm.role">
              <el-radio-button value="user">普通</el-radio-button>
              <el-radio-button value="admin">管理员</el-radio-button>
            </el-radio-group>
            <div class="field-hint">
              管理员能看所有人的问题、管理用户和通道；普通用户只看自己的
            </div>
          </el-form-item>
        </template>
        <el-form-item :label="userForm.id ? `给 ${userForm.username} 设置新密码` : '密码'">
          <el-input
            v-model="userForm.password" type="password" show-password
            placeholder="至少 6 位" @keyup.enter="saveUser"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDrawer = false">取消</el-button>
        <el-button type="primary" :loading="userSaving" @click="saveUser">保存</el-button>
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
  changePassword, clearRate, clearLoginLogs, createChannel, createProject, createUser,
  deleteChannel, deleteProject, deleteUser, getChannels, getLoginLogs, getMe, getProjects,
  getRateStatus, getSettings, listChannelModels, listUsers, mergeProjects, saveSettings,
  scanRepos, testChannel, toggleUser, unlockRate, updateChannel, updateProject,
  type AppUser, type AuthUser, type Channel, type LoginLog, type Project, type ScanResult
} from '../api'
import { useTheme } from '../useTheme'
import { useMobile } from '../useMobile'

const { mode, setMode } = useTheme()
const isMobile = useMobile()
const form = reactive<Record<string, any>>({})
const rubricVersion = ref('')
const saving = ref(false)

/* ===== 账号：用户管理 / 登录记录 ===== */
const accountTab = ref<'users' | 'logs'>('users')
const me = ref<AuthUser | null>(null)
const users = ref<AppUser[]>([])
const usersLoading = ref(false)
const userDrawer = ref(false)
const userSaving = ref(false)
const userForm = reactive<Record<string, any>>({
  id: 0, username: '', display_name: '', role: 'user', password: ''
})

/* ---------- 登录记录 ---------- */
const logs = reactive<{ items: LoginLog[]; total: number }>({ items: [], total: 0 })
const logsLoading = ref(false)
const logsPage = ref(0)
const logsPageSize = 30
const logKeyword = ref('')
const logResult = ref('')

const loadLogs = async () => {
  logsLoading.value = true
  try {
    const r = await getLoginLogs({
      limit: logsPageSize,
      offset: logsPage.value * logsPageSize,
      keyword: logKeyword.value.trim(),
      result: logResult.value || ''
    })
    logs.items = r.items || []
    logs.total = r.total || 0
  } catch {
    logs.items = []
    logs.total = 0
  } finally {
    logsLoading.value = false
  }
}

const applyLogFilter = () => {
  logsPage.value = 0
  loadLogs()
}

const logsPrev = () => {
  if (logsPage.value === 0) return
  logsPage.value -= 1
  loadLogs()
}

const logsNext = () => {
  if ((logsPage.value + 1) * logsPageSize >= logs.total) return
  logsPage.value += 1
  loadLogs()
}

/** UA 太长，表格里只留浏览器+系统这种能看懂的部分 */
const shortAgent = (ua: string) => {
  if (!ua) return '—'
  const browser =
    /Edg\/([\d.]+)/.exec(ua)?.[0]?.replace('Edg/', 'Edge ') ||
    /Chrome\/([\d.]+)/.exec(ua)?.[0]?.replace('Chrome/', 'Chrome ') ||
    /Firefox\/([\d.]+)/.exec(ua)?.[0]?.replace('Firefox/', 'Firefox ') ||
    /Version\/([\d.]+).*Safari/.exec(ua)?.[0]?.replace(/Version\/([\d.]+).*/, 'Safari $1') ||
    ''
  // 顺序要紧：iPhone/iPad 的 UA 里也有 "Mac OS X"，必须先判 iOS
  const os = /Windows NT/.test(ua) ? 'Windows'
    : /iPhone|iPad|iPod/.test(ua) ? 'iOS'
    : /Android/.test(ua) ? 'Android'
    : /Macintosh|Mac OS X/.test(ua) ? 'macOS'
    : /Linux/.test(ua) ? 'Linux' : ''
  if (browser && os) return `${browser} · ${os}`
  if (browser) return browser
  if (os) return os
  return ua.length > 28 ? ua.slice(0, 28) + '…' : ua
}

const switchAccountTab = (tab: 'users' | 'logs') => {
  accountTab.value = tab
  if (tab === 'logs' && !logs.items.length) loadLogs()
}

const doClearLogs = async () => {
  await ElMessageBox.confirm(
    '清空全部登录记录？这一步不能撤销，审计信息会永久丢失。',
    '提示', { type: 'warning' })
  const r = await clearLoginLogs()
  logsPage.value = 0
  await loadLogs()
  ElMessage.success(`已清空 ${r.deleted ?? 0} 条`)
}

const loadUsers = async () => {
  usersLoading.value = true
  try {
    const r = await listUsers()
    users.value = r.users || []
  } catch {
    users.value = []
  } finally {
    usersLoading.value = false
  }
}

const resetUserForm = () => {
  Object.assign(userForm, { id: 0, username: '', display_name: '', role: 'user', password: '' })
}

const openCreateUser = () => {
  resetUserForm()
  userDrawer.value = true
}

const openResetPassword = (u: AppUser) => {
  resetUserForm()
  Object.assign(userForm, { id: u.id, username: u.username })
  userDrawer.value = true
}

const saveUser = async () => {
  if (!userForm.password || userForm.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  userSaving.value = true
  try {
    if (userForm.id) {
      await changePassword(userForm.id, userForm.password)
      ElMessage.success('密码已重置')
    } else {
      if (!userForm.username.trim()) {
        ElMessage.warning('请填用户名')
        return
      }
      await createUser({
        username: userForm.username.trim(),
        password: userForm.password,
        display_name: userForm.display_name || userForm.username.trim(),
        role: userForm.role
      })
      ElMessage.success('用户已创建')
    }
    userDrawer.value = false
    await loadUsers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    userSaving.value = false
  }
}

const doToggleUser = async (u: AppUser) => {
  await toggleUser(u.id, !u.enabled)
  await loadUsers()
  ElMessage.success(u.enabled ? '已停用' : '已启用')
}

const doDeleteUser = async (u: AppUser) => {
  await ElMessageBox.confirm(
    `删除用户「${u.display_name || u.username}」？他的问题会变成「无归属」，不会删除。`,
    '提示', { type: 'warning' })
  await deleteUser(u.id)
  await loadUsers()
  ElMessage.success('已删除')
}

/* ===== 安全与限流 ===== */
const rate = ref<any>(null)
const rateLoading = ref(false)

const activeLocks = computed(() =>
  ((rate.value?.locks || []) as any[]).filter((l) => l.active)
)

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
  // 当前用户：决定「用户」区块是否显示
  const m = await getMe().catch(() => null)
  me.value = m?.user || null
  if (me.value?.role === 'admin') {
    await loadUsers()
    await loadLogs()
  }
})
</script>

<style scoped>
.settings { display: flex; flex-direction: column; gap: 14px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
.page-title { margin: 0; font-size: 24px; font-weight: 700; }
.page-sub { margin: 4px 0 0; font-size: 13px; color: var(--ih-sub); }

.panel { padding: 18px 20px; }
.panel-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 12px; flex-wrap: wrap; margin-bottom: 14px;
}
.panel-title { display: flex; gap: 12px; align-items: flex-start; flex: 1 1 260px; min-width: 0; }
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

/* ===== 账号：tab 切换 ===== */
.acct-tabs {
  display: flex; gap: 6px; margin-bottom: 14px;
  padding: 4px; border-radius: 12px; background: var(--ih-soft);
  width: fit-content;
}
.acct-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border: none; border-radius: 9px;
  background: transparent; color: var(--ih-sub);
  font-size: 13px; font-weight: 500; cursor: pointer;
  transition: all 0.16s ease; -webkit-appearance: none;
}
.acct-tab:hover { color: var(--ih-ink); }
.acct-tab.is-on {
  background: var(--ih-card); color: var(--ih-primary); font-weight: 600;
  box-shadow: 0 1px 3px rgba(16, 24, 40, 0.1);
}
.acct-count {
  min-width: 18px; padding: 0 5px; border-radius: 999px;
  font-size: 10.5px; font-weight: 600; line-height: 16px; text-align: center;
  background: var(--ih-chip); color: var(--ih-sub);
}
.acct-tab.is-on .acct-count { background: var(--ih-primary-soft); color: var(--ih-primary); }

/* ===== 登录记录 ===== */
.log-wrap { display: flex; flex-direction: column; gap: 10px; }
.log-filter { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.log-search { flex: 1 1 200px; min-width: 150px; }
.log-select { width: 130px; flex: 0 0 auto; }
.log-search-icon { color: var(--ih-sub); font-size: 13px; }

.log-table-wrap { overflow-x: auto; border-radius: 12px; border: 1px solid var(--ih-line); }
.log-table {
  width: 100%; border-collapse: collapse; font-size: 12.5px;
  background: var(--ih-surface);
}
.log-table th {
  text-align: left; font-weight: 600; font-size: 11.5px; color: var(--ih-sub);
  padding: 9px 10px; border-bottom: 1px solid var(--ih-line);
  background: var(--ih-soft); white-space: nowrap;
}
.log-table td {
  padding: 9px 10px; border-bottom: 1px solid var(--ih-line);
  color: var(--ih-ink); vertical-align: middle;
}
.log-table tr:last-child td { border-bottom: none; }
.log-table tbody tr:hover { background: var(--ih-soft); }
.col-time { white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--ih-sub); }
.col-user { white-space: nowrap; }
.col-ip code { font-size: 12px; }
.col-region { color: var(--ih-sub); }
.log-account { margin-left: 5px; font-size: 11px; color: var(--ih-sub); }
.log-agent {
  display: inline-block; max-width: 150px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; color: var(--ih-sub); font-size: 11.5px;
}

.log-result {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 500; white-space: nowrap;
}
.log-result.is-ok { background: rgba(18, 183, 106, 0.12); color: #12b76a; }
.log-result.is-bad { background: rgba(240, 68, 56, 0.1); color: #f04438; }

.log-cards { display: flex; flex-direction: column; gap: 8px; }
.log-card {
  padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--ih-line); background: var(--ih-surface);
  display: flex; flex-direction: column; gap: 5px;
}
.log-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.log-time { font-size: 11px; color: var(--ih-sub); font-variant-numeric: tabular-nums; }
.log-card-user { font-size: 13.5px; font-weight: 600; color: var(--ih-ink); }
.log-card-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11.5px; }
.log-card-line code { font-size: 11.5px; color: var(--ih-ink); }
.log-region { color: var(--ih-sub); }
.log-card-agent { font-size: 11px; color: var(--ih-sub); }

.log-pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding-top: 4px; font-size: 12px; }

/* ===== 用户管理 ===== */
.user-list { display: flex; flex-direction: column; gap: 8px; }
.user-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--ih-line); background: var(--ih-surface);
}
.user-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.user-name {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 13.5px; font-weight: 600; color: var(--ih-ink);
}
.user-role {
  font-size: 10.5px; font-weight: 500; padding: 1px 7px; border-radius: 999px;
  background: var(--ih-chip); color: var(--ih-sub);
}
.user-role.is-admin { background: rgba(79, 70, 229, 0.12); color: var(--ih-primary); }
.user-tag {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  background: rgba(240, 68, 56, 0.1); color: #f04438;
}
.user-tag.is-me { background: rgba(18, 183, 106, 0.12); color: #12b76a; }
.user-account {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 11.5px; color: var(--ih-sub);
}
.user-account code { font-size: 11.5px; color: var(--ih-ink); }
.user-actions { display: flex; gap: 6px; flex-shrink: 0; }
.user-empty { padding: 16px 12px; }
.user-hint { margin-top: 10px; }

@media (max-width: 768px) {
  /* 登录记录筛选：窄屏下输入框占满一行 */
  .acct-tabs { width: 100%; }
  .acct-tab { flex: 1; justify-content: center; }
  .log-search { flex: 1 1 100%; }
  .log-select { flex: 1 1 45%; width: auto; }
  .log-clear { flex: 0 0 auto; }

  /* 手机上按钮换行到下一行，避免挤压用户名 */
  .user-row { flex-direction: column; align-items: stretch; gap: 8px; }
  .user-actions { justify-content: flex-end; }
}

@media (max-width: 768px) {
  .page-head .el-button { display: none; }
  .panel { padding: 14px; }
  .field-grid { grid-template-columns: 1fr; }
  .field--wide { grid-column: span 1; }
  .footer { position: sticky; bottom: calc(64px + env(safe-area-inset-bottom)); }
  /* footer 是 sticky 的，会盖住页面最后一段内容，补足留白 */
  .settings { padding-bottom: calc(64px + env(safe-area-inset-bottom)); }

  /* 区块头部：窄屏下标题与按钮各占一行，别挤成一团 */
  .panel-head { flex-wrap: wrap; }
  .panel-title { flex: 1 1 100%; }
  .panel-actions { width: 100%; justify-content: flex-end; }

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
