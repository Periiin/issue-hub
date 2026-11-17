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
