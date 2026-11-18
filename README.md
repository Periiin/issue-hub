# Issue Hub · 甲方问题跟踪

记录甲方通过微信/电话反馈的问题 → AI 整理成结构化描述（定性）→ 人工确认 → AI 定级（S/P）→ 生成修复方案。
单机自托管，手机浏览器也能用。

访问：**http://192.168.110.12:8090/**

## 快速开始

```bash
cd /src/issue-hub
./start.sh          # 首次会自动装依赖、构建前端
# 后台跑：nohup ./start.sh > /tmp/issuehub.log 2>&1 &
./stop.sh           # 停止
```

开发前端（热更新）：`cd frontend && npm run dev`（5175，自动代理 /api、/files 到 8090）。

## 使用流程

1. **新建问题**：粘贴甲方原话，截图直接 `Ctrl+V`（微信截图）或选文件；填提出人/模块。
2. **① AI 定性**：选执行器 → 点「AI 定性」→ 得到结构化描述（现象/复现/期望/实际/范围/待确认）。
3. **人工确认**：改完点「确认定性，进入定级」。**没确认不能定级**，避免垃圾进垃圾出。
4. **② AI 定级**：给出 S1~S4（影响）、简单/中等/复杂（改动成本）、P0~P3（优先级）和依据。
   结果可以手动改，改完立即保存。
5. **③ 操作解决**：让 agent 在 `repo.root` 里定位根因、列改动清单。
   **当前版本不改代码**，只给方案；改代码建议在 worktree 里做、人工合并。
6. **导出**：单条「导出 Markdown」，列表页「导出周报」按优先级分组。

## AI 执行器

在「设置」里选默认执行器，单次操作也可以临时切换（详情页有下拉框）。

| 执行器 | 说明 | 需要什么 |
|---|---|---|
| `mock` | 返回固定假数据，用来验证流程，不花额度 | 无 |
| `deepseek` | 调 DeepSeek OpenAI 兼容接口，快、便宜，**看不到代码** | API Key |
| `dsh` | `dsh --profile headless "<任务>"`，同机可读仓库 | 本机装好 dsh |
| `claude` | `claude -p "<任务>"`，同机可读仓库（只读工具白名单） | 本机装好 claude |

提示词在 `backend/app/prompts.py`，定级规则带版本号（`RUBRIC_VERSION`），改规则时递增即可追溯。

## 主题（亮 / 暗）

- 右上角月亮/太阳按钮一键切换；设置页可选「浅色 / 深色 / 跟随系统」，选择存 `localStorage.ih-theme`
- 实现：`<html class="dark">` 同时驱动 Element Plus 暗色变量和自定义变量（`frontend/src/styles.css`）
- **新增页面必须用变量，不要写死色值**：
  `--ih-bg` 页面底 · `--ih-card` 卡片底 · `--ih-soft` / `--ih-soft-2` 浅填充 · `--ih-ink` 主文字 ·
  `--ih-sub` 次文字 · `--ih-line` 描边 · `--ih-primary-soft` / `--ih-warn-soft` / `--ih-success-soft` 语义底色
- 自检：`?` 不传参，点右上角切到深色，逐页看是否有白底/黑字硬编码残留

## MCP：让 AI 会话直接读写 issue

已注册到 `~/.zcode/cli/config.json`（`mcp.servers.issue-hub`），**重启 ZCode 生效**；之后会话里会出现
`mcp__issue-hub__*` 工具，可以直接说「把这周的 issue 过一遍，按 P0-P3 排好」。

提供的工具：

| 工具 | 作用 |
|---|---|
| `list_issues` | 按状态/优先级/模块/关键词列问题，带各状态数量 |
| `get_issue` | 单条完整信息（原文、确认后的描述、定级、修复方案、附件绝对路径、时间线） |
| `create_issue` | 新建问题 |
| `update_issue` | 改状态/标题/模块/提出人/等级/复杂度/优先级 |
| `add_note` | 加一条时间线备注 |
| `run_qualify` | 跑 AI 定性（草稿） |
| `confirm_qualify` | 确认定性 → 待定级 |
| `run_triage` | 跑 AI 定级 → 待处理 |
| `make_fix_plan` | 在代码目录里定位根因、给方案（只读） |
| `weekly_report` | 输出周报 Markdown |

MCP 直接读 SQLite，**不依赖 Web 服务是否在跑**。用的是独立 venv `.venv-mcp`，
避免和 FastAPI 抢 `starlette` 版本。

手动验证：

```bash
cd /src/issue-hub/backend
.venv-mcp/bin/python /tmp/mcp_client_test.py    # 需要一个用官方 SDK 写的客户端脚本
```

## 项目（Project）

一个项目 = 一组**各自独立**的 git 仓库。现实里「一个系统」经常是多个仓库
（gym = java + vue + 两个 uniapp），而且它们不一定在同一个父目录下
（`mes-java-2` 和 `mes-vue-2.0` 就在 `/src` 同级）。

```
project(id, name, repos[json], notes, ignored)
issue.project_id  →  归属项目
```

选定项目后：
- **代码范围**（分析搜索哪些目录）= 项目里的仓库
- **可改仓库**（worktree 在哪些仓库建）= 项目里的仓库，可在详情页临时取消某个

仓库仍然是独立仓库：worktree / branch / merge 都在单个仓库里做，项目只是集合。

### 配置：扫描根代替手填目录

设置页只配「扫描根」（一行一个，如 `/src`、`E:/project`），
后端自动往下 3 层找 git 仓库并聚成候选项目：

| 情况 | 聚类结果 |
|---|---|
| 扫描根的**直接子仓库** | 各自独立项目（bom-editor / gym-uniapp / issue-hub …） |
| 扫描根**子目录里的仓库** | 按子目录聚成一个项目（gym-fold 4 个 / asano-mes 2 个） |
| 名字前缀相近但不同父目录 | **只给合并建议，不自动合并**（mes-java-2 + mes-vue-2.0 → 建议合成 mes） |

换机器只改扫描根，不用重新维护一堆目录。

### 接口

```
GET   /api/code/scan?dry=true     扫描预览（不入库）
GET   /api/code/scan?dry=false    扫描并导入新候选项目（已存在的跳过）
GET   /api/projects               项目列表（含 ignored）
POST  /api/projects               新建 {name, repos[], notes}
PATCH /api/projects/{id}          改名 / 改仓库 / 说明 / ignored
DELETE /api/projects/{id}         删除（关联 issue 的 project_id 置空，不删 issue）
POST  /api/projects/merge         合并 {target_id, source_id, name}
GET   /api/code/roots?project_id= 候选仓库（传 project_id 只返回该项目）
```

## 操作解决闭环

```
生成修复方案（只读）
  → 在 code_scopes 里定位根因，写 fix_plan
开始修改（写）
  → 在 target_repo 上建 worktree（分支 issue-<id>）
  → agent（claude / dsh）只改 worktree 里的文件
  → 收集 git diff（stat + 逐行）
采纳并合并
  → 在 worktree 提交
  → 主仓库干净时 ff 合回当前分支；不干净则只提交并给出手工合并命令
驳回
  → 删除 worktree 和分支，状态回到「待处理」
```

护栏：

- 只改 worktree，绝不直接动主仓库工作区
- 不 push、不部署、不连生产库
- 主仓库有未提交改动时**拒绝自动合并**
- 只有 `claude` / `dsh` 能执行「开始修改」（DeepSeek API 只能出文本）

相关 API：

```
GET  /api/code/roots              候选目录（带 isGit/exists）
POST /api/issues/{id}/fix/apply   { provider, repo }  建 worktree 并让 agent 改
GET  /api/issues/{id}/fix/diff    重新收集 diff
POST /api/issues/{id}/fix/accept  { message, merge }  提交 +（可选）合并
POST /api/issues/{id}/fix/reject  丢弃 worktree 与分支
```

## 数据
## 数据

```
data/issuehub.db          SQLite 主库（备份就拷这个文件）
data/attachments/<id>/    截图、PDF
```

> 无登录鉴权，默认只在内网用。要挂到公网请先套 nginx basic auth 或加访问令牌。

## API（前端用到的都在这里）

```
GET    /api/issues?status=&priority=&module=&q=
POST   /api/issues                        {title,raw_text,source,reporter,module}
GET    /api/issues/{id}                   详情（含附件/运行记录/时间线）
PATCH  /api/issues/{id}                   改标题/描述/状态/定级字段
DELETE /api/issues/{id}
POST   /api/issues/{id}/attachments       multipart files[]
DELETE /api/issues/{id}/attachments/{aid}
POST   /api/issues/{id}/qualify           {provider?}  → 定性草稿
POST   /api/issues/{id}/qualify/confirm   人工确认 → 待定级
POST   /api/issues/{id}/triage            {provider?}  → 定级 → 待处理
POST   /api/issues/{id}/fix               {provider?}  → 修复方案
GET    /api/issues/{id}/export            Markdown
GET    /api/report/weekly                 周报
GET/PUT /api/settings
```

## 目录

```
backend/app/
  main.py        FastAPI 入口（同时托管前端 dist）
  db.py          SQLite + 表结构
  providers.py   AI 执行器（mock/deepseek/dsh/claude）
  prompts.py     定性/定级/修复提示词 + JSON 解析
  routers/       issues / ai / report / settings
frontend/src/
  views/         IssueList / IssueDetail / Settings
  api.ts         接口封装
```

## 下一步（还没做）

- 「操作解决」接 worktree：建分支 → agent 改代码 → 出 diff → 人工采纳才合并
- MCP server：让 ZCode 会话直接读写 issue 库（现在只能通过网页/API）
- 附件 OCR / 多模态读图（目前 claude/dsh 能读图，deepseek 只能看文字）
- 简单鉴权、甲方只读分享链接
