import { getToken } from '@/utils/auth'
import { AgentChatError } from './chat'

async function requestImageResource(path, { file, signal, blob = false } = {}) {
  const token = getToken()
  if (!token) throw new AgentChatError('登录已失效，请重新登录', 401)
  let body
  if (file) {
    body = new FormData()
    body.append('file', file)
  }
  let response
  try {
    response = await fetch(`/agent-api${path}`, {
      method: file ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token}` },
      body,
      signal
    })
  } catch (error) {
    if (error instanceof TypeError) throw new AgentChatError('无法连接图片服务，请检查网络后重试')
    throw error
  }
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    if (response.headers.get('content-type')?.includes('application/json')) {
      const { detail } = await response.json()
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail)) message = detail.map(item => item.msg).join('；')
    }
    throw new AgentChatError(message, response.status)
  }
  return blob ? response.blob() : response.json()
}

export function uploadAgentImage(threadId, file, signal) {
  return requestImageResource(`/chat/${encodeURIComponent(threadId)}/images`, { file, signal })
}

export function getImageJob(jobId, signal) {
  return requestImageResource(`/image-jobs/${encodeURIComponent(jobId)}`, { signal })
}

export function getAgentImage(imageId, signal) {
  return requestImageResource(`/images/${encodeURIComponent(imageId)}`, { blob: true, signal })
}
