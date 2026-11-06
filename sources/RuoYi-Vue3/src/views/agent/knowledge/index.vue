<template>
  <div class="app-container knowledge-page">
    <header class="page-heading"><div><h1>知识库</h1><p>上传业务资料，供所有已登录用户在对话中共同使用。</p></div><el-button :icon="Refresh" :loading="refreshing" @click="refresh()">刷新</el-button></header>
    <el-alert v-if="loadError" class="page-error" :title="loadError" type="error" :closable="false" show-icon />
    <div class="knowledge-layout">
      <aside class="base-panel" aria-label="知识库列表">
        <div class="panel-heading"><h2>全部知识库 <span>{{ bases.length }}</span></h2><el-button v-hasPermi="['knowledge:base:add']" :icon="Plus" type="primary" link @click="openBaseDialog()">创建</el-button></div>
        <div v-loading="loading" class="base-list">
          <article v-for="base in bases" :key="base.kb_id" class="base-item" :class="{ selected: selectedBaseId === base.kb_id }">
            <button class="base-select" :aria-current="selectedBaseId === base.kb_id ? 'true' : undefined" @click="selectBase(base.kb_id)">
              <el-icon class="base-icon"><Collection /></el-icon>
              <span class="base-copy"><span class="base-name">{{ base.name }}</span><span class="base-meta">{{ base.document_count }} 个文件 <span v-if="base.status !== 'active'">· {{ baseStatusLabels[base.status] }}</span></span></span>
            </button>
            <div class="base-actions">
              <el-button v-hasPermi="['knowledge:base:edit']" link :icon="Edit" :disabled="base.status !== 'active'" :aria-label="`重命名 ${base.name}`" @click="openBaseDialog(base)" />
              <el-button v-hasPermi="['knowledge:base:remove']" link :icon="Delete" type="danger" :disabled="base.status === 'deleting'" :loading="busyActions.has(`base:${base.kb_id}`)" :aria-label="`删除 ${base.name}`" @click="removeBase(base)" />
            </div>
            <div v-if="base.error" class="base-error">{{ base.error }}</div>
          </article>
          <el-empty v-if="!loading && !bases.length" description="还没有知识库" :image-size="70" />
        </div>
        <div class="shared-note"><el-icon><User /></el-icon>所有已登录用户共享资料</div>
      </aside>

      <section class="documents-panel" aria-label="知识库文件">
        <template v-if="selectedBase">
          <header class="document-heading"><div><h2>{{ selectedBase.name }}</h2><p v-if="selectedBase.description">{{ selectedBase.description }}</p><p v-else>上传原文件后，系统会自动解析并建立检索索引。</p></div><el-tag v-if="selectedBase.status !== 'active'" :type="selectedBase.status === 'deleting' ? 'warning' : 'danger'">{{ baseStatusLabels[selectedBase.status] }}</el-tag></header>
          <div class="document-toolbar">
            <div class="toolbar-actions"><el-button v-hasPermi="['knowledge:document:upload']" type="primary" :icon="Upload" :loading="uploading" :disabled="selectedBase.status !== 'active'" @click="uploadInput.click()">上传文件</el-button><el-tooltip content="PDF、Word、PowerPoint、Excel、图片、TXT 和 Markdown；单文件最大 50 MB，文本使用 UTF-8 编码" placement="top"><span class="upload-hint">支持多选 · 每个文件 ≤ 50 MB</span></el-tooltip><input ref="uploadInput" type="file" multiple :accept="acceptedFileTypes" class="upload-input" aria-label="选择要上传的知识库文件" @change="uploadFiles" /></div>
            <span v-if="pollingNeeded" class="processing-note" role="status"><span></span>处理进度自动更新</span><span v-else class="document-count">共 {{ total }} 个文件</span>
          </div>
          <div v-if="uploadEntries.length" class="upload-results" aria-live="polite"><div class="upload-results-title"><span>本次上传</span><el-button v-if="!uploading" link @click="uploadEntries = []">收起</el-button></div><div v-for="entry in uploadEntries" :key="entry.id" class="upload-entry"><span class="upload-file-name" :title="entry.name">{{ entry.name }}</span><span class="upload-file-size">{{ formatSize(entry.size) }}</span><el-tag size="small" :type="entry.status === 'failed' ? 'danger' : entry.status === 'accepted' ? 'success' : 'info'">{{ uploadStatusLabels[entry.status] }}</el-tag><span v-if="entry.error" class="upload-error">{{ entry.error }}</span></div></div>
          <el-table v-loading="loading" :data="documents" row-key="document_id" class="document-table">
            <el-table-column label="文件名" min-width="220"><template #default="{ row }"><div class="file-name"><el-icon><Document /></el-icon><el-button link type="primary" :title="row.name" @click="previewRef.open(row)">{{ row.name }}</el-button></div><div class="file-date">{{ formatDate(row.created_at) }}</div></template></el-table-column>
            <el-table-column label="大小" width="100"><template #default="{ row }">{{ formatSize(row.size) }}</template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="documentStatusTypes[row.status]" size="small">{{ documentStatusLabels[row.status] }}</el-tag></template></el-table-column>
            <el-table-column label="处理阶段 / 失败原因" min-width="200"><template #default="{ row }"><span class="stage-label">{{ stageLabel(row.stage) }}</span><div v-if="row.error" class="document-error">{{ row.error }}</div><span v-else-if="row.status === 'ready'" class="chunk-count">{{ row.chunk_count }} 个内容片段</span></template></el-table-column>
            <el-table-column label="操作" width="260" fixed="right"><template #default="{ row }"><div class="document-actions"><el-button link type="primary" @click="previewRef.open(row)">查看</el-button><el-button link type="primary" :loading="previewRef?.downloading.has(row.document_id)" @click="previewRef.download(row)">下载</el-button><el-button v-if="row.status === 'failed' || row.status === 'ready'" v-hasPermi="['knowledge:document:reprocess']" link type="primary" :disabled="selectedBase.status !== 'active'" :loading="busyActions.has(`reprocess:${row.document_id}`)" @click="reprocessDocument(row)">{{ row.status === 'failed' ? '重新处理' : '重建索引' }}</el-button><el-button v-hasPermi="['knowledge:document:remove']" link type="danger" :disabled="selectedBase.status !== 'active' || row.status === 'deleting'" :loading="busyActions.has(`document:${row.document_id}`)" @click="removeDocument(row)">{{ row.status === 'delete_failed' ? '重试删除' : '删除' }}</el-button></div></template></el-table-column>
            <template #empty><el-empty description="暂无文件，上传资料后即可在对话中引用" :image-size="80" /></template>
          </el-table>
          <div v-if="total" class="pagination-wrap"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next" @current-change="changePage" @size-change="changePageSize" /></div>
        </template>
        <el-empty v-else class="choose-base" description="创建或选择一个知识库，开始管理资料" :image-size="110" />
      </section>
    </div>

    <el-dialog v-model="baseDialogOpen" :title="editingBaseId ? '重命名知识库' : '创建知识库'" width="480px" append-to-body :close-on-click-modal="false" :close-on-press-escape="!savingBase" :show-close="!savingBase">
      <el-alert v-if="baseDialogError" :title="baseDialogError" type="error" :closable="false" show-icon class="dialog-error" />
      <el-form ref="baseFormRef" :model="baseForm" :rules="baseRules" label-position="top" :disabled="savingBase" @submit.prevent="saveBase">
        <el-form-item label="知识库名称" prop="name"><el-input v-model.trim="baseForm.name" placeholder="例如：产品手册、内部制度" maxlength="100" show-word-limit /></el-form-item>
        <el-form-item label="说明" prop="description"><el-input v-model.trim="baseForm.description" type="textarea" :rows="3" placeholder="简要描述知识库的内容和用途" maxlength="1000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="savingBase" @click="baseDialogOpen = false">取消</el-button><el-button type="primary" :loading="savingBase" @click="saveBase">保存</el-button></template>
    </el-dialog>
    <KnowledgeFilePreview ref="previewRef" />
  </div>
</template>

<script setup name="AgentKnowledge">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Delete, Document, Edit, Plus, Refresh, Upload, User } from '@element-plus/icons-vue'
import { createKnowledgeBase, deleteKnowledgeBase, deleteKnowledgeDocument, KnowledgeApiError, listKnowledgeBases, listKnowledgeDocuments, reprocessKnowledgeDocument, updateKnowledgeBase, uploadKnowledgeDocument } from '@/api/agent/knowledge'
import KnowledgeFilePreview from './components/KnowledgeFilePreview.vue'

const bases = ref([])
const selectedBaseId = ref('')
const documents = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const busyActions = reactive(new Set())
const uploadInput = ref(null)
const uploading = ref(false)
const uploadEntries = ref([])
const previewRef = ref(null)
const baseDialogOpen = ref(false)
const baseDialogError = ref('')
const editingBaseId = ref('')
const baseFormRef = ref(null)
const baseForm = reactive({ name: '', description: '' })
const savingBase = ref(false)
const baseRules = { name: [{ required: true, whitespace: true, message: '请输入知识库名称', trigger: 'blur' }] }
const baseStatusLabels = { active: '可用', deleting: '删除中', delete_failed: '删除失败' }
const documentStatusLabels = { processing: '处理中', ready: '可用', failed: '处理失败', deleting: '删除中', delete_failed: '删除失败' }
const documentStatusTypes = { processing: 'primary', ready: 'success', failed: 'danger', deleting: 'warning', delete_failed: 'danger' }
const uploadStatusLabels = { uploading: '上传中', accepted: '已接收', failed: '上传失败', cancelled: '已取消' }
const acceptedExtensions = new Set(['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg', 'jp2', 'webp', 'gif', 'bmp', 'txt', 'md'])
const acceptedFileTypes = [...acceptedExtensions].map(extension => `.${extension}`).join(',')
const stageLabels = { queued: '等待处理', parsing: '解析文件', splitting: '拆分内容', indexing: '建立索引', ready: '处理完成', failed: '处理失败' }
const selectedBase = computed(() => bases.value.find(base => base.kb_id === selectedBaseId.value))
const pollingNeeded = computed(() => bases.value.some(base => base.status === 'deleting') || documents.value.some(file => file.status === 'processing' || file.status === 'deleting'))
const controllers = new Set()
let refreshController
let pollTimer
let active = false

function stageLabel(stage) {
  return stage ? stageLabels[stage] || stage : '—'
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function schedulePoll() {
  window.clearTimeout(pollTimer)
  if (active && pollingNeeded.value) pollTimer = window.setTimeout(() => void refresh({ silent: true }), 3000)
}

async function refresh({ silent = false } = {}) {
  window.clearTimeout(pollTimer)
  refreshController?.abort()
  const controller = new AbortController()
  refreshController = controller
  controllers.add(controller)
  refreshing.value = true
  loading.value = !silent
  loadError.value = ''
  try {
    const result = await listKnowledgeBases(controller.signal)
    if (controller.signal.aborted) return
    bases.value = result.items
    if (!bases.value.some(base => base.kb_id === selectedBaseId.value)) {
      selectedBaseId.value = bases.value.length ? bases.value[0].kb_id : ''
      page.value = 1
    }
    if (selectedBaseId.value) {
      let result = await listKnowledgeDocuments(selectedBaseId.value, { page: page.value, page_size: pageSize.value }, controller.signal)
      if (controller.signal.aborted) return
      if (!result.items.length && result.total > 0 && page.value > 1) {
        page.value = Math.ceil(result.total / pageSize.value)
        result = await listKnowledgeDocuments(selectedBaseId.value, { page: page.value, page_size: pageSize.value }, controller.signal)
      }
      if (controller.signal.aborted) return
      documents.value = result.items
      total.value = result.total
    } else {
      documents.value = []
      total.value = 0
    }
  } catch (error) {
    if (controller.signal.aborted) return
    if (!(error instanceof KnowledgeApiError)) throw error
    loadError.value = error.message
  } finally {
    controllers.delete(controller)
    if (refreshController === controller) {
      loading.value = false
      refreshing.value = false
      schedulePoll()
    }
  }
}

function selectBase(kbId) {
  if (selectedBaseId.value === kbId) return
  selectedBaseId.value = kbId
  page.value = 1
  documents.value = []
  total.value = 0
  void refresh()
}

function changePage() {
  void refresh()
}

function changePageSize() {
  page.value = 1
  void refresh()
}

async function openBaseDialog(base) {
  editingBaseId.value = base ? base.kb_id : ''
  baseForm.name = base ? base.name : ''
  baseForm.description = base ? base.description : ''
  baseDialogError.value = ''
  baseDialogOpen.value = true
  await nextTick()
  baseFormRef.value.clearValidate()
}

async function saveBase() {
  const valid = await baseFormRef.value.validate(valid => valid)
  if (!valid) return
  savingBase.value = true
  baseDialogError.value = ''
  const controller = new AbortController()
  controllers.add(controller)
  try {
    const data = { name: baseForm.name, description: baseForm.description }
    if (editingBaseId.value) await updateKnowledgeBase(editingBaseId.value, data, controller.signal)
    else {
      const base = await createKnowledgeBase(data, controller.signal)
      selectedBaseId.value = base.kb_id
      page.value = 1
    }
    if (controller.signal.aborted) return
    baseDialogOpen.value = false
    ElMessage.success('知识库已保存')
    await refresh({ silent: true })
  } catch (error) {
    if (controller.signal.aborted) return
    if (!(error instanceof KnowledgeApiError)) throw error
    baseDialogError.value = error.message
  } finally {
    controllers.delete(controller)
    savingBase.value = false
  }
}

async function confirmRemoval(message, title) {
  try {
    await ElMessageBox.confirm(message, title, { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger', distinguishCancelAndClose: true })
    return true
  } catch (action) {
    if (action === 'cancel' || action === 'close') return false
    throw action
  }
}

async function performAction(key, action, successMessage) {
  const controller = new AbortController()
  controllers.add(controller)
  busyActions.add(key)
  try {
    await action(controller.signal)
    if (controller.signal.aborted) return
    ElMessage.success(successMessage)
    await refresh({ silent: true })
  } catch (error) {
    if (controller.signal.aborted) return
    if (!(error instanceof KnowledgeApiError)) throw error
    ElMessage.error(error.message)
  } finally {
    controllers.delete(controller)
    busyActions.delete(key)
  }
}

async function removeBase(base) {
  if (!await confirmRemoval(`确定删除“${base.name}”及其全部文件、内容索引吗？删除后无法恢复。`, '删除知识库')) return
  if (!active) return
  await performAction(`base:${base.kb_id}`, signal => deleteKnowledgeBase(base.kb_id, signal), '已提交知识库删除任务')
}

async function removeDocument(file) {
  if (!await confirmRemoval(`确定删除“${file.name}”及其内容索引吗？删除后无法恢复。`, '删除文件')) return
  if (!active) return
  await performAction(`document:${file.document_id}`, signal => deleteKnowledgeDocument(file.document_id, signal), '已提交文件删除任务')
}

async function reprocessDocument(file) {
  await performAction(`reprocess:${file.document_id}`, signal => reprocessKnowledgeDocument(file.document_id, signal), '已提交重新处理任务')
}

async function uploadFiles(event) {
  const files = [...event.target.files]
  event.target.value = ''
  if (!files.length) return
  const kbId = selectedBaseId.value
  uploading.value = true
  uploadEntries.value = files.map((file, index) => ({ id: index, name: file.name, size: file.size, status: 'uploading', error: '' }))
  try {
    await Promise.all(files.map(async (file, index) => {
      const entry = uploadEntries.value[index]
      const extension = file.name.split('.').pop().toLowerCase()
      if (!acceptedExtensions.has(extension)) {
        entry.status = 'failed'
        entry.error = '不支持此文件格式，请上传 PDF、Office、图片、TXT 或 Markdown 文件'
        return
      }
      if (file.size > 50 * 1024 * 1024) {
        entry.status = 'failed'
        entry.error = '单个文件不能超过 50 MB'
        return
      }
      const controller = new AbortController()
      controllers.add(controller)
      try {
        await uploadKnowledgeDocument(kbId, file, controller.signal)
        if (controller.signal.aborted) return
        entry.status = 'accepted'
      } catch (error) {
        if (controller.signal.aborted) {
          entry.status = 'cancelled'
          return
        }
        if (!(error instanceof KnowledgeApiError)) throw error
        entry.status = 'failed'
        entry.error = error.message
      } finally {
        controllers.delete(controller)
      }
    }))
    if (active) await refresh({ silent: true })
  } finally {
    uploading.value = false
  }
}

function activate() {
  if (active) return
  active = true
  void refresh()
}

function deactivate() {
  active = false
  window.clearTimeout(pollTimer)
  controllers.forEach(controller => controller.abort())
  controllers.clear()
  baseDialogOpen.value = false
}

onMounted(activate)
onActivated(activate)
onDeactivated(deactivate)
onBeforeUnmount(deactivate)
</script>

<style scoped lang="scss">
.knowledge-page { color: var(--el-text-color-primary); }
.page-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 20px; }
.page-heading h1 { margin: 0 0 7px; font-size: 22px; font-weight: 600; }
.page-heading p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
.page-error { margin-bottom: 16px; }
.knowledge-layout { display: flex; min-height: 590px; overflow: hidden; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; background: var(--el-bg-color); }
.base-panel { display: flex; flex-direction: column; flex: 0 0 255px; min-width: 0; background: var(--el-fill-color-lighter); border-right: 1px solid var(--el-border-color-lighter); }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 20px 17px 14px; }
.panel-heading h2 { margin: 0; font-size: 14px; font-weight: 600; }
.panel-heading h2 span { margin-left: 5px; color: var(--el-text-color-placeholder); font-size: 12px; font-weight: 400; }
.base-list { flex: 1; min-height: 120px; max-height: 70vh; overflow-y: auto; padding: 0 9px 14px; }
.base-item { position: relative; margin-bottom: 6px; border: 1px solid transparent; border-radius: 7px; }
.base-item:hover { background: var(--el-bg-color); }
.base-item.selected { border-color: var(--el-color-primary-light-8); background: var(--el-color-primary-light-9); }
.base-select { display: flex; align-items: flex-start; gap: 9px; width: 100%; padding: 13px 56px 13px 10px; border: 0; border-radius: 7px; background: transparent; color: inherit; text-align: left; font-family: inherit; cursor: pointer; }
.base-select:focus-visible { outline: 2px solid var(--el-color-primary); }
.base-icon { flex-shrink: 0; margin-top: 2px; color: var(--el-color-primary); font-size: 17px; }
.base-copy { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.base-name { overflow: hidden; font-size: 13px; line-height: 19px; text-overflow: ellipsis; white-space: nowrap; }
.selected .base-name { color: var(--el-color-primary); font-weight: 500; }
.base-meta { color: var(--el-text-color-secondary); font-size: 11px; line-height: 16px; }
.base-actions { position: absolute; top: 11px; right: 6px; display: flex; gap: 4px; }
.base-actions .el-button { width: 20px; margin: 0; }
.base-error { padding: 0 10px 10px; color: var(--el-color-danger); font-size: 11px; line-height: 1.6; overflow-wrap: anywhere; }
.shared-note { display: flex; align-items: center; gap: 6px; margin: 0 17px; padding: 15px 0; border-top: 1px solid var(--el-border-color-lighter); color: var(--el-text-color-placeholder); font-size: 11px; }
.documents-panel { flex: 1; min-width: 0; padding: 22px 24px; }
.document-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.document-heading h2 { margin: 0; font-size: 18px; line-height: 1.5; overflow-wrap: anywhere; }
.document-heading p { margin: 7px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.document-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin: 23px 0 18px; }
.toolbar-actions { display: flex; align-items: center; gap: 12px; }
.upload-input { display: none; }
.upload-hint, .document-count { color: var(--el-text-color-secondary); font-size: 12px; }
.processing-note { display: flex; align-items: center; gap: 6px; color: var(--el-color-primary); font-size: 12px; }
.processing-note > span { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.upload-results { margin-bottom: 16px; padding: 10px 13px; border: 1px solid var(--el-border-color-lighter); border-radius: 7px; background: var(--el-fill-color-lighter); }
.upload-results-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; color: var(--el-text-color-secondary); font-size: 12px; }
.upload-entry { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; padding: 5px 0; font-size: 12px; }
.upload-file-name { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-file-size { color: var(--el-text-color-secondary); }
.upload-error { width: 100%; color: var(--el-color-danger); line-height: 1.6; overflow-wrap: anywhere; }
.file-name { display: flex; align-items: center; gap: 6px; }
.file-name > .el-icon { flex-shrink: 0; color: var(--el-text-color-placeholder); }
.file-name > .el-button { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.file-date { margin: 4px 0 0 20px; color: var(--el-text-color-placeholder); font-size: 10px; line-height: 1.7; }
.stage-label { display: block; font-size: 12px; }
.chunk-count { display: block; margin-top: 3px; color: var(--el-text-color-secondary); font-size: 11px; }
.document-error { max-height: 84px; margin-top: 4px; overflow-y: auto; color: var(--el-color-danger); font-size: 11px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.document-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 5px 10px; }
.document-actions .el-button { margin: 0; font-size: 12px; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 22px; overflow-x: auto; }
.choose-base { min-height: 450px; }
.dialog-error { margin-bottom: 18px; }
@media (max-width: 1050px) { .base-panel { flex-basis: 220px; } .documents-panel { padding: 20px 16px; } .upload-hint { display: none; } }
@media (max-width: 767px) {
  .knowledge-page { padding: 14px; }
  .page-heading { gap: 12px; margin-bottom: 16px; }
  .page-heading h1 { font-size: 20px; }
  .page-heading p { font-size: 11px; }
  .knowledge-layout { flex-direction: column; }
  .base-panel { flex-basis: auto; border-right: 0; border-bottom: 1px solid var(--el-border-color-lighter); }
  .panel-heading { padding: 15px 15px 10px; }
  .base-list { max-height: 230px; min-height: 0; }
  .shared-note { padding: 10px 0; }
  .documents-panel { padding: 18px 13px; }
  .document-heading h2 { font-size: 16px; }
  .pagination-wrap { justify-content: flex-start; }
  .upload-file-name { max-width: 200px; }
}
</style>
