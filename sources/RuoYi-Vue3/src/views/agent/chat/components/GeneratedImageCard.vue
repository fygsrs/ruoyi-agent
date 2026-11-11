<template>
  <section class="generated-image-card" aria-label="图片生成任务">
    <div class="job-heading"><el-icon><Picture /></el-icon><span>图片生成</span><span v-if="job" class="job-status" :class="`status-${job.status}`" role="status"><el-icon v-if="pending" class="is-loading"><Loading /></el-icon>{{ statusLabels[job.status] }}</span></div>
    <div v-if="error" class="job-error" role="alert"><span>{{ error }}</span><el-button link type="primary" @click="loadJob">刷新状态</el-button></div>
    <div v-else-if="!job" v-loading="true" class="job-loading">正在读取图片任务</div>
    <template v-else>
      <p class="job-prompt">{{ job.prompt }}</p>
      <template v-if="pending">
        <p class="job-note">图片生成需要一些时间，你可以继续聊天。</p>
        <div v-if="job.error" class="job-warning" role="status"><span>暂时无法更新结果，将继续查询。</span><p>{{ job.error }}</p></div>
      </template>
      <div v-else-if="job.status === 'uncertain'" class="job-warning" role="alert"><span>{{ job.error }}</span><p>暂时无法确认生成结果，请联系管理员在模型服务控制台核对任务。重新发送生成请求可能产生重复任务。</p></div>
      <p v-else-if="job.status === 'failed'" class="job-error" role="alert">{{ job.error }}</p>
      <div v-if="job.images.length" class="generated-images">
        <ImageAsset v-for="image in job.images" :key="image.image_id" :image="image" editable :disabled="disabled" @edit="emit('edit', $event)" @loaded="emit('change')" @error="emit('error', $event)" />
      </div>
      <span class="job-size">{{ job.size }}</span>
    </template>
  </section>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { Loading, Picture } from '@element-plus/icons-vue'
import { AgentChatError } from '@/api/agent/chat'
import { getImageJob } from '@/api/agent/images'
import ImageAsset from './ImageAsset.vue'

const props = defineProps({ jobId: { type: String, required: true }, disabled: Boolean })
const emit = defineEmits(['edit', 'change', 'error'])
const job = ref(null)
const error = ref('')
const statusLabels = { queued: '排队中', submitting: '正在提交', running: '正在生成', succeeded: '生成完成', failed: '生成失败', uncertain: '结果待确认' }
const pending = computed(() => job.value && ['queued', 'submitting', 'running'].includes(job.value.status))
let active = true
let request = null
let timer = null

function stopPolling() {
  window.clearTimeout(timer)
  timer = null
  request?.abort()
  request = null
}

async function loadJob() {
  if (!active || request) return
  window.clearTimeout(timer)
  const controller = new AbortController()
  request = controller
  error.value = ''
  try {
    const data = await getImageJob(props.jobId, controller.signal)
    if (controller.signal.aborted) return
    job.value = data
    emit('change')
    if (pending.value) timer = window.setTimeout(loadJob, 2500)
  } catch (cause) {
    if (controller.signal.aborted) return
    if (!(cause instanceof AgentChatError)) throw cause
    error.value = cause.message
    emit('error', cause)
    emit('change')
  } finally {
    if (request === controller) request = null
  }
}

watch(() => props.jobId, () => {
  stopPolling()
  job.value = null
  error.value = ''
  void loadJob()
}, { immediate: true })
onActivated(() => {
  active = true
  if (!job.value || pending.value) void loadJob()
})
onDeactivated(() => {
  active = false
  stopPolling()
})
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.generated-image-card { margin-top: 12px; padding: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); white-space: normal; }
.job-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; font-size: 13px; font-weight: 500; }
.job-heading > .el-icon { color: var(--el-color-primary); font-size: 17px; }
.job-status { display: inline-flex; align-items: center; gap: 4px; margin-left: auto; color: var(--el-text-color-secondary); font-size: 11px; font-weight: 400; }
.status-succeeded { color: var(--el-color-success); }
.status-failed { color: var(--el-color-danger); }
.status-uncertain { color: var(--el-color-warning-dark-2); }
.job-prompt { margin: 10px 0 0; font-size: 12px; line-height: 1.8; white-space: pre-wrap; }
.job-note, .job-loading { margin: 7px 0 0; color: var(--el-text-color-secondary); font-size: 12px; }
.job-loading { min-height: 65px; padding-top: 22px; text-align: center; }
.job-error { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 10px 0 0; color: var(--el-color-danger); font-size: 12px; line-height: 1.7; }
.job-warning { margin-top: 10px; padding: 10px; border-radius: 5px; color: var(--el-color-warning-dark-2); background: var(--el-color-warning-light-9); font-size: 12px; line-height: 1.7; }
.job-warning p { margin: 5px 0; }
.generated-images { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; }
.job-size { display: block; margin-top: 8px; color: var(--el-text-color-placeholder); font-size: 10px; }
</style>
