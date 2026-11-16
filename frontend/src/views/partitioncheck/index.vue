<template>
  <section class="page" data-module="partitioncheck">
    <header class="page-head">
      <div>
        <h2>分区检测管理</h2>
        <p class="page-desc">管理数据表分区的完整性检测规则，自动发现和补齐缺失分区。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检测规则</button>
        <button class="btn" type="button" @click="exportRows">导出分区检测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

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
            <button class="link" type="button" @click="openReports(row)">关联差异报告</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无分区检测数据，可先登记检测规则</td>
        </tr>
      </tbody>
    </table>

    <section v-if="reportPanel" class="report-panel">
      <header class="report-head">
        <h3>关联差异报告 · 规则 {{ reportPanel.ruleNo }}（{{ reportPanel.table }}）</h3>
        <button class="btn ghost" type="button" @click="reportPanel = null">关闭</button>
      </header>
      <p v-if="!reportPanel.reports.length" class="empty-state">该表暂无关联的终态差异报告</p>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th v-for="column in reportColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="report in reportPanel.reports" :key="String(report.id)">
            <td v-for="column in reportColumns" :key="column">{{ reportCell(report, column) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条分区检测记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/partitioncheck'
const ruleFields = ["规则编号", "数据表名", "期望分区数", "分区延迟容忍", "缺失分区告警", "检测间隔分钟", "自动补齐开关", "补齐优先级"]
const detectFields = ["差异数量", "未核对分区", "缺失分区"]
const columns = [...ruleFields, ...detectFields]
const actions = ["提交规则评审", "启用规则", "暂停规则", "检测缺失分区"]
const reportColumns = ["报告编号", "任务编号", "源表名", "目标表名", "比对字段", "差异数量", "未核对分区", "终态", "生成时间"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ruleFields.slice(0, 3)
const reportPanel = ref<{ ruleNo: string; table: string; reports: Row[] } | null>(null)

const stats = computed(() => [
  { label: "检测规则总数", value: total.value },
  { label: "已启用规则", value: rows.value.filter((row) => row.status === '已启用').length },
  { label: "评审中规则", value: rows.value.filter((row) => row.status === '规则评审中').length },
])

function joinList(value: unknown): string {
  if (Array.isArray(value) && value.length) {
    return value.join('、')
  }
  return '—'
}

function displayCell(row: Row, column: string): string {
  const value = row[column]
  if (Array.isArray(value)) {
    return joinList(value)
  }
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  return String(value)
}

function reportCell(report: Row, column: string): string {
  return displayCell(report, column)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检测规则登记入口尚未接入审批流'
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
      throw new Error(payload.message || '分区检测动作未生效')
    }
    noticeMessage.value = payload.message || `检测规则已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分区检测操作失败'
  }
}

async function openReports(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/diffreports`)
    if (!response.ok) {
      throw new Error('关联差异报告读取失败')
    }
    const payload = await response.json()
    reportPanel.value = {
      ruleNo: String(row['规则编号'] ?? row.id),
      table: String(row['数据表名'] ?? ''),
      reports: payload.reports ?? [],
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '关联差异报告读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('检测规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分区检测列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
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
