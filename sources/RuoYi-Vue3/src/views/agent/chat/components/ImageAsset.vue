<template>
  <figure class="image-asset" :class="{ 'is-compact': compact }">
    <div v-loading="loading" class="asset-preview">
      <el-image v-if="url" :src="url" :preview-src-list="[url]" :alt="image.name" fit="contain" preview-teleported @load="emit('loaded')">
        <template #error><span class="asset-error">图片无法显示</span></template>
      </el-image>
      <div v-else-if="error" class="asset-error" role="alert"><span>{{ error }}</span><el-button link type="primary" @click="loadImage">重新加载</el-button></div>
      <span v-else class="asset-placeholder">正在加载图片</span>
    </div>
    <figcaption v-if="!compact" class="asset-caption">
      <span class="asset-name" :title="image.name">{{ image.name }}</span>
      <span class="asset-size">{{ image.width }} × {{ image.height }}</span>
    </figcaption>
    <div v-if="actions" class="asset-actions">
      <el-button link type="primary" :icon="Download" :disabled="!url" @click="download">下载图片</el-button>
      <el-button v-if="editable" link type="primary" :icon="EditPen" :disabled="disabled" @click="emit('edit', image)">基于此图修改</el-button>
    </div>
  </figure>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { Download, EditPen } from '@element-plus/icons-vue'
import { AgentChatError } from '@/api/agent/chat'
import { getAgentImage } from '@/api/agent/images'

const props = defineProps({
  image: { type: Object, required: true },
  actions: { type: Boolean, default: true },
  editable: Boolean,
  disabled: Boolean,
  compact: Boolean
})
const emit = defineEmits(['edit', 'loaded', 'error'])
const url = ref('')
const loading = ref(false)
const error = ref('')
let active = true
let request = null

function releaseImage() {
  request?.abort()
  request = null
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
  loading.value = false
}

async function loadImage() {
  if (!active || request || url.value) return
  const controller = new AbortController()
  request = controller
  loading.value = true
  error.value = ''
  try {
    const blob = await getAgentImage(props.image.image_id, controller.signal)
    if (controller.signal.aborted) return
    url.value = URL.createObjectURL(blob)
  } catch (cause) {
    if (controller.signal.aborted) return
    if (!(cause instanceof AgentChatError)) throw cause
    error.value = cause.message
    emit('error', cause)
  } finally {
    if (request === controller) {
      request = null
      loading.value = false
    }
  }
}

function download() {
  const anchor = document.createElement('a')
  anchor.href = url.value
  anchor.download = props.image.name
  anchor.click()
}

watch(() => props.image.image_id, () => {
  releaseImage()
  void loadImage()
}, { immediate: true })
onActivated(() => {
  active = true
  void loadImage()
})
onDeactivated(() => {
  active = false
  releaseImage()
})
onBeforeUnmount(releaseImage)
</script>

<style scoped>
.image-asset { width: min(100%, 420px); min-width: 0; margin: 0; white-space: normal; }
.asset-preview { display: grid; place-items: center; min-height: 140px; overflow: hidden; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.asset-preview .el-image { display: block; width: 100%; max-height: 420px; cursor: zoom-in; }
.asset-preview :deep(.el-image__inner) { max-height: 420px; }
.asset-placeholder, .asset-error { padding: 14px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; text-align: center; }
.asset-error { display: flex; flex-direction: column; align-items: center; gap: 6px; color: var(--el-color-danger); }
.asset-caption { display: flex; justify-content: space-between; gap: 12px; margin-top: 5px; color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.6; }
.asset-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-size { flex-shrink: 0; font-variant-numeric: tabular-nums; }
.asset-actions { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 5px; }
.asset-actions .el-button + .el-button { margin-left: 0; }
.is-compact { width: 92px; }
.is-compact .asset-preview { height: 76px; min-height: 76px; }
.is-compact .el-image, .is-compact :deep(.el-image__inner) { height: 76px; max-height: 76px; }
.is-compact .asset-placeholder, .is-compact .asset-error { padding: 5px; font-size: 10px; }
</style>
