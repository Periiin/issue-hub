import axios from 'axios'

export const api = axios.create({ baseURL: '/api', timeout: 240000 })

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

export const runQualify = (id: number, provider?: string) =>
  api.post(`/issues/${id}/qualify`, { provider }).then((r) => r.data)

export const confirmQualify = (id: number, data: Record<string, any>) =>
  api.post(`/issues/${id}/qualify/confirm`, data).then((r) => r.data)

export const runTriage = (id: number, provider?: string) =>
  api.post(`/issues/${id}/triage`, { provider }).then((r) => r.data)

export const runFix = (id: number, provider?: string) =>
  api.post(`/issues/${id}/fix`, { provider }).then((r) => r.data)

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

export const getCodeRoots = () =>
  api.get<{ roots: CodeRoot[]; ignore: string[]; projectNotes: string; targetRepos: TargetRepo[] }>('/code/roots')
    .then((r) => r.data)

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

export const applyFix = (id: number, data: { provider?: string; repos?: string[]; message?: string }) =>
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
