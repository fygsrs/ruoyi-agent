import { EventSourceParserStream } from 'eventsource-parser/stream'
import { getToken } from '@/utils/auth'

export class AgentChatError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'AgentChatError'
    this.status = status
  }
}

async function responseError(response) {
  if (response.headers.get('content-type')?.includes('application/json')) {
    const payload = await response.json()
    const detail = payload.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(item => item.msg).join('；')
  }
  return `请求失败（HTTP ${response.status}）`
}

function authHeaders() {
  const token = getToken()
  if (!token) throw new AgentChatError('登录已失效，请重新登录', 401)
  return { Authorization: `Bearer ${token}` }
}

async function getChatResource(path, signal) {
  const response = await fetch(`/agent-api${path}`, { headers: authHeaders(), signal })
  if (!response.ok) throw new AgentChatError(await responseError(response), response.status)
  return response.json()
}

export function listAgentThreads(signal) {
  return getChatResource('/chat', signal)
}

export function getAgentThread(threadId, signal) {
  return getChatResource(`/chat/${encodeURIComponent(threadId)}`, signal)
}

export async function deleteAgentThread(threadId, signal) {
  const response = await fetch(`/agent-api/chat/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
    signal
  })
  if (!response.ok) throw new AgentChatError(await responseError(response), response.status)
}

export function streamAgentChat(payload, handlers) {
  return streamChatResource('/chat', payload, handlers)
}

export function resumeAgentChat(payload, handlers) {
  return streamChatResource('/chat/resume', payload, handlers)
}

async function streamChatResource(path, payload, { signal, onDelta, onThread, onReview, onSources, onArtifact }) {
  const response = await fetch(`/agent-api${path}`, {
    method: 'POST',
    headers: {
      ...authHeaders(),
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    },
    body: JSON.stringify(payload),
    signal
  })

  if (!response.ok) throw new AgentChatError(await responseError(response), response.status)
  if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
    throw new AgentChatError('服务返回的不是流式响应，请稍后重试')
  }

  const reader = response.body
    .pipeThrough(new TextDecoderStream())
    .pipeThrough(new EventSourceParserStream({ onError: 'terminate' }))
    .getReader()

  try {
    while (true) {
      const { value: event, done } = await reader.read()
      if (done) throw new AgentChatError('连接已中断，请恢复会话查看已保存的状态')

      const data = JSON.parse(event.data)
      switch (event.event) {
        case 'thread':
          if (typeof data.thread_id !== 'string') throw new AgentChatError('服务返回了无效的会话编号')
          onThread(data.thread_id)
          break
        case 'delta':
          if (typeof data.text !== 'string') throw new AgentChatError('服务返回了无效的消息内容')
          onDelta(data.text)
          break
        case 'sources':
          if (!Array.isArray(data.items)) throw new AgentChatError('服务返回了无效的引用来源')
          onSources(data.items)
          break
        case 'artifact':
          if (data.type !== 'image_generation' || typeof data.job_id !== 'string') throw new AgentChatError('服务返回了无效的图片任务')
          onArtifact(data)
          break
        case 'review_required':
          if (typeof data.interrupt_id !== 'string' || data.kind !== 'user_review' || !['create', 'update', 'delete'].includes(data.operation)) {
            throw new AgentChatError('服务返回了无效的审核请求')
          }
          onReview(data)
          await reader.cancel()
          return
        case 'done':
          await reader.cancel()
          return
        case 'error':
          if (typeof data.message !== 'string') throw new AgentChatError('服务返回了无效的错误消息')
          throw new AgentChatError(data.message)
        default:
          throw new AgentChatError('服务返回了无法识别的消息事件')
      }
    }
  } finally {
    reader.releaseLock()
  }
}
