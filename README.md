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

## AI 通道

「执行器」这个概念被换成了「通道」：用户真正拥有的是一组 API 端点和模型名，
而不是写死的三选一。设置页可以配任意多个通道，issue 上记住上次用的。

| 类型 | 说明 | 能改代码 |
|---|---|---|
| **API 端点** | OpenAI 兼容格式（官方 / 中转站 / 自建都行） | ✅ 靠内置工具循环 |
| **本地 Agent** | `claude` / `dsh` 这类命令行，自带文件工具 | ✅ 开箱即可 |
| **Mock** | 假数据，验证流程不花额度 | ❌ |

配置项：名称、Base URL、API Key、模型（可点「拉取模型」从 `/v1/models` 取）、
温度、工具循环最大轮数。有「测试」按钮做真实连通性检查。

### 截图识别（多模态）

甲方截图里的报错和界面状态往往是最关键的信息。API 通道会把附件图片转成
base64 的 `image_url` 内容块（`app/vision.py`）：

```python
[{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
 {"type": "text", "text": "问题描述 + 指令"}]
```

- 支持 png/jpeg/webp/gif，单张 ≤4MB，单次最多 6 张
- 转不进去的图（超限/格式不支持）会在文本里注明「有 N 个附件无法读取，
  请不要猜测图中信息」——避免模型臆造
- 没有可用图片时退回纯字符串，兼容只支持文本的模型
- claude / dsh 这类能自己读文件的 agent 走文件路径，不重复编码

### 采纳前强制验证

模型改完代码 ≠ 代码能编译。采纳时会在 **worktree 里**先跑验证，失败就阻止提交。

命令优先级：`project.verify_cmd`（手动配）→ 自动推断：

| 特征 | 推断命令 |
|---|---|
| `pom.xml` | `mvn -q -DskipTests compile` |
| `build.gradle` | `./gradlew -q compileJava` |
| `package.json` 有 type-check/typecheck/lint/build | `npm run <那个脚本>` |
| 有 `tsconfig.json` | `npx vue-tsc --noEmit \|\| npx tsc --noEmit` |
| `go.mod` / `Cargo.toml` | `go build ./...` / `cargo check` |

推断不出来时 `ok=null`（跳过，不阻断），但会在 UI 里提示「未验证」。

接口：`POST /api/issues/{id}/fix/verify`（只验证不提交，UI 有「先验证」按钮）。

### 手机端（PWA）

`frontend/public/` 里有 manifest、service worker、图标。手机浏览器打开后
「添加到主屏幕」即可像 App 一样使用，支持：
- 静态资源缓存（二次打开秒开）
- 离线兜底页
- **API 请求不缓存**（issue 数据必须实时，缓存了看到过期状态更糟）

注意：service worker 只在 https 或 localhost 下生效，**局域网 http 访问不会注册**。

### 对话记忆

**记忆挂在「问题」上，不挂在 agent 上**。同一个 issue 的同一类操作共用一个 session，
换通道、换模型、隔几天再来，新模型先读历史就知道之前讨论过什么。

按操作类型隔离成四份，互不污染：

| kind | 用途 |
|---|---|
| `qualify` | 定性 |
| `triage` | 定级 |
| `analysis` | 分析 |
| `apply` | 改代码 |

为什么隔离：把「整理一段话」和几十轮改代码的工具调用混在一个上下文里，
既贵又干扰判断。

**存什么**：只存「提问 + 结论」的对话轮，**不存工具调用过程**。
过程又长又会过期（代码改了就失效），下次让模型重新调用工具拿最新内容更可靠。

**注入什么**：除了对话历史，还会拼一段「已知背景」（`build_memory_block`）：

- 已确认的问题描述（人工确认过，视为事实）
- 定级结论
- 上一轮分析结论（改代码时给，标注「可能与实际不符」）
- **历史修改记录**：实际根因、与方案的出入、当时发现的新问题、改过的文件
  → 末尾加一句「不要重复踩过的坑；如果判断与历史不同，请说明依据」

**裁剪**（`trim_messages`）：工具结果累积很容易撞上下文上限。

- 预算 60K 估算 token（字符数 / 2.5，中英混排偏保守）
- 永远保留 `system` + 第一条 `user`（原始任务）+ 最新对话
- 从最旧的「assistant + tool」对开始丢，**不拆散 tool_calls 与其结果**（拆了 API 会 400）
- 丢掉的位置插一条说明，让模型知道有历史被省略

**去重**：同一个工具 + 同样参数重复调用时，不重复回灌全文，只返回一句指代。
实测模型会反复 `read_file` 同一个文件确认，每次都塞 8K 字符纯属浪费。

接口：

```
GET    /api/issues/{id}/memory           查看各类记忆的调用次数/token
DELETE /api/issues/{id}/memory?kind=     清空（不传 kind 清全部）
```

前端在详情页右栏「准备」tab 底部展示，可单独清空某一类。

### API 通道的工具循环

纯 API 只能返回文本，没法读写文件。为了让它也能改代码，后端自己实现了
function calling 循环（`app/codetools.py`）：

```
用户问题 + tools 定义  →  模型返回 tool_calls
                          ↓ 执行（read/list/grep/write/edit）
                       结果回灌 → 模型继续 → … → 输出结论
```

工具：`list_dir`、`read_file`、`grep`，写入场景额外给 `write_file`、`edit_file`。
只读场景（定性/定级）**不注册写工具**，模型看不到也就不会尝试。

安全边界：
- 所有路径必须落在 worktree 内（`_safe_path`），越界直接拒绝
- 单次读取 40K 字符、grep 80 条上限，防上下文爆炸
- 不提供 shell / delete / move，改动只能由 git diff 呈现
- `max_rounds` 控制轮数，用完会标注「可能不完整」

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
data/issue-context/       每个 issue 一份「修复边界」Markdown
backend/app/data/         ip2region 离线 IP 库（11MB，随仓库走）
```

## 多用户与审计

鉴权默认**关闭**（单人本机用，后端视所有请求为 admin）。要多人一起用就在
「设置 → 其他代码设置」里打开登录，然后：

- **用户**：管理员在「设置 → 账号 → 用户管理」里建人、改密码、停用、删除。
  每人只看到自己的问题 / 项目 / 通道（`owner_id` 隔离，越权返 404 不返 403）。
- **IP 白名单**：一行一个，支持 CIDR。**每次请求**都校验，不只是登录时。
  挂 nginx 后必须把反代 IP 写进 `auth.trusted_proxies`，否则白名单拿到的是
  nginx 的 IP（`X-Forwarded-For` 只对可信反代采信，防伪造）。
- **登录记录**：成功 / 密码错误 / 用户不存在 / 已停用 / 被锁 / IP 不在白名单 /
  退出登录，全部落 `app_login_log`，带 IP、**归属地**、客户端 UA、时间。
  在「设置 → 账号 → 登录记录」里看，可按用户名 / IP / 归属地搜，按结果筛，可清空。
- **限流**：登录频率（IP 维度）、失败锁定（IP+用户名，默认 5 次锁 15 分钟）、
  通用 API 频率、重操作（改代码/分析/拉模型）每小时上限。阈值都在设置里。

归属地用自带的离线库 `backend/app/data/ip2region_v4.xdb`（11MB，ip2region，
Apache-2.0），解析器是纯标准库手写的（`backend/app/geoip.py`），不联网、不加依赖。
内网 IP 直接标「内网」「本机」。库缺失时归属地留空，不影响登录。

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

GET    /api/auth/mode                     要不要显示登录页
POST   /api/auth/login | /logout
GET    /api/auth/me
GET    /api/auth/users                    用户列表（管理员）
POST   /api/auth/users                    新建用户（管理员）
PATCH  /api/auth/users/{id}               改密码（自己或管理员）
POST   /api/auth/users/{id}/enabled       停用/启用（管理员）
DELETE /api/auth/users/{id}               删除（管理员，不能删自己）
GET    /api/auth/login-logs               登录记录，支持 keyword/result/username + 分页
DELETE /api/auth/login-logs               清空登录记录（管理员）
GET    /api/auth/rate/status              限流配置与当前锁定
POST   /api/auth/rate/unlock | /clear
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

- 甲方只读分享链接（带 token 的只读视图，让客户自己看进度）
- 登录记录导出 CSV
