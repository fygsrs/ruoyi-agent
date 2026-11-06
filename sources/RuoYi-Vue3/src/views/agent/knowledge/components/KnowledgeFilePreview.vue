<template>
  <el-dialog v-model="visible" :title="document.name" width="min(960px, 94vw)" append-to-body destroy-on-close @closed="closePreview">
    <div v-loading="loading" class="file-preview" aria-label="原文件预览">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template v-else-if="url">
        <img v-if="mediaType.startsWith('image/')" :src="url" :alt="document.name" class="preview-image" />
        <iframe v-else-if="mediaType === 'application/pdf'" :src="pdfUrl" :title="document.name" class="preview-pdf"></iframe>
        <pre v-else-if="text !== null" class="preview-text">{{ text }}</pre>
        <el-empty v-else description="此格式请下载原文件后查看" :image-size="80" />
      </template>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :icon="Download" :loading="downloading.has(document.document_id)" @click="download(document)">下载原文件</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onDeactivated, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { getKnowledgeDocumentFile, KnowledgeApiError } from '@/api/agent/knowledge'

const visible = ref(false)
const loading = ref(false)
const error = ref('')
const document = ref({ name: '', document_id: '', page: null })
const url = ref('')
const mediaType = ref('')
const text = ref(null)
const downloading = reactive(new Set())
const controllers = new Set()
const downloadUrls = new Map()
let previewController
const pdfUrl = computed(() => document.value.page ? `${url.value}#page=${document.value.page}` : url.value)

function closePreview() {
  previewController?.abort()
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''
  text.value = null
}

async function open(file) {
  closePreview()
  document.value = file
  visible.value = true
  loading.value = true
  error.value = ''
  const controller = new AbortController()
  previewController = controller
  controllers.add(controller)
  try {
    const blob = await getKnowledgeDocumentFile(file.document_id, controller.signal)
    if (controller.signal.aborted) return
    mediaType.value = blob.type
    if (blob.type.startsWith('text/')) text.value = await blob.text()
    if (controller.signal.aborted) return
    url.value = URL.createObjectURL(blob)
  } catch (cause) {
    if (controller.signal.aborted) return
    if (!(cause instanceof KnowledgeApiError)) throw cause
    error.value = cause.message
  } finally {
    controllers.delete(controller)
    if (previewController === controller) loading.value = false
  }
}

async function download(file) {
  const controller = new AbortController()
  controllers.add(controller)
  downloading.add(file.document_id)
  try {
    const blob = await getKnowledgeDocumentFile(file.document_id, controller.signal)
    if (controller.signal.aborted) return
    const downloadUrl = URL.createObjectURL(blob)
    const anchor = window.document.createElement('a')
    anchor.href = downloadUrl
    anchor.download = file.name
    anchor.click()
    const timer = window.setTimeout(() => {
      URL.revokeObjectURL(downloadUrl)
      downloadUrls.delete(downloadUrl)
    }, 1000)
    downloadUrls.set(downloadUrl, timer)
  } catch (cause) {
    if (controller.signal.aborted) return
    if (!(cause instanceof KnowledgeApiError)) throw cause
    ElMessage.error(cause.message)
  } finally {
    controllers.delete(controller)
    downloading.delete(file.document_id)
  }
}

function cleanup() {
  visible.value = false
  controllers.forEach(controller => controller.abort())
  closePreview()
  downloadUrls.forEach((timer, objectUrl) => {
    window.clearTimeout(timer)
    URL.revokeObjectURL(objectUrl)
  })
  downloadUrls.clear()
}

onBeforeUnmount(cleanup)
onDeactivated(cleanup)
defineExpose({ open, download, downloading })
</script>

<style scoped>
.file-preview { min-height: 180px; }
.preview-image { display: block; max-width: 100%; max-height: 65vh; margin: 0 auto; object-fit: contain; }
.preview-pdf { width: 100%; height: 65vh; border: 0; }
.preview-text { max-height: 65vh; margin: 0; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.8 monospace; }
</style>
