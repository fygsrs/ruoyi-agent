import { getToken } from '@/utils/auth'

export class KnowledgeApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'KnowledgeApiError'
    this.status = status
  }
}

async function errorMessage(response) {
  if (response.headers.get('content-type')?.includes('application/json')) {
    const { detail } = await response.json()
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(item => item.msg).join('；')
  }
  return `请求失败（HTTP ${response.status}）`
}

async function request(path, { method = 'GET', data, file, signal, blob = false } = {}) {
  const token = getToken()
  if (!token) throw new KnowledgeApiError('登录已失效，请重新登录', 401)
  const headers = { Authorization: `Bearer ${token}` }
  let body
  if (file) {
    body = new FormData()
    body.append('file', file)
  } else if (data !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(data)
  }
  let response
  try {
    response = await fetch(`/agent-api/knowledge${path}`, { method, headers, body, signal })
  } catch (error) {
    if (error instanceof TypeError) throw new KnowledgeApiError('无法连接知识库服务，请检查网络后重试')
    throw error
  }
  if (!response.ok) throw new KnowledgeApiError(await errorMessage(response), response.status)
  if (blob) return response.blob()
  if (response.status === 204) return
  return response.json()
}

export function listKnowledgeBases(signal) {
  return request('/bases', { signal })
}

export function createKnowledgeBase(data, signal) {
  return request('/bases', { method: 'POST', data, signal })
}

export function updateKnowledgeBase(kbId, data, signal) {
  return request(`/bases/${encodeURIComponent(kbId)}`, { method: 'PATCH', data, signal })
}

export function deleteKnowledgeBase(kbId, signal) {
  return request(`/bases/${encodeURIComponent(kbId)}`, { method: 'DELETE', signal })
}

export function listKnowledgeDocuments(kbId, query, signal) {
  const params = new URLSearchParams(query)
  return request(`/bases/${encodeURIComponent(kbId)}/documents?${params}`, { signal })
}

export function uploadKnowledgeDocument(kbId, file, signal) {
  return request(`/bases/${encodeURIComponent(kbId)}/documents`, { method: 'POST', file, signal })
}

export function reprocessKnowledgeDocument(documentId, signal) {
  return request(`/documents/${encodeURIComponent(documentId)}/reprocess`, { method: 'POST', signal })
}

export function deleteKnowledgeDocument(documentId, signal) {
  return request(`/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE', signal })
}

export function getKnowledgeDocumentFile(documentId, signal) {
  return request(`/documents/${encodeURIComponent(documentId)}/file`, { blob: true, signal })
}

export function getKnowledgeAsset(assetId, signal) {
  return request(`/assets/${encodeURIComponent(assetId)}`, { blob: true, signal })
}
