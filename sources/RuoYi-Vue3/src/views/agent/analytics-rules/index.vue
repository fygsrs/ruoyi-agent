<template>
  <div class="app-container">
    <el-alert
      class="rule-description"
      title="规则用于模型生成SQL的约束；数据库查询使用只读账号。"
      type="info"
      :closable="false"
      show-icon
    />

    <el-form ref="queryRef" :model="queryParams" :inline="true" v-show="showSearch">
      <el-form-item label="库名" prop="databaseName">
        <el-input
          v-model.trim="queryParams.databaseName"
          placeholder="请输入库名"
          maxlength="64"
          clearable
          style="width: 200px"
          @keyup.enter="getList"
        />
      </el-form-item>
      <el-form-item label="表名" prop="tableName">
        <el-input
          v-model.trim="queryParams.tableName"
          placeholder="请输入表名"
          maxlength="64"
          clearable
          style="width: 200px"
          @keyup.enter="getList"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="getList">搜索</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="Plus" @click="handleAdd">新增</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button type="success" plain icon="Edit" :disabled="selectedRows.length !== 1" @click="handleUpdate()">修改</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button type="danger" plain icon="Delete" :disabled="selectedRows.length === 0" @click="handleDelete()">删除</el-button>
      </el-col>
      <right-toolbar v-model:showSearch="showSearch" @queryTable="getList" />
    </el-row>

    <el-table v-loading="loading" :data="ruleList" row-key="id" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="库名" prop="databaseName" min-width="150" show-overflow-tooltip />
      <el-table-column label="表名" prop="tableName" min-width="150" show-overflow-tooltip />
      <el-table-column label="字段名" prop="columnName" min-width="150" show-overflow-tooltip />
      <el-table-column label="备注" prop="remark" min-width="220" show-overflow-tooltip />
      <el-table-column label="操作" width="170" align="center" class-name="small-padding fixed-width">
        <template #default="scope">
          <el-button link type="primary" icon="Edit" @click="handleUpdate(scope.row)">修改</el-button>
          <el-button link type="primary" icon="Delete" @click="handleDelete([scope.row])">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>暂无查询约束</template>
    </el-table>

    <el-dialog :title="title" v-model="open" width="560px" append-to-body :close-on-click-modal="false">
      <el-form ref="ruleRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="规则范围" prop="scope">
          <el-radio-group v-model="ruleScope" @change="handleScopeChange">
            <el-radio value="database">整个库</el-radio>
            <el-radio value="table">整张表</el-radio>
            <el-radio value="column">单个字段</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="库名" prop="databaseName">
          <el-input v-model.trim="form.databaseName" placeholder="请输入库名" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item v-if="ruleScope !== 'database'" label="表名" prop="tableName">
          <el-input v-model.trim="form.tableName" placeholder="请输入表名" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item v-if="ruleScope === 'column'" label="字段名" prop="columnName">
          <el-input v-model.trim="form.columnName" placeholder="请输入字段名" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item label="备注" prop="remark">
          <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="请输入约束说明" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" :loading="submitting" @click="submitForm">确 定</el-button>
          <el-button :disabled="submitting" @click="open = false">取 消</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="AnalyticsRules">
import { addAnalyticsRule, deleteAnalyticsRules, listAnalyticsRules, updateAnalyticsRule } from '@/api/agent/analyticsRules'

const { proxy } = getCurrentInstance()
const ruleList = ref([])
const selectedRows = ref([])
const loading = ref(false)
const submitting = ref(false)
const showSearch = ref(true)
const open = ref(false)
const title = ref('')
const ruleScope = ref('database')
const queryParams = reactive({ databaseName: '', tableName: '' })
const form = ref({})

function nameRules(label) {
  return [
    { required: true, whitespace: true, message: `${label}不能为空`, trigger: 'blur' },
    { max: 64, message: `${label}不能超过64个字符`, trigger: 'blur' },
    { validator: (_rule, value, callback) => value === '*' ? callback(new Error('请填写具体名称，范围通过规则范围选择')) : callback(), trigger: 'blur' }
  ]
}

const rules = computed(() => ({
  databaseName: nameRules('库名'),
  tableName: ruleScope.value === 'database' ? [] : nameRules('表名'),
  columnName: ruleScope.value === 'column' ? nameRules('字段名') : [],
  remark: [{ max: 200, message: '备注不能超过200个字符', trigger: 'blur' }]
}))

async function getList() {
  loading.value = true
  try {
    const response = await listAnalyticsRules(queryParams)
    ruleList.value = response.data
    selectedRows.value = []
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  proxy.resetForm('queryRef')
  getList()
}

function handleSelectionChange(selection) {
  selectedRows.value = selection
}

function handleAdd() {
  form.value = { id: undefined, databaseName: '', tableName: '*', columnName: '*', remark: '' }
  ruleScope.value = 'database'
  title.value = '新增查询约束'
  open.value = true
  nextTick(() => proxy.$refs.ruleRef.clearValidate())
}

function handleUpdate(row = selectedRows.value[0]) {
  form.value = {
    id: row.id,
    databaseName: row.databaseName,
    tableName: row.tableName,
    columnName: row.columnName,
    remark: row.remark
  }
  ruleScope.value = row.tableName === '*' ? 'database' : row.columnName === '*' ? 'table' : 'column'
  title.value = '修改查询约束'
  open.value = true
  nextTick(() => proxy.$refs.ruleRef.clearValidate())
}

function handleScopeChange(scope) {
  if (scope === 'database') {
    form.value.tableName = '*'
  } else if (form.value.tableName === '*') {
    form.value.tableName = ''
  }
  if (scope !== 'column') {
    form.value.columnName = '*'
  } else if (form.value.columnName === '*') {
    form.value.columnName = ''
  }
  nextTick(() => proxy.$refs.ruleRef.clearValidate())
}

function submitForm() {
  proxy.$refs.ruleRef.validate(async valid => {
    if (!valid) return
    submitting.value = true
    const editing = form.value.id !== undefined
    try {
      await (editing ? updateAnalyticsRule(form.value) : addAnalyticsRule(form.value))
      proxy.$modal.msgSuccess(editing ? '修改成功' : '新增成功')
      open.value = false
      await getList()
    } finally {
      submitting.value = false
    }
  })
}

function describeTarget(row) {
  if (row.tableName === '*') return `库「${row.databaseName}」（整个库）`
  if (row.columnName === '*') return `库「${row.databaseName}」/ 表「${row.tableName}」（整张表）`
  return `库「${row.databaseName}」/ 表「${row.tableName}」/ 字段「${row.columnName}」`
}

async function handleDelete(rows = selectedRows.value) {
  const confirmed = await proxy.$modal.confirm(`是否确认删除以下查询约束：${rows.map(describeTarget).join('；')}？`).then(
    () => true,
    action => {
      if (action === 'cancel' || action === 'close') return false
      throw action
    }
  )
  if (!confirmed) return
  await deleteAnalyticsRules(rows.map(row => row.id))
  proxy.$modal.msgSuccess('删除成功')
  await getList()
}

getList()
</script>

<style scoped>
.rule-description {
  margin-bottom: 20px;
}
</style>
