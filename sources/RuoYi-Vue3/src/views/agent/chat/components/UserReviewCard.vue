<template>
  <section class="review-card" aria-label="用户操作审核">
    <div class="review-heading">
      <div><el-tag :type="isDelete ? 'danger' : 'warning'" size="small">等待人工审核</el-tag><h2>{{ review.title }}</h2></div>
      <span class="review-hint">审核通过后才会执行</span>
    </div>
    <el-alert v-if="optionsError" :title="optionsError" type="error" :closable="false" show-icon class="review-alert" />
    <el-alert v-if="validationMessage" :title="validationMessage" type="error" :closable="false" show-icon class="review-alert" />
    <el-form v-if="selectingTarget" ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="busy">
      <el-alert title="输入要操作的登录账号，助手会查找用户并生成完整的审核表单。" type="info" :closable="false" show-icon class="review-alert" />
      <el-form-item label="登录账号" prop="userName"><el-input v-model="form.userName" maxlength="30" placeholder="例如：zhangsan" /></el-form-item>
    </el-form>
    <template v-else-if="isDelete">
      <el-alert title="删除后，该用户将无法继续登录。请核对用户身份。" type="warning" :closable="false" show-icon />
      <el-descriptions :column="1" border class="target-details">
        <el-descriptions-item label="登录账号">{{ target.userName }}</el-descriptions-item>
        <el-descriptions-item label="用户昵称">{{ target.nickName }}</el-descriptions-item>
      </el-descriptions>
    </template>
    <el-form v-else-if="!optionsError" ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="busy" class="review-form">
      <div class="form-grid">
        <el-form-item label="登录账号" prop="userName">
          <el-input v-model="form.userName" :disabled="review.operation === 'update'" :maxlength="review.operation === 'create' ? 20 : 30" />
        </el-form-item>
        <el-form-item label="用户昵称" prop="nickName"><el-input v-model="form.nickName" maxlength="30" /></el-form-item>
        <el-form-item label="归属部门" prop="deptId">
          <el-tree-select v-model="form.deptId" :data="review.options.departments" :props="{ label: 'label', children: 'children', value: 'id' }" node-key="id" check-strictly clearable filterable placeholder="选择部门" />
        </el-form-item>
        <el-form-item label="用户角色" prop="roleIds">
          <el-select v-model="form.roleIds" multiple clearable placeholder="选择角色">
            <el-option v-for="role in review.options.roles" :key="role.roleId" :label="role.roleName" :value="role.roleId" :disabled="role.status !== '0'" />
          </el-select>
        </el-form-item>
        <el-form-item label="岗位" prop="postIds">
          <el-select v-model="form.postIds" multiple clearable placeholder="选择岗位">
            <el-option v-for="post in review.options.posts" :key="post.postId" :label="post.postName" :value="post.postId" :disabled="post.status !== '0'" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机号码" prop="phonenumber"><el-input v-model="form.phonenumber" maxlength="11" /></el-form-item>
        <el-form-item label="邮箱" prop="email"><el-input v-model="form.email" maxlength="50" /></el-form-item>
        <el-form-item label="性别" prop="sex">
          <el-select v-model="form.sex"><el-option label="男" value="0" /><el-option label="女" value="1" /><el-option label="未知" value="2" /></el-select>
        </el-form-item>
        <el-form-item label="用户状态" prop="status">
          <el-radio-group v-model="form.status"><el-radio value="0">正常</el-radio><el-radio value="1">停用</el-radio></el-radio-group>
        </el-form-item>
        <el-form-item label="备注" prop="remark" class="full-width"><el-input v-model="form.remark" type="textarea" :rows="2" maxlength="500" /></el-form-item>
      </div>
      <p v-if="review.operation === 'create'" class="field-note">初始密码由若依系统配置提供。</p>
      <div v-if="review.operation === 'update' && changes.length" class="changes">
        <h3>本次修改</h3>
        <div v-for="change in changes" :key="change.label" class="change-row">
          <span>{{ change.label }}</span><del>{{ change.before }}</del><span class="change-arrow">→</span><strong>{{ change.after }}</strong>
        </div>
      </div>
    </el-form>
    <div class="review-actions">
      <el-button :type="isDelete ? 'danger' : 'primary'" :loading="busy" :disabled="busy || !!optionsError" @click="approve">{{ selectingTarget ? '查找用户并继续审核' : isDelete ? '确认删除' : '审核通过并执行' }}</el-button>
      <el-button :disabled="busy" @click="emit('submit', { decision: 'reject' })">拒绝执行</el-button>
    </div>
    <div class="feedback-area">
      <label :for="`review-feedback-${review.interrupt_id}`">也可以回复修改要求，让助手重新准备</label>
      <el-input :id="`review-feedback-${review.interrupt_id}`" v-model="feedback" type="textarea" :rows="2" maxlength="2000" :disabled="busy" placeholder="例如：把部门改成研发部，角色只保留普通角色" />
      <el-button :disabled="busy || !feedback.trim()" :icon="Position" @click="sendFeedback">发送修改要求</el-button>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { Position } from '@element-plus/icons-vue'

const props = defineProps({ review: { type: Object, required: true }, busy: Boolean })
const emit = defineEmits(['submit'])
const formRef = ref(null)
const feedback = ref('')
const form = reactive({})
const selectingTarget = computed(() => props.review.stage === 'select_target')
const isDelete = computed(() => props.review.operation === 'delete' && !selectingTarget.value)
const target = computed(() => props.review.target || props.review.fields)
const validationMessage = computed(() => props.review.errors?.map(error => `${error.field}：${error.message}`).join('；') || '')
const optionsError = computed(() => {
  if (isDelete.value || selectingTarget.value) return ''
  const options = props.review.options
  if (!options || !Array.isArray(options.roles) || !Array.isArray(options.posts) || !Array.isArray(options.departments)) {
    return '未能获取部门、角色和岗位选项，请回复助手重新准备，或拒绝本次操作。'
  }
  return options.error || ''
})
const rules = computed(() => ({
  userName: [{ required: true, whitespace: true, message: '请填写登录账号', trigger: 'blur' }, { min: props.review.operation === 'create' ? 2 : 1, max: props.review.operation === 'create' ? 20 : 30, message: props.review.operation === 'create' ? '登录账号长度为 2 至 20 个字符' : '登录账号最多 30 个字符', trigger: 'blur' }],
  nickName: [{ required: true, whitespace: true, message: '请填写用户昵称', trigger: 'blur' }, { max: 30, message: '用户昵称最多 30 个字符', trigger: 'blur' }],
  email: [{ type: 'email', message: '请填写有效的邮箱地址', trigger: 'blur' }],
  phonenumber: [{ pattern: /^(?:1[3-9]\d{9})?$/, message: '请填写有效的 11 位手机号码', trigger: 'blur' }]
}))
const fieldLabels = {
  nickName: '昵称', deptId: '部门', roleIds: '角色', postIds: '岗位', phonenumber: '手机', email: '邮箱', sex: '性别', status: '状态', remark: '备注'
}

watch(() => props.review, () => {
  const fields = props.review.fields
  Object.assign(form, {
    userId: fields.userId,
    userName: fields.userName ?? '',
    nickName: fields.nickName ?? '',
    deptId: fields.deptId,
    roleIds: [...(fields.roleIds ?? [])],
    postIds: [...(fields.postIds ?? [])],
    phonenumber: fields.phonenumber ?? '',
    email: fields.email ?? '',
    sex: fields.sex ?? '2',
    status: fields.status ?? '0',
    remark: fields.remark ?? ''
  })
  feedback.value = ''
  formRef.value?.clearValidate()
}, { immediate: true })

function departmentLabel(id, nodes) {
  for (const node of nodes) {
    if (node.id === id) return node.label
    const label = node.children && departmentLabel(id, node.children)
    if (label) return label
  }
  return ''
}

function displayValue(key, value) {
  if (value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)) return '未设置'
  const options = props.review.options
  if (key === 'deptId') return departmentLabel(value, options.departments) || `部门 ${value}`
  if (key === 'roleIds') return value.map(id => options.roles.find(role => role.roleId === id)?.roleName || `角色 ${id}`).join('、')
  if (key === 'postIds') return value.map(id => options.posts.find(post => post.postId === id)?.postName || `岗位 ${id}`).join('、')
  if (key === 'sex') return { 0: '男', 1: '女', 2: '未知' }[value]
  if (key === 'status') return { 0: '正常', 1: '停用' }[value]
  return value
}

const changes = computed(() => {
  if (selectingTarget.value || props.review.operation !== 'update' || !props.review.before || optionsError.value) return []
  return Object.entries(fieldLabels)
    .filter(([key]) => JSON.stringify(props.review.before[key] ?? '') !== JSON.stringify(form[key] ?? ''))
    .map(([key, label]) => ({ label, before: displayValue(key, props.review.before[key]), after: displayValue(key, form[key]) }))
})

async function approve() {
  if (!isDelete.value) {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) return
  }
  const fields = selectingTarget.value ? { userName: form.userName.trim() } : isDelete.value ? { userId: target.value.userId } : { ...form, deptId: form.deptId ?? null, roleIds: [...form.roleIds], postIds: [...form.postIds] }
  if (props.review.operation === 'create') delete fields.userId
  emit('submit', { decision: 'approve', fields })
}

function sendFeedback() {
  emit('submit', { decision: 'feedback', feedback: feedback.value.trim() })
}
</script>

<style scoped lang="scss">
.review-card { margin: 14px 0 26px 46px; padding: 20px; border: 1px solid var(--el-color-warning-light-5); border-radius: 12px; background: var(--el-bg-color); }
.review-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 18px; }
.review-heading h2 { margin: 10px 0 0; font-size: 16px; font-weight: 600; }
.review-hint, .field-note { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.7; }
.review-alert { margin-bottom: 16px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 18px; }
.form-grid .el-select, .form-grid .el-tree-select { width: 100%; }
.full-width { grid-column: 1 / -1; }
.field-note { margin: -6px 0 14px; }
.target-details { margin-top: 16px; }
.review-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.review-actions .el-button + .el-button { margin-left: 0; }
.feedback-area { display: flex; align-items: flex-start; flex-direction: column; gap: 10px; border-top: 1px solid var(--el-border-color-lighter); margin-top: 20px; padding-top: 16px; }
.feedback-area label { color: var(--el-text-color-secondary); font-size: 12px; }
.feedback-area > .el-button { align-self: flex-end; }
.changes { border-radius: 8px; background: var(--el-fill-color-light); padding: 12px; }
.changes h3 { margin: 0 0 10px; font-size: 13px; }
.change-row { display: grid; grid-template-columns: 60px 1fr 16px 1fr; gap: 8px; margin-top: 8px; font-size: 12px; overflow-wrap: anywhere; }
.change-row del { color: var(--el-text-color-secondary); }
.change-row strong { font-weight: 500; }
.change-arrow { color: var(--el-text-color-placeholder); }
@media (max-width: 768px) {
  .review-card { margin-left: 0; padding: 14px; }
  .review-heading { flex-direction: column; gap: 6px; }
  .form-grid { grid-template-columns: 1fr; gap: 0; }
  .change-row { grid-template-columns: 48px 1fr 12px 1fr; gap: 4px; }
}
</style>
