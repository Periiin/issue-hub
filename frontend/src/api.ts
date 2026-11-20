import axios from 'axios'

export const api = axios.create({ baseURL: '/api', timeout: 240000 })

/* ===== 鉴权 =====
 * token 存 localStorage，每个请求自动带 Authorization。
 * 401 时清掉 token 并跳登录页 —— 否则用户会看到一堆"加载失败"却不知道为什么。
 */
const TOKEN_KEY = 'ih_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

api.interceptors.request.use((cfg) => {
  const t = getToken()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401 && location.pathname !== '/login') {
      clearToken()
      location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export interface AuthUser {
  id: number
  username: string
  displayName: string
  role: 'admin' | 'user'
}

/** 用户列表里的完整记录（后端返回 snake_case + enabled/created_at） */
export interface AppUser extends AuthUser {
  display_name?: string
  enabled: boolean
  created_at?: string
}

export const getAuthMode = () =>
  api.get<{ enabled: boolean }>('/auth/mode').then((r) => r.data)

export const login = (username: string, password: string) =>
  api.post<{ token: string; user: AuthUser; expiresAt: string }>('/auth/login',
    { username, password }).then((r) => r.data)

export const logout = () => api.post('/auth/logout').then((r) => r.data)

/** 可选负责人（精简信息，普通用户也能拿到） */
export interface Assignee {
  username: string
  displayName: string
}

export const getAssignees = () =>
  api.get<{ users: Assignee[] }>('/auth/assignees').then((r) => r.data)

export const getMe = () =>
  api.get<{ user: AuthUser }>('/auth/me').then((r) => r.data)

export const listUsers = () =>
  api.get<{ users: AuthUser[] }>('/auth/users').then((r) => r.data)

export const createUser = (data: { username: string; password: string; display_name?: string; role?: string }) =>
  api.post('/auth/users', data).then((r) => r.data)

export const changePassword = (userId: number, password: string) =>
  api.patch(`/auth/users/${userId}`, { password }).then((r) => r.data)

export const toggleUser = (userId: number, enabled: boolean) =>
  api.post(`/auth/users/${userId}/enabled`, null, { params: { enabled } }).then((r) => r.data)

export const deleteUser = (userId: number) =>
  api.delete(`/auth/users/${userId}`).then((r) => r.data)

/** 一条登录记录 */
export interface LoginLog {
  id: number
  user_id: number | null
  username: string
  result: string
  resultLabel: string
  success: boolean
  ip: string
  ip_region: string
  user_agent: string
  note: string
  created_at: string
  display_name?: string | null
  role?: string | null
}

export const getLoginLogs = (params: {
  limit?: number; offset?: number; username?: string; result?: string; keyword?: string
} = {}) =>
  api.get<{ items: LoginLog[]; total: number; limit: number; offset: number }>(
    '/auth/login-logs', { params }).then((r) => r.data)

export const clearLoginLogs = () => api.delete('/auth/login-logs').then((r) => r.data)

export interface Issue {
  id: number
  title: string
  raw_text: string
  source: string
  reporter: string
  module: string
  status: string
  qualify_draft: any
  qualify_final: any
  triage: any
  severity: string | null
  complexity: string | null
  priority: string | null
  fix_plan: any
  /** 所属项目（决定默认代码范围与可改仓库） */
  project_id?: number | null
  created_at: string
  updated_at: string
}

export interface Attachment {
  id: number
  issue_id: number
  filename: string
  path: string
  mime: string
  size: number
}

export const listIssues = (params: Record<string, any>) =>
  api.get('/issues', { params }).then((r) => r.data)

/** 周报 Markdown 原文（days=0 表示本周） */
export const getWeeklyReport = (days = 0) =>
  api.get<string>('/report/weekly', { params: { days }, responseType: 'text' })
    .then((r) => (typeof r.data === 'string' ? r.data : String(r.data)))

/** 批量改：只传要改的字段 */
export const batchPatchIssues = (data: Record<string, any>) =>
  api.post('/issues/batch', data).then((r) => r.data)

export const batchDeleteIssues = (ids: number[]) =>
  api.post('/issues/batch/delete', { ids }).then((r) => r.data)

export interface IssueLink {
  id: number
  kind: string
  kindLabel: string
  target_id: number
  direction: 'in' | 'out'
  title: string
  status: string
  created_at: string
}

export const listLinks = (issueId: number) =>
  api.get<{ links: IssueLink[] }>(`/issues/${issueId}/links`).then((r) => r.data)

export const addLink = (issueId: number, otherId: number, kind = 'duplicate') =>
  api.post(`/issues/${issueId}/links`, { other_id: otherId, kind }).then((r) => r.data)

export const removeLink = (issueId: number, linkId: number) =>
  api.delete(`/issues/${issueId}/links/${linkId}`).then((r) => r.data)

export interface IssueComment {
  id: number
  author: string
  author_id: number | null
  body: string
  created_at: string
}

export const listComments = (issueId: number) =>
  api.get<{ comments: IssueComment[] }>(`/issues/${issueId}/comments`).then((r) => r.data)

export const addComment = (issueId: number, body: string) =>
  api.post<{ comment: IssueComment }>(`/issues/${issueId}/comments`, { body }).then((r) => r.data)

export const deleteComment = (issueId: number, commentId: number) =>
  api.delete(`/issues/${issueId}/comments/${commentId}`).then((r) => r.data)

export const createIssue = (data: Record<string, any>) =>
  api.post('/issues', data).then((r) => r.data)

export const getIssue = (id: number) =>
  api.get(`/issues/${id}`).then((r) => r.data)

export const patchIssue = (id: number, data: Record<string, any>) =>
  api.patch(`/issues/${id}`, data).then((r) => r.data)

export const deleteIssue = (id: number) =>
  api.delete(`/issues/${id}`).then((r) => r.data)

export const uploadAttachments = (id: number, files: File[]) => {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return api.post(`/issues/${id}/attachments`, form).then((r) => r.data)
}

export const deleteAttachment = (issueId: number, attachmentId: number) =>
  api.delete(`/issues/${issueId}/attachments/${attachmentId}`).then((r) => r.data)

export const runQualify = (id: number, channelId?: number | null) =>
  api.post(`/issues/${id}/qualify`, { channel_id: channelId }).then((r) => r.data)

export const confirmQualify = (id: number, data: Record<string, any>) =>
  api.post(`/issues/${id}/qualify/confirm`, data).then((r) => r.data)

export const runTriage = (id: number, channelId?: number | null) =>
  api.post(`/issues/${id}/triage`, { channel_id: channelId }).then((r) => r.data)

export const runFix = (id: number, channelId?: number | null) =>
  api.post(`/issues/${id}/fix`, { channel_id: channelId }).then((r) => r.data)

export const getSettings = () => api.get('/settings').then((r) => r.data)

export const saveSettings = (values: Record<string, any>) =>
  api.put('/settings', { values }).then((r) => r.data)

export const fileUrl = (path: string) => `/files/${path}`

// ---------- 操作解决（worktree） ----------

export interface CodeRoot {
  path: string
  name: string
  exists: boolean
  isGit: boolean
  repoRoot: string | null
}

/** 可做 worktree 的 git 仓库根（后端按 repoRoot 去重） */
export interface TargetRepo {
  path: string
  name: string
  exists: boolean
  isGit: boolean
  /** 该仓库覆盖的、已配置为代码范围的子目录 */
  covers: string[]
}

export const getCodeRoots = (projectId?: number | null) =>
  api.get<{ roots: CodeRoot[]; ignore: string[]; projectNotes: string; targetRepos: TargetRepo[] }>(
    '/code/roots', { params: projectId ? { project_id: projectId } : {} }
  ).then((r) => r.data)

/** 单个仓库的 worktree 状态（多仓库时 fix_state.repos 的每个值） */
export interface RepoFixState {
  repo: string
  name?: string
  worktree?: string
  branch?: string
  base_branch?: string
  base_commit?: string
  status?: 'changed' | 'unchanged' | 'failed'
  error?: string
  provider?: string
  duration_ms?: number
  summary?: string
  diff_stat?: string
  files?: string[]
  accepted?: boolean
  accepted_at?: string
  commit_message?: string
  merge?: { merged?: boolean; base_branch?: string; reason?: string; command?: string }
  updated_at?: string
}

export interface FixState {
  repos: Record<string, RepoFixState>
  context?: string
  updated_at?: string
}

export const applyFix = (id: number, data: { channel_id?: number | null; repos?: string[]; message?: string }) =>
  api.post<{ state: FixState; diffs: Record<string, any>; context: string }>(`/issues/${id}/fix/apply`, data)
    .then((r) => r.data)

export const getFixDiff = (id: number, repo?: string) =>
  api.get<{ state: FixState; diffs: Record<string, any> }>(`/issues/${id}/fix/diff`, { params: repo ? { repo } : {} })
    .then((r) => r.data)

export const acceptFix = (id: number, data: { repo?: string; message?: string; merge?: boolean }) =>
  api.post<{ ok: boolean; results: Record<string, any>; state: FixState }>(`/issues/${id}/fix/accept`, data)
    .then((r) => r.data)

export const rejectFix = (id: number, data: { repo?: string } = {}) =>
  api.post(`/issues/${id}/fix/reject`, data).then((r) => r.data)

// ---------- 修复上下文（边界文件） ----------

export const getFixContext = (id: number) =>
  api.get<{ text: string; path: string }>(`/issues/${id}/context`).then((r) => r.data)

export const saveFixContext = (id: number, text: string) =>
  api.put<{ ok: boolean; path: string }>(`/issues/${id}/context`, { text }).then((r) => r.data)

export const regenerateFixContext = (id: number) =>
  api.post<{ ok: boolean; text: string; path: string }>(`/issues/${id}/context/regenerate`).then((r) => r.data)

/** 一轮「开始修改」的归档：实际改的过程与方案的出入 */
export interface FixAttempt {
  seq: number
  provider?: string
  status?: 'changed' | 'unchanged' | 'failed' | 'partial'
  summary?: string
  actual_root_cause?: string
  deviations?: string[]
  found_issues?: string[]
  files?: string[]
  risks?: string[]
  verification?: string
  repos?: Record<string, { status?: string; error?: string; summary?: string; files?: string[]; deviations?: string[]; found_issues?: string[] }>
  created_at?: string
}

// ---------- 项目 ----------

/** Magpie 里的一个模型 */
export interface MagpieModel {
  id: string
  label: string
  contextLength: number
  tools: boolean
  vision: boolean
}

export interface MagpieDetect {
  found: boolean
  running: boolean
  baseUrl: string
  version: string
  models: MagpieModel[]
  error: string
}

export const detectMagpie = () =>
  api.get<MagpieDetect>('/channels/magpie/detect').then((r) => r.data)

export const importMagpieModels = (models: string[]) =>
  api.post<{ ok: boolean; created: string[]; skipped: string[]; baseUrl: string }>(
    '/channels/magpie/import', { models }).then((r) => r.data)

export interface Project {
  id: number
  name: string
  repos: string[]
  notes?: string
  ignored?: boolean
}

export interface ScanResult {
  roots: string[]
  scanned: number
  repos: { path: string; name: string; parent: string; root: string; depth: number }[]
  clusters: { key: string; name: string; repos: string[]; depth: number }[]
  created: { id: number; name: string; repos: string[] }[]
  suggestions: {
    reason: string
    projects: { name: string; key: string; repos: string[] }[]
    mergedName: string
    mergedRepos: string[]
  }[]
  projects: Project[]
  hint?: string
}

export const getProjects = () =>
  api.get<{ projects: Project[] }>('/projects').then((r) => r.data)

export const createProject = (data: { name: string; repos: string[]; notes?: string }) =>
  api.post<{ id: number; project: Project }>('/projects', data).then((r) => r.data)

export const updateProject = (id: number, data: Partial<Project>) =>
  api.patch<{ project: Project }>(`/projects/${id}`, data).then((r) => r.data)

export const deleteProject = (id: number) =>
  api.delete(`/projects/${id}`).then((r) => r.data)

export const mergeProjects = (target_id: number, source_id: number, name?: string) =>
  api.post<{ project: Project }>('/projects/merge', { target_id, source_id, name }).then((r) => r.data)

/** dry=true 只扫描不入库；dry=false 会把新候选项目写进库 */
export const scanRepos = (dry = true) =>
  api.get<ScanResult>('/code/scan', { params: { dry } }).then((r) => r.data)

// ---------- AI 通道 ----------

export interface Channel {
  id: number
  name: string
  kind: 'api' | 'agent' | 'mock'
  base_url?: string
  model?: string
  command?: string
  args?: string
  temperature?: number
  max_rounds?: number
  enabled: boolean
  hasKey: boolean
}

export const getChannels = () =>
  api.get<{ channels: Channel[] }>('/channels').then((r) => r.data)

export const createChannel = (data: Partial<Channel> & { api_key?: string }) =>
  api.post<{ id: number }>('/channels', data).then((r) => r.data)

export const updateChannel = (id: number, data: Partial<Channel> & { api_key?: string }) =>
  api.patch(`/channels/${id}`, data).then((r) => r.data)

export const deleteChannel = (id: number) =>
  api.delete(`/channels/${id}`).then((r) => r.data)

export const listChannelModels = (data: { base_url: string; api_key?: string; channel_id?: number }) =>
  api.post<{ models: string[] }>('/channels/models', data).then((r) => r.data)

export const testChannel = (id: number) =>
  api.post<{ ok: boolean; model: string; reply: string; durationMs: number }>(
    `/channels/${id}/test`, {}, { timeout: 180000 }
  ).then((r) => r.data)

// ---------- 对话记忆 ----------

export interface MemorySession {
  id: number
  kind: string
  kindLabel: string
  rounds: number
  turns: number
  tokens: number
  created_at: string
  updated_at: string
}

export const getMemory = (issueId: number) =>
  api.get<{ sessions: MemorySession[]; kinds: Record<string, string> }>(`/issues/${issueId}/memory`)
    .then((r) => r.data)

/** kind 为空表示清空全部 */
export const clearMemory = (issueId: number, kind = '') =>
  api.delete(`/issues/${issueId}/memory`, { params: kind ? { kind } : {} }).then((r) => r.data)

/** 只跑验证不提交：先看看能不能编译 */
export const verifyFix = (id: number, repo = '') =>
  api.post(`/issues/${id}/fix/verify`, {}, { params: repo ? { repo } : {}, timeout: 600000 })
    .then((r) => r.data)

// ---------- 用户仓库副本 ----------

export interface RepoCopy {
  path: string
  source: string
  exists: boolean
  isCopy: boolean
  head?: string
  branch?: string
  worktrees?: number
  dirty?: boolean
  sizeMb?: number
}

export const getRepoCopies = () =>
  api.get<{ copies: RepoCopy[]; totalMb: number; mode: 'copy' | 'shared' }>('/repos')
    .then((r) => r.data)

export const syncRepoCopy = (source: string) =>
  api.post(`/repos/sync`, null, { params: { source }, timeout: 300000 }).then((r) => r.data)

export const syncAllRepoCopies = () =>
  api.post('/repos/sync-all', null, { timeout: 600000 }).then((r) => r.data)

// ---------- 限流状态 ----------

export interface RateStatus {
  enabled: boolean
  loginPerIpPerMin: number
  failLimit: number
  failLockMinutes: number
  apiPerMin: number
  heavyPerHour: number
  locks: { lock_key: string; locked_until: string; reason?: string; active: boolean; remainSeconds: number }[]
}

export const getRateStatus = () =>
  api.get<RateStatus>('/auth/rate/status').then((r) => r.data)

export const unlockRate = (lockKey: string) =>
  api.post('/auth/rate/unlock', null, { params: { lock_key: lockKey } }).then((r) => r.data)

export const clearRate = () =>
  api.post('/auth/rate/clear').then((r) => r.data)
