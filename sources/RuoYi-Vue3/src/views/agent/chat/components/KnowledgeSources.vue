<template>
  <section v-if="sources.length" class="knowledge-sources" aria-label="知识库引用来源">
    <div class="sources-heading"><el-icon><Collection /></el-icon><span>引用来源</span><span class="source-count">{{ sources.length }}</span></div>
    <el-collapse v-model="expandedSources" @change="loadExpandedAssets">
      <el-collapse-item v-for="source in sources" :key="source.source_id" :name="source.source_id">
        <template #title>
          <span class="source-number">{{ source.source_id }}</span>
          <span class="source-title">{{ source.document_name }}</span>
          <span v-if="source.page" class="source-location">第 {{ source.page }} 页</span>
        </template>
        <div v-if="source.section" class="source-section">{{ source.section }}</div>
        <blockquote>{{ source.excerpt }}</blockquote>
        <div v-if="source.asset_ids.length" class="source-images">
          <div v-for="assetId in source.asset_ids" :key="assetId" class="source-image" v-loading="assets[assetId].status === 'loading'">
            <el-image v-if="assets[assetId].url" :src="assets[assetId].url" :preview-src-list="[assets[assetId].url]" :alt="`${source.document_name} 中的引用图片`" fit="contain" preview-teleported />
            <div v-else-if="assets[assetId].error" class="asset-error" role="alert"><span>{{ assets[assetId].error }}</span><el-button link type="primary" @click="loadAsset(assetId)">重试</el-button></div>
            <span v-else class="image-placeholder">正在加载引用图片</span>
          </div>
        </div>
        <div class="source-actions">
          <el-button link type="primary" :icon="Document" @click="viewSource(source)">查看原文件</el-button>
          <el-button link type="primary" :icon="Download" :loading="previewRef?.downloading.has(source.document_id)" @click="downloadSource(source)">下载原文件</el-button>
        </div>
      </el-collapse-item>
    </el-collapse>
    <KnowledgeFilePreview ref="previewRef" />
  </section>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { Collection, Document, Download } from '@element-plus/icons-vue'
import { getKnowledgeAsset, KnowledgeApiError } from '@/api/agent/knowledge'
import KnowledgeFilePreview from '@/views/agent/knowledge/components/KnowledgeFilePreview.vue'

const props = defineProps({ sources: { type: Array, required: true } })
const expandedSources = ref([])
const assets = ref({})
const previewRef = ref(null)
const controllers = new Set()
let active = true

function releaseAssets() {
  controllers.forEach(controller => controller.abort())
  controllers.clear()
  Object.values(assets.value).forEach(asset => {
    if (asset.url) URL.revokeObjectURL(asset.url)
  })
}

function initializeAssets() {
  releaseAssets()
  const ids = new Set(props.sources.flatMap(source => source.asset_ids))
  assets.value = Object.fromEntries([...ids].map(id => [id, { status: 'idle', url: '', error: '' }]))
  if (active) void loadExpandedAssets()
}

async function loadAsset(assetId) {
  const asset = assets.value[assetId]
  if (asset.status === 'loading' || asset.status === 'ready') return
  const controller = new AbortController()
  controllers.add(controller)
  asset.status = 'loading'
  asset.error = ''
  try {
    const blob = await getKnowledgeAsset(assetId, controller.signal)
    if (controller.signal.aborted) return
    asset.url = URL.createObjectURL(blob)
    asset.status = 'ready'
  } catch (error) {
    if (controller.signal.aborted) return
    if (!(error instanceof KnowledgeApiError)) throw error
    asset.status = 'failed'
    asset.error = error.message
  } finally {
    controllers.delete(controller)
  }
}

async function loadExpandedAssets() {
  const ids = new Set(props.sources.filter(source => expandedSources.value.includes(source.source_id)).flatMap(source => source.asset_ids))
  await Promise.all([...ids].map(loadAsset))
}

function originalFile(source) {
  return { document_id: source.document_id, name: source.document_name, page: source.page }
}

function viewSource(source) {
  void previewRef.value.open(originalFile(source))
}

function downloadSource(source) {
  void previewRef.value.download(originalFile(source))
}

watch(() => props.sources, initializeAssets, { immediate: true, deep: true })
onActivated(() => {
  active = true
  initializeAssets()
})
onDeactivated(() => {
  active = false
  releaseAssets()
})
onBeforeUnmount(releaseAssets)
</script>

<style scoped>
.knowledge-sources { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter); }
.sources-heading { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; color: var(--el-text-color-secondary); font-size: 12px; }
.source-count { padding: 0 5px; border-radius: 4px; background: var(--el-fill-color); font-size: 10px; }
.knowledge-sources :deep(.el-collapse) { border-top: 0; border-bottom: 0; }
.knowledge-sources :deep(.el-collapse-item__header) { min-height: 36px; height: auto; gap: 7px; border-bottom-color: var(--el-border-color-extra-light); background: transparent; font-size: 12px; line-height: 1.6; }
.knowledge-sources :deep(.el-collapse-item__wrap) { background: transparent; border-bottom-color: var(--el-border-color-extra-light); }
.knowledge-sources :deep(.el-collapse-item__content) { padding: 9px 0 12px; }
.source-number { display: inline-grid; place-items: center; flex-shrink: 0; width: 19px; height: 19px; border-radius: 4px; background: var(--el-color-primary-light-9); color: var(--el-color-primary); font-size: 10px; }
.source-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-location { flex-shrink: 0; color: var(--el-text-color-secondary); font-size: 10px; }
.source-section { margin-bottom: 6px; color: var(--el-text-color-secondary); font-size: 11px; }
blockquote { margin: 0; padding: 8px 11px; border-left: 2px solid var(--el-color-primary-light-7); border-radius: 0 5px 5px 0; background: var(--el-fill-color-light); color: var(--el-text-color-regular); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.8; }
.source-images { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.source-image { display: grid; place-items: center; width: 180px; min-height: 90px; overflow: hidden; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
.source-image .el-image { display: block; width: 100%; height: 120px; cursor: zoom-in; }
.image-placeholder, .asset-error { padding: 10px; color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.6; }
.asset-error { color: var(--el-color-danger); }
.source-actions { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 10px; }
.source-actions .el-button + .el-button { margin-left: 0; }
.source-actions .el-button { font-size: 12px; }
</style>
