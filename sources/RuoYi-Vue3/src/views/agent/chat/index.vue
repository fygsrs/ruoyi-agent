<template>
  <div class="agent-page">
    <div class="chat-shell" @keydown.esc="closeSidebar">
      <button v-if="sidebarOpen" class="sidebar-backdrop" aria-label="关闭会话列表" @click="closeSidebar"></button>
      <aside id="agent-conversation-sidebar" ref="sidebarRef" class="conversation-sidebar" :class="{ 'is-open': sidebarOpen }" aria-label="会话列表" @keydown.tab="onSidebarTab">
        <div class="sidebar-header">
          <div class="sidebar-heading"><h2>会话记录</h2><span>{{ threads.length }}</span></div>
          <el-button ref="sidebarCloseRef" class="sidebar-close" text :icon="Close" aria-label="关闭会话列表" @click="closeSidebar" />
        </div>
        <div class="new-conversation-wrap">
          <el-button class="new-conversation-button" :icon="Plus" :disabled="isBusy" type="primary" plain @click="startNewConversation">新对话</el-button>
        </div>
        <nav class="conversation-list" aria-label="历史会话">
          <div v-for="group in conversationGroups" :key="group.label" class="conversation-group">
            <h3>{{ group.label }}</h3>
            <div v-for="thread in group.items" :key="thread.thread_id" class="conversation-item" :class="{ 'is-active': thread.thread_id === threadId }">
              <button class="thread-open" :disabled="isBusy" :aria-current="thread.thread_id === threadId ? 'true' : undefined" :title="thread.title" @click="openConversation(thread.thread_id)">
                <el-icon class="thread-symbol" aria-hidden="true"><ChatDotRound /></el-icon>
                <span class="thread-info"><span class="thread-title">{{ thread.title }}</span><time :datetime="thread.updated_at" class="thread-date">{{ formatDate(thread.updated_at) }}</time></span>
              </button>
              <el-button class="thread-delete" text :icon="Delete" :loading="deletingThreadId === thread.thread_id" :disabled="isBusy" :aria-label="`删除会话：${thread.title}`" :title="`删除会话：${thread.title}`" @click="confirmRemoveConversation(thread)" />
            </div>
          </div>
          <div v-if="!threads.length" class="empty-conversations"><el-icon aria-hidden="true"><ChatDotRound /></el-icon><p>还没有会话记录</p><span>新对话会自动保存在这里</span></div>
        </nav>
        <div class="sidebar-footer"><el-icon aria-hidden="true"><CircleCheck /></el-icon><span>会话保存在服务端，可随时继续</span></div>
      </aside>

      <section v-loading="isLoading" class="chat-panel" :aria-busy="isBusy">
        <header class="chat-header">
          <div class="assistant-heading">
            <el-button ref="sidebarToggleRef" class="sidebar-toggle" text :icon="Expand" aria-label="打开会话列表" aria-controls="agent-conversation-sidebar" :aria-expanded="sidebarOpen" @click="openSidebar" />
            <div class="assistant-mark" aria-hidden="true"><el-icon><ChatDotRound /></el-icon></div>
            <div class="heading-copy"><h1>AI 助手</h1><p>{{ currentConversationTitle }}</p></div>
          </div>
          <div class="header-status"><span></span>执行前由你审核</div>
        </header>
        <el-alert v-if="loadError || needsRecovery" :title="loadError || '连接已停止或中断，请恢复会话确认已保存的消息和审核状态。'" type="warning" :closable="false" show-icon class="connection-alert">
          <el-button text type="primary" :disabled="isBusy" @click="recoverConversation">恢复会话</el-button>
        </el-alert>
        <div class="conversation-wrapper">
          <div ref="conversationRef" class="conversation" role="log" aria-label="与 AI 助手的对话" @scroll="onScroll">
            <div class="conversation-content" :class="{ 'is-empty': !messages.length && !review }">
              <div v-if="!messages.length && !review && !isLoading" class="conversation-empty">
                <div class="empty-mark" aria-hidden="true"><el-icon><ChatDotRound /></el-icon></div>
                <h2>今天有什么可以帮你？</h2>
                <p>查询知识库、分析数据、生成图片或管理用户。</p>
                <el-button v-if="!threadId" type="primary" :icon="Plus" :disabled="isBusy" @click="startNewConversation">开始新对话</el-button>
              </div>
              <template v-for="message in messages" :key="message.id">
                <article v-if="message.role === 'user' || message.content || message.artifacts?.length || message.status !== 'complete'" class="message-row" :class="message.role === 'user' ? 'user-message' : 'assistant-message'">
                  <div v-if="message.role === 'assistant'" class="message-avatar assistant-avatar" aria-hidden="true"><el-icon><ChatDotRound /></el-icon></div>
                  <div class="message-body">
                    <div class="message-author">{{ message.role === 'user' ? displayName : 'AI 助手' }}</div>
                    <div class="message-bubble" :class="[message.role === 'user' ? 'user-bubble' : 'assistant-bubble', { 'incomplete-bubble': message.status === 'error' }]">
                      <div v-if="message.content" class="message-text">{{ message.content }}<span v-if="message.status === 'streaming'" class="stream-cursor" aria-hidden="true"></span></div>
                      <div v-if="message.images?.length" class="message-images">
                        <ImageAsset v-for="image in message.images" :key="image.image_id" :image="image" editable :disabled="imageSelectionDisabled" @edit="useReferenceImage" @loaded="onImageLayout" @error="handleImageError" />
                      </div>
                      <GeneratedImageCard v-for="artifact in message.artifacts" :key="artifact.job_id" :job-id="artifact.job_id" :disabled="imageSelectionDisabled" @edit="useReferenceImage" @change="onImageLayout" @error="handleImageError" />
                      <KnowledgeSources v-if="message.sources?.length" :sources="message.sources" />
                      <div v-if="message.status === 'streaming' && !message.content && !message.artifacts?.length && !message.sources?.length" class="thinking"><span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>正在处理</div>
                      <div v-if="message.status === 'error'" class="message-feedback error-feedback" role="alert"><el-icon><WarningFilled /></el-icon><span>{{ message.error }}</span></div>
                      <div v-if="message.status === 'stopped'" class="message-feedback stopped-feedback"><span class="stopped-dot"></span><span>已停止接收，请恢复会话查看保存状态</span></div>
                    </div>
                    <div v-if="showSuggestedQuestions && message.role === 'assistant' && message.status === 'complete' && message.id === messages.at(-1).id" class="suggested-questions">
                      <div class="suggestions-heading">想先体验哪项功能？<span>点击直接发送</span></div>
                      <div class="suggestion-list">
                        <button v-for="question in suggestedQuestions" :key="question.title" type="button" class="suggestion-button" :disabled="imageSelectionDisabled" @click="sendMessage(question.prompt)">
                          <span class="suggestion-title"><el-icon aria-hidden="true"><component :is="question.icon" /></el-icon>{{ question.title }}</span>
                          <span class="suggestion-prompt">{{ question.prompt }}</span>
                        </button>
                      </div>
                    </div>
                  </div>
                  <div v-if="message.role === 'user'" class="message-avatar user-avatar" aria-hidden="true"><el-icon><User /></el-icon></div>
                </article>
              </template>
              <UserReviewCard v-if="review" :key="review.interrupt_id" :review="review" :busy="isBusy || needsRecovery" @submit="submitReview" />
            </div>
          </div>
          <el-button v-if="!followLatest" class="latest-button" round :icon="ArrowDown" @click="jumpToLatest">回到最新消息</el-button>
        </div>
        <div class="composer-area">
          <div v-if="review" class="pending-review-note"><el-icon><WarningFilled /></el-icon>当前操作等待审核，请填写上方表单，或发送修改要求。</div>
          <div class="composer">
            <div v-if="selectedImages.length" class="composer-references">
              <div class="reference-heading">参考图片 {{ selectedImages.length }} / {{ MAX_REFERENCE_IMAGES }}<span>请在下方说明生成或修改要求</span></div>
              <div class="reference-images">
                <div v-for="image in selectedImages" :key="image.image_id" class="reference-image">
                  <ImageAsset :image="image" :actions="false" compact @error="handleImageError" />
                  <el-button class="reference-remove" circle size="small" :icon="Close" :disabled="isBusy" :aria-label="`移除参考图：${image.name}`" @click="removeReferenceImage(image.image_id)" />
                </div>
              </div>
            </div>
            <el-input ref="inputRef" v-model="draft" type="textarea" :autosize="{ minRows: 1, maxRows: 5 }"
              :maxlength="MAX_MESSAGE_LENGTH" :disabled="!!review || isLoading || needsRecovery || !threadId" :placeholder="review ? '请先处理待审核操作' : !threadId ? '开始新对话后，向助手发送消息' : '描述你的需求，例如创建用户、查询知识库，或生成和修改图片…'" aria-label="聊天消息" resize="none" @keydown="onInputKeydown" />
            <div class="composer-toolbar">
              <div class="composer-tools">
                <input ref="imageInputRef" class="image-file-input" type="file" accept="image/jpeg,image/png,image/webp" multiple @change="onImagesSelected" />
                <el-button class="attach-button" text size="small" :icon="Picture" :loading="isUploading" :disabled="imageSelectionDisabled || selectedImages.length >= MAX_REFERENCE_IMAGES" title="最多 3 张参考图，支持 JPG、PNG、WEBP，单张不超过 10MB" @click="imageInputRef.click()">{{ isUploading ? '上传中' : '参考图' }}</el-button>
                <div class="keyboard-hint">Enter 发送<span>·</span>Shift + Enter 换行</div>
              </div>
              <div class="composer-actions">
                <span v-if="draft.length" class="character-count" :class="{ 'near-limit': draft.length > 7500 }">{{ draft.length }} / {{ MAX_MESSAGE_LENGTH }}</span>
                <el-button v-if="isStreaming" class="stop-button" size="small" :icon="VideoPause" @click="stop">停止接收</el-button>
                <el-button v-else class="send-button" size="small" type="primary" :icon="Position" :disabled="!draft.trim() || !!review || isBusy || needsRecovery || !threadId" @click="sendDraft">发送</el-button>
              </div>
            </div>
          </div>
          <div class="composer-note"><span class="session-note">对话和待审核操作自动保存</span><span v-if="isStreaming" class="generation-status" role="status"><span></span>正在处理</span><span v-else-if="review">等待你的审核</span><span v-else>AI 生成的内容请仔细核对</span></div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup name="AgentChat">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ArrowDown, ChatDotRound, CircleCheck, Close, Delete, Expand, Picture, Plus, Position, Reading, User, VideoPause, WarningFilled } from '@element-plus/icons-vue'
import { MAX_MESSAGE_LENGTH, MAX_REFERENCE_IMAGES, useAgentChat } from '@/composables/useAgentChat'
import UserReviewCard from './components/UserReviewCard.vue'
import KnowledgeSources from './components/KnowledgeSources.vue'
import GeneratedImageCard from './components/GeneratedImageCard.vue'
import ImageAsset from './components/ImageAsset.vue'

const { messages, threads, threadId, review, isStreaming, isLoading, isUploading, selectedImages, isBusy, needsRecovery, loadError, displayName, deletingThreadId,
  send, stop, uploadImages, addReferenceImage, removeReferenceImage, handleImageError, submitReview, newConversation, selectConversation, recoverConversation, removeConversation } = useAgentChat()
const draft = ref('')
const inputRef = ref(null)
const imageInputRef = ref(null)
const conversationRef = ref(null)
const followLatest = ref(true)
const sidebarOpen = ref(false)
const sidebarRef = ref(null)
const sidebarToggleRef = ref(null)
const sidebarCloseRef = ref(null)
const imageSelectionDisabled = computed(() => isBusy.value || !!review.value || needsRecovery.value || !threadId.value)
const suggestedQuestions = [
  { title: '新增用户', icon: User, prompt: '新增一个用户，账号 demo001，昵称“演示用户”' },
  { title: '知识库问答', icon: Reading, prompt: '帮我查一下员工手册里的请假流程' },
  { title: '生成图片', icon: Picture, prompt: '生成一张清晨海边日出的写实照片' }
]
const showSuggestedQuestions = computed(() => !messages.value.some(message => message.role === 'user') && !selectedImages.value.length && !loadError.value && !needsRecovery.value)

const currentConversationTitle = computed(() => {
  const current = threads.value.find(thread => thread.thread_id === threadId.value)
  return current ? current.title : threadId.value ? '新对话' : '对话管理用户，让工作更简单'
})

const conversationGroups = computed(() => {
  const today = new Date().setHours(0, 0, 0, 0)
  const yesterday = today - 86400000
  const lastWeek = today - 6 * 86400000
  const groups = [
    { label: '今天', items: [] },
    { label: '昨天', items: [] },
    { label: '近 7 天', items: [] },
    { label: '更早', items: [] }
  ]
  for (const thread of threads.value) {
    const updatedAt = new Date(thread.updated_at).getTime()
    const groupIndex = updatedAt >= today ? 0 : updatedAt >= yesterday ? 1 : updatedAt >= lastWeek ? 2 : 3
    groups[groupIndex].items.push(thread)
  }
  return groups.filter(group => group.items.length)
})

function formatDate(value) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function onScroll() {
  const element = conversationRef.value
  followLatest.value = element.scrollHeight - element.scrollTop - element.clientHeight < 80
}

async function jumpToLatest() {
  followLatest.value = true
  await nextTick()
  conversationRef.value?.scrollTo({ top: conversationRef.value.scrollHeight })
}

watch([messages, review], async () => {
  if (followLatest.value) await jumpToLatest()
}, { deep: true })

function onImageLayout() {
  if (followLatest.value) void jumpToLatest()
}

function onImagesSelected(event) {
  const files = Array.from(event.target.files)
  event.target.value = ''
  void uploadImages(files)
}

function useReferenceImage(image) {
  if (addReferenceImage(image)) inputRef.value?.focus()
}

async function openSidebar() {
  sidebarOpen.value = true
  await nextTick()
  sidebarCloseRef.value.$el.focus()
}

function onSidebarTab(event) {
  if (!sidebarOpen.value || !window.matchMedia('(max-width: 767px)').matches) return
  const buttons = sidebarRef.value.querySelectorAll('button:not(:disabled)')
  const first = buttons[0]
  const last = buttons[buttons.length - 1]
  if (event.shiftKey && event.target === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && event.target === last) {
    event.preventDefault()
    first.focus()
  }
}

function closeSidebar() {
  if (!sidebarOpen.value) return
  sidebarOpen.value = false
  sidebarToggleRef.value?.$el.focus()
}

async function openConversation(id) {
  draft.value = ''
  followLatest.value = true
  closeSidebar()
  await selectConversation(id)
  await jumpToLatest()
}

async function confirmRemoveConversation(thread) {
  try {
    await ElMessageBox.confirm(`确定删除“${thread.title}”吗？删除后无法恢复。`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger',
      distinguishCancelAndClose: true
    })
  } catch (action) {
    if (action === 'cancel' || action === 'close') return
    throw action
  }
  const wasCurrent = thread.thread_id === threadId.value
  const removed = await removeConversation(thread.thread_id)
  if (removed && wasCurrent) {
    draft.value = ''
    await jumpToLatest()
  }
}

function sendDraft() {
  sendMessage(draft.value)
}

function sendMessage(text) {
  if (send(text)) {
    draft.value = ''
    void jumpToLatest()
    inputRef.value?.focus()
  }
}

function onInputKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    sendDraft()
  }
}

function startNewConversation() {
  draft.value = ''
  followLatest.value = true
  closeSidebar()
  newConversation()
  inputRef.value?.focus()
}
</script>

<style scoped lang="scss">
.agent-page { height: calc(100dvh - 120px); min-height: 420px; padding: 12px 16px; color: var(--el-text-color-primary); }
.chat-shell { position: relative; display: flex; height: 100%; overflow: hidden; border: 1px solid var(--el-border-color-lighter); border-radius: 12px; background: var(--el-bg-color); box-shadow: 0 4px 22px rgb(30 52 82 / 3%); }
.conversation-sidebar { display: flex; flex: 0 0 240px; flex-direction: column; min-width: 0; background: #f7f9fc; border-right: 1px solid var(--el-border-color-lighter); }
.sidebar-header { display: flex; align-items: center; justify-content: space-between; height: 53px; padding: 0 18px; }
.sidebar-heading { display: flex; align-items: center; gap: 8px; }
.sidebar-heading h2 { margin: 0; font-size: 13px; font-weight: 600; letter-spacing: .5px; }
.sidebar-heading > span { min-width: 20px; padding: 1px 5px; border: 1px solid var(--el-border-color-lighter); border-radius: 5px; color: var(--el-text-color-secondary); background: var(--el-bg-color); font-size: 10px; line-height: 15px; text-align: center; font-variant-numeric: tabular-nums; }
.new-conversation-wrap { padding: 0 14px 14px; }
.new-conversation-button { width: 100%; height: 35px; border-radius: 8px; font-weight: 500; }
.conversation-list { flex: 1; min-height: 0; overflow-y: auto; padding: 0 8px 14px; scrollbar-width: thin; }
.conversation-group + .conversation-group { margin-top: 16px; }
.conversation-group h3 { margin: 0 10px 7px; color: var(--el-text-color-placeholder); font-size: 11px; font-weight: 400; line-height: 18px; }
.conversation-item { position: relative; display: flex; align-items: center; margin-bottom: 4px; border: 1px solid transparent; border-radius: 8px; transition: background .18s, border-color .18s; }
.conversation-item:hover { background: var(--el-bg-color); }
.conversation-item.is-active { border-color: var(--el-color-primary-light-8); background: var(--el-color-primary-light-9); }
.thread-open { display: flex; flex: 1; align-items: flex-start; gap: 9px; min-width: 0; padding: 11px 34px 10px 10px; border: 0; border-radius: 7px; background: transparent; color: inherit; text-align: left; cursor: pointer; font-family: inherit; }
.thread-open:disabled { cursor: not-allowed; }
.thread-open:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.thread-symbol { flex-shrink: 0; margin-top: 2px; color: var(--el-text-color-placeholder); font-size: 15px; }
.thread-info { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.thread-title { overflow: hidden; color: var(--el-text-color-regular); font-size: 13px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.thread-date { color: var(--el-text-color-placeholder); font-size: 10px; line-height: 14px; font-variant-numeric: tabular-nums; }
.is-active .thread-symbol, .is-active .thread-title { color: var(--el-color-primary); }
.is-active .thread-title { font-weight: 500; }
.thread-delete { position: absolute; top: 8px; right: 4px; width: 27px; height: 27px; padding: 0; border-radius: 6px; color: var(--el-text-color-placeholder); opacity: 0; transition: color .18s, opacity .18s; }
.conversation-item:hover .thread-delete, .conversation-item:focus-within .thread-delete, .is-active .thread-delete, .thread-delete.is-loading { opacity: 1; }
.thread-delete:not(.is-disabled):hover { color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.empty-conversations { padding: 42px 10px; color: var(--el-text-color-placeholder); text-align: center; }
.empty-conversations > .el-icon { font-size: 25px; opacity: .65; }
.empty-conversations p { margin: 12px 0 7px; color: var(--el-text-color-secondary); font-size: 12px; }
.empty-conversations > span { font-size: 11px; }
.sidebar-footer { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin: 0 16px; padding: 14px 0; border-top: 1px solid var(--el-border-color-lighter); color: var(--el-text-color-placeholder); font-size: 10px; }
.sidebar-footer .el-icon { font-size: 12px; }
.sidebar-backdrop, .sidebar-toggle, .sidebar-close { display: none; }
.chat-panel { display: flex; flex: 1; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; }
.chat-header { display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; gap: 16px; min-height: 62px; padding: 10px 24px; border-bottom: 1px solid var(--el-border-color-extra-light); }
.assistant-heading { display: flex; align-items: center; gap: 10px; min-width: 0; }
.assistant-mark { display: grid; place-items: center; width: 34px; height: 34px; flex-shrink: 0; color: var(--el-color-primary); background: var(--el-color-primary-light-9); border: 1px solid var(--el-color-primary-light-8); border-radius: 10px; font-size: 20px; }
.heading-copy { min-width: 0; }
.heading-copy h1 { margin: 0; font-size: 15px; font-weight: 600; line-height: 20px; }
.heading-copy p { overflow: hidden; max-width: 480px; margin: 3px 0 0; color: var(--el-text-color-secondary); font-size: 11px; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.header-status { display: flex; align-items: center; gap: 6px; flex-shrink: 0; color: var(--el-text-color-secondary); font-size: 11px; }
.header-status > span { width: 5px; height: 5px; border-radius: 50%; background: var(--el-color-success); }
.connection-alert { flex-shrink: 0; padding: 8px 20px; border-radius: 0; }
.connection-alert :deep(.el-alert__content) { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; }
.connection-alert :deep(.el-alert__title) { font-size: 12px; }
.connection-alert :deep(.el-alert__description) { margin: 0; }
.pending-review-note { display: flex; align-items: center; gap: 7px; margin: 0 auto 8px; color: var(--el-color-warning-dark-2); font-size: 12px; line-height: 18px; }
.conversation-wrapper { position: relative; flex: 1; min-height: 0; }
.conversation { height: 100%; overflow-y: auto; overscroll-behavior: contain; scroll-behavior: auto; scrollbar-width: thin; }
.conversation-content { width: 100%; max-width: 1320px; margin: 0 auto; padding: 26px 36px 8px; }
.conversation-content.is-empty { display: flex; align-items: center; justify-content: center; min-height: 100%; }
.conversation-empty { padding: 28px 10px 48px; text-align: center; }
.empty-mark { display: grid; place-items: center; width: 58px; height: 58px; margin: 0 auto 20px; border: 1px solid var(--el-color-primary-light-8); border-radius: 18px; color: var(--el-color-primary); background: var(--el-color-primary-light-9); font-size: 30px; }
.conversation-empty h2 { margin: 0 0 12px; font-size: 22px; font-weight: 500; letter-spacing: .4px; }
.conversation-empty p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.8; }
.conversation-empty > .el-button { margin-top: 24px; border-radius: 8px; }
.message-row { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 25px; }
.message-avatar { display: grid; place-items: center; width: 30px; height: 30px; flex-shrink: 0; border-radius: 9px; font-size: 17px; }
.assistant-avatar { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.user-avatar { color: var(--el-text-color-secondary); background: var(--el-fill-color); }
.message-body { min-width: 0; max-width: calc(100% - 42px); }
.assistant-message .message-body { width: 100%; }
.message-author { margin: 0 0 6px 2px; color: var(--el-text-color-secondary); font-size: 11px; line-height: 16px; }
.message-bubble { padding: 12px 16px; border-radius: 10px; font-size: 14px; line-height: 1.85; overflow-wrap: anywhere; }
.assistant-bubble { border: 1px solid var(--el-border-color-extra-light); border-top-left-radius: 3px; background: #f8fafc; }
.message-text, .user-bubble { white-space: pre-wrap; }
.suggested-questions { margin-top: 16px; }
.suggestions-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-bottom: 10px; color: var(--el-text-color-secondary); font-size: 12px; }
.suggestions-heading > span { color: var(--el-text-color-placeholder); font-size: 11px; }
.suggestion-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.suggestion-button { display: flex; flex-direction: column; gap: 8px; min-width: 0; padding: 13px 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 9px; background: var(--el-bg-color); color: var(--el-text-color-primary); font: inherit; text-align: left; cursor: pointer; }
.suggestion-button:hover:not(:disabled) { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.suggestion-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.suggestion-button:disabled { cursor: not-allowed; opacity: .5; }
.suggestion-title { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 500; }
.suggestion-title .el-icon { color: var(--el-color-primary); font-size: 16px; }
.suggestion-prompt { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.message-images { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 10px; }
.user-message { justify-content: flex-end; }
.user-message .message-body { max-width: min(85%, 840px); }
.user-message .message-author { text-align: right; margin-right: 2px; }
.user-bubble { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border-top-right-radius: 3px; }
.stream-cursor { display: inline-block; height: 16px; width: 2px; margin-left: 4px; vertical-align: -2px; background: var(--el-color-primary); animation: cursor-blink 1s steps(2, start) infinite; }
.thinking { display: flex; align-items: center; gap: 10px; color: var(--el-text-color-secondary); font-size: 13px; padding: 2px 0; }
.thinking-dots { display: inline-flex; gap: 4px; }
.thinking-dots i { width: 4px; height: 4px; border-radius: 50%; background: var(--el-color-primary); animation: dot-pulse 1.3s ease-in-out infinite; }
.thinking-dots i:nth-child(2) { animation-delay: .16s; }
.thinking-dots i:nth-child(3) { animation-delay: .32s; }
.message-feedback { display: flex; align-items: flex-start; gap: 7px; font-size: 12px; line-height: 1.7; }
.message-text + .message-feedback { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter); }
.error-feedback { color: var(--el-color-danger); }
.error-feedback .el-icon { margin-top: 3px; flex-shrink: 0; }
.incomplete-bubble { border-color: var(--el-color-danger-light-8); }
.stopped-feedback { color: var(--el-text-color-secondary); }
.stopped-dot { width: 6px; height: 6px; background: var(--el-text-color-placeholder); margin-top: 7px; border-radius: 2px; flex-shrink: 0; }
.latest-button { position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%); height: 30px; box-shadow: 0 3px 15px rgb(0 0 0 / 8%); font-size: 12px; }
.composer-area { flex-shrink: 0; padding: 8px 28px 10px; }
.composer { margin: 0 auto; border: 1px solid var(--el-border-color); border-radius: 10px; background: var(--el-bg-color); transition: border-color .2s, box-shadow .2s; }
.composer:focus-within { border-color: var(--el-color-primary); box-shadow: 0 0 0 3px var(--el-color-primary-light-9); }
.composer-references { padding: 10px 13px 2px; }
.reference-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; margin-bottom: 8px; color: var(--el-text-color-secondary); font-size: 11px; }
.reference-heading > span { color: var(--el-text-color-placeholder); font-size: 10px; }
.reference-images { display: flex; gap: 10px; }
.reference-image { position: relative; }
.reference-remove { position: absolute; top: -5px; right: -5px; width: 21px; height: 21px; padding: 0; font-size: 11px; }
.image-file-input { display: none; }
.composer :deep(.el-textarea__inner) { padding: 10px 13px 4px; border: 0; box-shadow: none; background: transparent; color: var(--el-text-color-primary); font-size: 13px; line-height: 1.7; }
.composer :deep(.el-textarea.is-disabled .el-textarea__inner) { color: var(--el-text-color-disabled); }
.composer-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 3px 8px 7px 13px; }
.composer-tools { display: flex; align-items: center; gap: 12px; min-width: 0; }
.attach-button { flex-shrink: 0; margin-left: -7px; font-size: 11px; }
.keyboard-hint { color: var(--el-text-color-placeholder); font-size: 10px; }
.keyboard-hint span { padding: 0 5px; }
.composer-actions { display: flex; align-items: center; gap: 10px; }
.character-count { color: var(--el-text-color-placeholder); font-size: 10px; font-variant-numeric: tabular-nums; }
.near-limit { color: var(--el-color-warning); }
.send-button, .stop-button { min-width: 70px; height: 27px; border-radius: 6px; }
.composer-note { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 6px auto 0; color: var(--el-text-color-placeholder); font-size: 10px; line-height: 14px; }
.generation-status { display: flex; align-items: center; gap: 6px; color: var(--el-text-color-secondary); }
.generation-status > span { width: 5px; height: 5px; border-radius: 50%; background: var(--el-color-primary); animation: dot-pulse 1.3s ease-in-out infinite; }
@keyframes cursor-blink { to { opacity: 0; } }
@keyframes dot-pulse { 0%, 80%, 100% { opacity: .35; } 40% { opacity: 1; } }

@media (max-width: 1100px) {
  .conversation-sidebar { flex-basis: 220px; }
  .chat-header { padding-right: 20px; padding-left: 20px; }
  .conversation-content { padding-right: 24px; padding-left: 24px; }
  .composer-area { padding-right: 20px; padding-left: 20px; }
  .header-status { display: none; }
}

@media (max-width: 767px) {
  .agent-page { height: calc(100dvh - 144px); min-height: 380px; padding: 8px; }
  .chat-shell { border-radius: 10px; }
  .conversation-sidebar { position: absolute; z-index: 4; top: 0; bottom: 0; left: 0; width: min(280px, calc(100% - 48px)); box-shadow: 8px 0 24px rgb(30 52 82 / 8%); visibility: hidden; transform: translateX(-100%); transition: transform .2s, visibility .2s; }
  .conversation-sidebar.is-open { visibility: visible; transform: translateX(0); }
  .sidebar-backdrop { position: absolute; z-index: 3; inset: 0; display: block; width: 100%; padding: 0; border: 0; background: rgb(25 39 58 / 24%); cursor: pointer; }
  .sidebar-close, .sidebar-toggle { display: inline-flex; width: 28px; height: 28px; padding: 0; color: var(--el-text-color-secondary); }
  .sidebar-toggle { flex-shrink: 0; margin-right: 1px; font-size: 17px; }
  .thread-delete { opacity: 1; }
  .thread-open { padding-top: 12px; padding-bottom: 12px; }
  .chat-header { min-height: 58px; padding: 9px 12px; }
  .assistant-heading { gap: 8px; }
  .assistant-mark { width: 30px; height: 30px; border-radius: 9px; font-size: 18px; }
  .heading-copy h1 { font-size: 14px; }
  .heading-copy p { max-width: calc(100vw - 160px); font-size: 10px; }
  .connection-alert { padding: 7px 12px; }
  .conversation-content { padding: 20px 14px 5px; }
  .conversation-empty { padding-bottom: 28px; }
  .conversation-empty h2 { font-size: 19px; }
  .conversation-empty p { font-size: 12px; }
  .message-row { gap: 8px; margin-bottom: 22px; }
  .message-avatar { width: 26px; height: 26px; border-radius: 8px; font-size: 15px; }
  .message-body { max-width: calc(100% - 34px); }
  .user-message .message-body { max-width: calc(100% - 34px); }
  .message-bubble { padding: 10px 12px; font-size: 13px; }
  .suggestion-list { grid-template-columns: 1fr; gap: 8px; }
  .suggestion-button { gap: 5px; padding: 11px 12px; }
  .composer-area { padding: 7px 12px 8px; }
  .pending-review-note { font-size: 11px; }
  .keyboard-hint { display: none; }
  .composer-toolbar { gap: 8px; }
  .composer-tools { gap: 0; }
  .composer-actions { gap: 6px; }
  .character-count { font-size: 9px; }
  .composer-note { justify-content: center; font-size: 9px; }
  .session-note { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .stream-cursor, .thinking-dots i, .generation-status > span { animation: none; }
  .conversation-sidebar { transition: none; }
}
</style>
