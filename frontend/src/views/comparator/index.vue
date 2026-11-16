<template>
  <section class="page" data-module="comparator">
    <header class="page-head">
      <div>
        <h2>数据比对管理</h2>
        <p class="page-desc">管理ETL输出数据与源端的一致性比对任务，检测数据漂移和计算偏差。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记比对任务</button>
        <button class="btn" type="button" @click="exportRows">导出数据比对清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="createVisible" class="filter-bar create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.name" class="filter-item">
        <span>{{ field.name }}<em v-if="field.required" class="required-mark">*</em></span>
        <input v-model="createForm[field.name]" :placeholder="field.placeholder" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
      <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openReport(row)">差异报告</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据比对数据，可先登记比对任务</td>
        </tr>
      </tbody>
    </table>

    <section v-if="reportPanel" class="report-panel">
      <header class="report-head">
        <h3>差异报告 · 任务 {{ reportPanel.taskNo }}</h3>
        <button class="btn ghost" type="button" @click="reportPanel = null">关闭</button>
      </header>
      <p v-if="!reportPanel.report" class="empty-state">任务尚未到达终态，差异报告未生成</p>
      <table v-else class="data-table">
        <tbody>
          <tr v-for="item in reportRows" :key="item.label">
            <th>{{ item.label }}</th>
            <td>{{ item.value }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据比对记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/comparator'
const businessFields = ["任务编号", "源表名", "目标表名", "比对字段", "比对方式", "差异阈值", "采样比例", "产出差异报告"]
const columns = [...businessFields, "状态"]
const actions = ["提交比对审批", "启动比对", "完成比对", "标记失败"]
const createFields = [
  { name: "任务编号", required: true, placeholder: "如 COMP-0004" },
  { name: "源表名", required: true, placeholder: "源端数据表" },
  { name: "目标表名", required: true, placeholder: "目标数据表" },
  { name: "比对字段", required: false, placeholder: "多个字段用逗号分隔" },
  { name: "比对方式", required: false, placeholder: "全量比对 / 抽样比对" },
  { name: "差异阈值", required: false, placeholder: "允许的最大差异数量" },
  { name: "采样比例", required: false, placeholder: "1-100" },
  { name: "产出差异报告", required: false, placeholder: "是 / 否" },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = businessFields.slice(0, 3)
const createVisible = ref(false)
const createForm = ref<Record<string, string>>({})
const reportPanel = ref<{ taskNo: string; report: Row | null } | null>(null)

const stats = computed(() => [
  { label: "比对任务总数", value: total.value },
  { label: "执行中任务", value: rows.value.filter((row) => row.status === '执行中').length },
  { label: "已完成任务", value: rows.value.filter((row) => row.status === '已完成').length },
])

const reportRows = computed(() => {
  const report = reportPanel.value?.report
  if (!report) {
    return []
  }
  return [
    { label: "报告编号", value: report["报告编号"] },
    { label: "任务编号", value: report["任务编号"] },
    { label: "源表名", value: report["源表名"] },
    { label: "目标表名", value: report["目标表名"] },
    { label: "比对字段", value: joinList(report["比对字段"]) },
    { label: "比对方式", value: report["比对方式"] || '—' },
    { label: "差异阈值", value: report["差异阈值"] || '—' },
    { label: "差异数量", value: report["差异数量"] ?? '—' },
    { label: "未核对分区", value: joinList(report["未核对分区"]) },
    { label: "终态", value: report["终态"] },
    { label: "错误信息", value: report["错误信息"] || '—' },
    { label: "备注", value: report["备注"] || '—' },
    { label: "生成时间", value: report["生成时间"] },
  ]
})

function joinList(value: unknown): string {
  if (Array.isArray(value) && value.length) {
    return value.join('、')
  }
  return '—'
}

function displayCell(row: Row, column: string): string {
  if (column === '状态') {
    return row.status ?? '—'
  }
  const value = row[column]
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  return String(value)
}

function toggleCreate() {
  createVisible.value = !createVisible.value
  if (createVisible.value) {
    createForm.value = {}
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '比对任务登记失败')
    }
    noticeMessage.value = payload.message || '比对任务已登记'
    createVisible.value = false
    createForm.value = {}
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '比对任务登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '数据比对动作未生效')
    }
    noticeMessage.value = payload.message || `比对任务已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据比对操作失败'
  }
}

async function openReport(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/report`)
    if (!response.ok) {
      throw new Error('差异报告读取失败')
    }
    const payload = await response.json()
    reportPanel.value = { taskNo: String(row['任务编号'] ?? row.id), report: payload.report }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '差异报告读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('比对任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据比对列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.create-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.required-mark {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.report-panel {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.report-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.report-head h3 {
  margin: 0;
  font-size: 14px;
}
.notice-text {
  color: #067647;
}
</style>
