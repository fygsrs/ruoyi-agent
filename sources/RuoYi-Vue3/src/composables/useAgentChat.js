import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AgentChatError, deleteAgentThread, getAgentThread, listAgentThreads, resumeAgentChat, streamAgentChat } from '@/api/agent/chat'
import { removeToken } from '@/utils/auth'
import useUserStore from '@/store/modules/user'

export const MAX_MESSAGE_LENGTH = 8000

export function useAgentChat() {
  const messages = ref([])
  const threads = ref([])
  const threadId = ref('')
  const review = ref(null)
  const isStreaming = ref(false)
  const isLoading = ref(false)
  const deletingThreadId = ref('')
  const needsRecovery = ref(false)
  const loadError = ref('')
  const userStore = useUserStore()
  const route = useRoute()
  const router = useRouter()
  let activeRequest = null
  let isActive = true

  const displayName = computed(() => userStore.nickName || userStore.name)
  const isBusy = computed(() => isStreaming.value || isLoading.value || !!deletingThreadId.value)
  const storageKey = computed(() => `ruoyi-agent.thread.${userStore.id}`)

  function rememberThread(id) {
    threadId.value = id
    localStorage.setItem(storageKey.value, id)
  }

  async function expireSession() {
    ElMessage.warning('登录已失效，请重新登录')
    const redirect = route.fullPath
    removeToken()
    userStore.$patch({ token: '', id: '', name: '', nickName: '', roles: [], permissions: [] })
    await router.replace({ path: '/login', query: { redirect } })
  }

  async function reportError(error) {
    if (error instanceof AgentChatError && error.status === 401) await expireSession()
    else ElMessage.error(error.message)
  }

  function restoreMessages(history) {
    messages.value = history.map(message => ({ ...message, id: crypto.randomUUID(), status: 'complete', error: '' }))
  }

  async function refreshThreads(signal) {
    const data = await listAgentThreads(signal)
    threads.value = data.threads
  }

  async function readThread(id, signal) {
    const data = await getAgentThread(id, signal)
    rememberThread(data.thread_id)
    restoreMessages(data.messages)
    review.value = data.review
    needsRecovery.value = false
  }

  async function selectConversation(id) {
    if (!isActive || isBusy.value) return
    const request = { controller: new AbortController() }
    activeRequest = request
    isLoading.value = true
    loadError.value = ''
    try {
      await readThread(id, request.controller.signal)
    } catch (error) {
      if (request.controller.signal.aborted) return
      loadError.value = error.message
      await reportError(error)
    } finally {
      if (activeRequest === request) {
        activeRequest = null
        isLoading.value = false
      }
    }
  }

  function clearConversation() {
    threadId.value = ''
    localStorage.removeItem(storageKey.value)
    messages.value = []
    review.value = null
    needsRecovery.value = false
    loadError.value = ''
  }

  async function removeConversation(id) {
    if (!isActive || isBusy.value) return false
    const request = { controller: new AbortController() }
    activeRequest = request
    deletingThreadId.value = id
    const wasCurrent = id === threadId.value
    try {
      await deleteAgentThread(id, request.controller.signal)
      threads.value = threads.value.filter(thread => thread.thread_id !== id)
      if (wasCurrent) clearConversation()
      ElMessage.success('会话已删除')
    } catch (error) {
      if (!request.controller.signal.aborted) await reportError(error)
      return false
    } finally {
      if (activeRequest === request) {
        activeRequest = null
        deletingThreadId.value = ''
      }
    }
    if (wasCurrent && threads.value.length && isActive) {
      await selectConversation(threads.value[0].thread_id)
    }
    return true
  }

  async function runStream(payload, mode = 'chat') {
    const reply = { id: crypto.randomUUID(), role: 'assistant', content: '', status: 'streaming', error: '' }
    messages.value.push(reply)
    const message = messages.value.at(-1)
    const request = { controller: new AbortController(), message }
    activeRequest = request
    isStreaming.value = true
    loadError.value = ''

    try {
      const stream = mode === 'resume' ? resumeAgentChat : streamAgentChat
      await stream(payload, {
        signal: request.controller.signal,
        onThread(id) {
          if (activeRequest === request) rememberThread(id)
        },
        onDelta(text) {
          if (activeRequest === request) message.content += text
        },
        onReview(data) {
          if (activeRequest === request) review.value = data
        },
        onSources(data) {
          if (activeRequest === request) message.sources = data
        }
      })
      if (activeRequest !== request) return
      message.status = 'complete'
      await readThread(threadId.value, request.controller.signal)
      await refreshThreads(request.controller.signal)
    } catch (error) {
      if (activeRequest !== request) return
      if (request.controller.signal.aborted) message.status = 'stopped'
      else {
        message.status = 'error'
        message.error = error.message
        needsRecovery.value = error.status !== 422
        request.controller.abort()
        if (error instanceof AgentChatError && error.status === 401) await expireSession()
      }
    } finally {
      if (activeRequest === request) {
        activeRequest = null
        isStreaming.value = false
      }
    }
  }

  function send(text) {
    const content = text.trim()
    if (!isActive || isBusy.value || needsRecovery.value || review.value || !threadId.value || !content) return false
    if (content.length > MAX_MESSAGE_LENGTH) {
      ElMessage.warning('消息不能超过 8000 字符')
      return false
    }
    messages.value.push({ id: crypto.randomUUID(), role: 'user', content, status: 'complete', error: '' })
    void runStream({ action: 'chat', thread_id: threadId.value, content })
    return true
  }

  function submitReview(decision) {
    if (!isActive || isBusy.value || needsRecovery.value || !review.value) return
    void runStream({ thread_id: threadId.value, interrupt_id: review.value.interrupt_id, ...decision }, 'resume')
  }

  function stop() {
    if (!activeRequest) return
    const request = activeRequest
    if (request.message) {
      request.message.status = 'stopped'
      needsRecovery.value = true
    }
    activeRequest = null
    isStreaming.value = false
    isLoading.value = false
    deletingThreadId.value = ''
    request.controller.abort()
  }

  function newConversation() {
    if (!isActive || isBusy.value) return
    clearConversation()
    void runStream({ action: 'greet' })
  }

  async function initialize() {
    const request = { controller: new AbortController() }
    activeRequest = request
    isLoading.value = true
    loadError.value = ''
    try {
      await refreshThreads(request.controller.signal)
      const savedId = localStorage.getItem(storageKey.value)
      if (savedId) {
        try {
          await readThread(savedId, request.controller.signal)
        } catch (error) {
          if (!(error instanceof AgentChatError) || error.status !== 404) throw error
          localStorage.removeItem(storageKey.value)
          ElMessage.info('原会话已不存在，已开始新对话')
        }
      }
    } catch (error) {
      if (request.controller.signal.aborted) return
      loadError.value = error.message
      await reportError(error)
    } finally {
      if (activeRequest === request) {
        activeRequest = null
        isLoading.value = false
        if (!threadId.value && !loadError.value && isActive) newConversation()
      }
    }
  }

  function recoverConversation() {
    if (threadId.value) void selectConversation(threadId.value)
    else void initialize()
  }

  function leavePage() {
    isActive = false
    stop()
  }

  onMounted(initialize)
  onActivated(() => { isActive = true })
  onDeactivated(leavePage)
  onBeforeUnmount(leavePage)

  return { messages, threads, threadId, review, isStreaming, isLoading, isBusy, deletingThreadId, needsRecovery, loadError, displayName,
    send, stop, submitReview, newConversation, selectConversation, removeConversation, recoverConversation }
}
