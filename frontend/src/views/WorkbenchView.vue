<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate()">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <RouterLink
      v-if="returnArchiveId"
      class="return-banner"
      data-testid="return-archive"
      :to="`/exp_archive?focus=${returnArchiveId}`"
    >
      材料登记并置为合格状态后，返回原归档 #{{ returnArchiveId }} 继续办理
    </RouterLink>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :data-testid="`row-${row.id}`"
          :data-status="String(row.status)"
          :class="{ 'focus-row': focusId === Number(row.id) }"
        >
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <template v-if="meta.key === 'report_gen'">
              <button
                class="link"
                type="button"
                :data-testid="`summary-${row.id}`"
                @click="openReportDetail(row, 'summary')"
              >
                查看摘要
              </button>
              <button
                class="link"
                type="button"
                :data-testid="`materials-${row.id}`"
                @click="openReportDetail(row, 'materials')"
              >
                查看材料
              </button>
              <button
                v-if="String(row.status) === '已完成'"
                class="link"
                type="button"
                :data-testid="`archive-row-${row.id}`"
                @click="quickArchive(row)"
              >
                归档结论
              </button>
            </template>
            <template v-if="meta.key === 'exp_archive'">
              <button
                class="link"
                type="button"
                :data-testid="`claim-row-${row.id}`"
                @click="quickClaim(row)"
              >
                领取依据
              </button>
              <button
                class="link"
                type="button"
                :data-testid="`basis-${row.id}`"
                @click="openArchiveDetail(row)"
              >
                归档依据/明细
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div
      v-if="detail"
      class="modal-backdrop evidence-backdrop"
      data-testid="evidence-modal"
      @click.self="closeDetail"
    >
      <section class="modal evidence-modal" role="dialog" aria-modal="true">
        <header class="evidence-head">
          <div>
            <h3>{{ detailTitle }}</h3>
            <p class="page-desc">编号 {{ detail.row.id }} · 实验 {{ detail.row.实验编码 ?? '—' }}</p>
          </div>
          <button class="btn" type="button" data-testid="close-detail" @click="closeDetail">关闭</button>
        </header>

        <p v-if="detailBusy" data-testid="detail-loading" class="status-legend">资料读取/办理中…</p>
        <p v-if="detailError" class="error-text" data-testid="detail-error">{{ detailError }}</p>
        <p v-if="detailNotice" class="notice-text" data-testid="detail-notice">{{ detailNotice }}</p>

        <template v-if="detail.kind === 'report'">
          <section class="evidence-card" data-testid="report-summary-panel">
            <h4>摘要与结论条数出处</h4>
            <p data-testid="report-summary-text">{{ summaryData?.摘要 ?? '摘要读取中…' }}</p>
            <p>
              结论条数：
              <strong data-testid="summary-conclusion-count">
                <span data-testid="conclusion-count">
                  {{ summaryData?.结论条数 ?? reportData?.结论条数 ?? '—' }}
                </span>
              </strong>
              （检验 {{ summaryData?.检验条数 ?? '—' }} + 归因 {{ summaryData?.归因条数 ?? '—' }}）
            </p>
            <p class="muted">依据编号：{{ reportData?.依据编号 ?? summaryData?.依据编号 ?? '—' }}</p>
            <div class="page-actions">
              <button
                v-if="String(detail.row.status) === '排队中'"
                class="btn primary"
                type="button"
                data-testid="generate-report-now"
                @click="generateFromPanel"
              >
                生成报告
              </button>
              <button class="btn" type="button" data-testid="refresh-report-detail" @click="refreshReportDetail">
                刷新材料
              </button>
              <button
                v-if="String(detail.row.status) === '已完成' && !detail.row.confirmed"
                class="btn"
                type="button"
                data-testid="confirm-report"
                @click="confirmReport"
              >
                确认结论引用
              </button>
              <button
                v-if="String(detail.row.status) === '已完成'"
                class="btn primary"
                type="button"
                data-testid="archive-conclusion"
                @click="archiveConclusion"
              >
                归档结论
              </button>
            </div>
          </section>

          <section class="evidence-card" data-testid="report-materials-panel">
            <h4>报告实际采用的材料（{{ reportRefs.length }}）</h4>
            <p v-if="!reportRefs.length" class="empty-state">暂无已固化材料；未生成报告显示当前可采用材料。</p>
            <ul class="material-list" data-testid="material-list">
              <li
                v-for="(material, index) in reportRefs"
                :key="material.ref_id ?? index"
                class="material-item"
                data-testid="material-item"
              >
                <span class="tag" :data-material-type="String(material.material_type)">
                  {{ material.类型 ?? material.type ?? material.material_type }}
                </span>
                <div class="material-body">
                  <strong :data-testid="`material-code-${index}`">{{ material.编号 ?? material.材料编号 ?? '未命名材料' }}</strong>
                  <span class="muted">
                    实验 {{ material.实验编码 ?? '—' }} · {{ material.status ?? material.状态 ?? '—' }}
                    <template v-if="material.detail?.指标编码"> · 指标 {{ material.detail.指标编码 }}</template>
                    <template v-if="material.detail?.贡献因子"> · 因子 {{ material.detail.贡献因子 }}</template>
                  </span>
                </div>
                <RouterLink
                  class="btn ghost"
                  :data-testid="`open-material-${index}`"
                  :to="linkForMaterial(material)"
                >
                  打开材料
                </RouterLink>
              </li>
            </ul>
          </section>

          <section class="evidence-card" data-testid="linked-archives-panel">
            <h4>关联归档与恢复依据</h4>
            <p v-if="!linkedArchives.length" class="muted">尚未写入归档，可点击“归档结论”。</p>
            <div v-for="item in linkedArchives" :key="String(item.id)" class="linked-row">
              <RouterLink
                class="link"
                :data-testid="`linked-archive-${item.id}`"
                :to="`/exp_archive?focus=${item.id}`"
              >
                打开归档 #{{ item.id }}（{{ item.status }}）
              </RouterLink>
              <span class="muted">{{ item.依据状态 ?? '' }} · 结论 {{ item.结论条数 ?? '—' }} 条</span>
            </div>
          </section>
        </template>

        <template v-else>
          <section class="evidence-card" data-testid="archive-count-panel">
            <h4>归档结论条数与出处明细复核</h4>
            <p>
              当初发布结论条数：
              <strong data-testid="archive-published-count">
                <span data-testid="archive-conclusion-count">
                  {{ basisData?.实际发布结论条数 ?? basisData?.归档结论条数 ?? basisData?.结论条数 ?? '—' }}
                </span>
              </strong>
            </p>
            <p>
              依据状态：<strong data-testid="archive-basis-status">{{ basisData?.依据状态 ?? '待领取' }}</strong>
              <span class="muted">
                · 已复核 {{ verification?.复核条数 ?? 0 }} /
                {{ verification?.结论条数 ?? basisData?.结论条数 ?? archiveRefs.length }}
              </span>
            </p>
            <p class="muted">依据编号：{{ basisData?.依据编号 ?? '—' }}</p>
            <div class="page-actions">
              <button
                v-if="String(detail.row.status) === '待归档'"
                class="btn"
                type="button"
                data-testid="execute-archive-detail"
                @click="executeArchive"
              >
                执行归档
              </button>
              <button class="btn primary" type="button" data-testid="claim-basis" @click="claimBasis">
                {{ missingItems.length ? '重新领取原归档依据' : '领取归档结论依据' }}
              </button>
              <button class="btn" type="button" data-testid="continue-restore" @click="continueRestore">
                {{ missingItems.length ? '补齐后继续办理原记录' : '继续恢复/恢复实验' }}
              </button>
              <button class="btn ghost" type="button" data-testid="refresh-basis" @click="refreshArchiveDetail">
                刷新明细
              </button>
            </div>
          </section>

          <section v-if="missingItems.length" class="evidence-card missing-card" data-testid="missing-materials-panel">
            <h4>缺项登记：当前缺哪笔材料；请补齐以下材料后重新领取</h4>
            <ul class="material-list" data-testid="missing-list">
              <li
                v-for="(item, index) in missingItems"
                :key="`${item.编号}-${index}`"
                class="material-item missing-item"
                :data-testid="`missing-item-${item.编号 || index}`"
              >
                <span class="tag danger">{{ item.类型 ?? '材料' }}</span>
                <div class="material-body">
                  <strong>{{ item.编号 ? `编号 ${item.编号}` : '缺少材料编号' }}</strong>
                  <span data-testid="missing-reason" class="error-text">{{ item.reason ?? item.原因 }}</span>
                  <span class="muted">{{ item.补证要求 }}</span>
                </div>
                <RouterLink class="btn primary" :data-testid="`fix-missing-${index}`" :to="linkForMaterial(item)">
                  去补齐
                </RouterLink>
              </li>
            </ul>
          </section>

          <section class="evidence-card" data-testid="archive-materials-panel">
            <h4>归档引用材料（{{ archiveRefs.length }}）</h4>
            <p v-if="!archiveRefs.length" class="muted">该档案尚未领取结论依据。</p>
            <ul class="material-list">
              <li v-for="(material, index) in archiveRefs" :key="material.ref_id ?? index" class="material-item">
                <span class="tag">{{ material.类型 ?? material.type ?? material.material_type }}</span>
                <div class="material-body">
                  <strong>{{ material.编号 ?? material.材料编号 ?? '未命名材料' }}</strong>
                  <span class="muted">实验 {{ material.实验编码 ?? '—' }} · {{ material.status ?? '—' }}</span>
                </div>
                <RouterLink class="btn ghost" :to="linkForMaterial(material)">打开材料</RouterLink>
              </li>
            </ul>
          </section>

          <section class="evidence-card" data-testid="archive-history-panel">
            <h4>恢复历史记录</h4>
            <p v-if="!historyItems.length" class="muted">领取完整依据后生成供恢复使用的历史记录。</p>
            <ul class="history-list" data-testid="archive-history-list">
              <li v-for="item in historyItems" :key="String(item.历史编号)" data-testid="history-item">
                <strong>{{ item.历史编号 }}</strong>
                <span>{{ item.status }} · 结论 {{ item.结论条数 }} 条 · {{ item.生成时间 }}</span>
              </li>
            </ul>
          </section>
        </template>
      </section>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  archiveReportNow,
  claimArchiveBasis,
  createEntry,
  downloadEntries,
  generateReportNow,
  getArchiveBasis,
  getReportMaterials,
  getReportSummary,
  listEntries,
  moduleMeta,
  restoreArchiveBasis,
  runAction as applyAction,
  type ArchiveBasis,
  type MaterialRef,
  type ReportMaterials,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const route = useRoute()
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const detail = ref<{ kind: 'report' | 'archive'; row: EntryRow; tab?: string } | null>(null)
const detailBusy = ref(false)
const detailError = ref('')
const detailNotice = ref('')
const reportData = ref<ReportMaterials | null>(null)
const summaryData = ref<ReportMaterials | null>(null)
const basisData = ref<ArchiveBasis | null>(null)

const focusId = computed(() => {
  const value = Number(route.query.focus)
  return Number.isInteger(value) && value > 0 ? value : null
})
const returnArchiveId = computed(() => {
  const value = Number(route.query.return_archive_id)
  return Number.isInteger(value) && value > 0 ? value : null
})

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

const detailTitle = computed(() => {
  if (!detail.value) return ''
  return detail.value.kind === 'report' ? '报告材料、摘要与归档出处' : '归档结论依据与恢复明细'
})
const reportRefs = computed<MaterialRef[]>(() =>
  (reportData.value?.结论依据 as MaterialRef[] | undefined)
  ?? reportData.value?.materials
  ?? summaryData.value?.结论依据 as MaterialRef[] | undefined
  ?? [],
)
const linkedArchives = computed<Record<string, unknown>[]>(() =>
  (reportData.value?.关联归档 as Record<string, unknown>[] | undefined)
  ?? reportData.value?.archives as Record<string, unknown>[] | undefined
  ?? [],
)
const archiveRefs = computed<MaterialRef[]>(() =>
  (basisData.value?.materials as MaterialRef[] | undefined)
  ?? (basisData.value?.复核材料 as MaterialRef[] | undefined)
  ?? (basisData.value?.结论依据 as MaterialRef[] | undefined)
  ?? [],
)
const missingItems = computed<MaterialRef[]>(() =>
  (basisData.value?.缺项 as MaterialRef[] | undefined)
  ?? basisData.value?.missing
  ?? [],
)
const historyItems = computed<Record<string, unknown>[]>(() =>
  (basisData.value?.恢复历史 as Record<string, unknown>[] | undefined)
  ?? [],
)
const verification = computed<{ 复核条数?: number; 结论条数?: number } | null>(() =>
  (basisData.value?.verification as { 复核条数?: number; 结论条数?: number } | undefined) ?? null,
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate(prefill: Record<string, string> = {}) {
  const queryValues: Record<string, string> = {}
  for (const field of meta.fields) {
    const value = route.query[field]
    if (typeof value === 'string') queryValues[field] = value
  }
  createValues.value = Object.fromEntries(
    meta.fields.map((field) => [field, prefill[field] ?? queryValues[field] ?? '']),
  )
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) {
      if (meta.key === 'exp_archive' && ['执行归档', '恢复实验', '继续恢复', '继续办理'].includes(action)) {
        await openArchiveDetail(row)
        detailError.value = result.message
      }
      throw new Error(result.message)
    }
    await reload()
    if (detail.value && Number(detail.value.row.id) === Number(row.id)) {
      if (detail.value.kind === 'report') await refreshReportDetail()
      else await refreshArchiveDetail()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, { size: '200', ...filters.value })
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

function closeDetail() {
  detail.value = null
  reportData.value = null
  summaryData.value = null
  basisData.value = null
  detailError.value = ''
  detailNotice.value = ''
}

async function openReportDetail(row: EntryRow, tab = 'materials') {
  detail.value = { kind: 'report', row, tab }
  detailError.value = ''
  detailNotice.value = ''
  detailBusy.value = true
  try {
    const [materials, summary] = await Promise.all([
      getReportMaterials(Number(row.id)),
      getReportSummary(Number(row.id)),
    ])
    reportData.value = materials
    summaryData.value = summary
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '报告资料读取失败'
  } finally {
    detailBusy.value = false
  }
}

async function refreshReportDetail() {
  if (!detail.value || detail.value.kind !== 'report') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  try {
    const [materials, summary] = await Promise.all([getReportMaterials(id), getReportSummary(id)])
    reportData.value = materials
    summaryData.value = summary
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '报告资料读取失败'
  } finally {
    detailBusy.value = false
  }
}

async function openArchiveDetail(row: EntryRow) {
  detail.value = { kind: 'archive', row }
  detailError.value = ''
  detailNotice.value = ''
  detailBusy.value = true
  try {
    basisData.value = await getArchiveBasis(Number(row.id))
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '归档依据读取失败'
  } finally {
    detailBusy.value = false
  }
}

async function refreshArchiveDetail() {
  if (!detail.value || detail.value.kind !== 'archive') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  try {
    basisData.value = await getArchiveBasis(id)
    const fresh = rows.value.find((row) => Number(row.id) === id)
    if (fresh) detail.value.row = fresh
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '归档依据读取失败'
  } finally {
    detailBusy.value = false
  }
}

async function executeArchive() {
  if (!detail.value || detail.value.kind !== 'archive') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  detailError.value = ''
  detailNotice.value = ''
  try {
    const result = await applyAction('exp_archive', id, '执行归档')
    detailNotice.value = result.message
    if (!result.ok) detailError.value = result.message
    await reload()
    await refreshArchiveDetail()
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '归档失败'
  } finally {
    detailBusy.value = false
  }
}

async function quickClaim(row: EntryRow) {
  await openArchiveDetail(row)
  await claimBasis()
}

async function claimBasis() {
  if (!detail.value || detail.value.kind !== 'archive') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  detailError.value = ''
  detailNotice.value = ''
  try {
    const result = await claimArchiveBasis(id)
    detailNotice.value = result.message
    if (!result.ok) detailError.value = result.message
    await reload()
    basisData.value = await getArchiveBasis(id)
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '领取依据失败'
  } finally {
    detailBusy.value = false
  }
}

async function continueRestore() {
  if (!detail.value || detail.value.kind !== 'archive') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  detailError.value = ''
  detailNotice.value = ''
  try {
    const result = await restoreArchiveBasis(id)
    detailNotice.value = result.message
    if (!result.ok) detailError.value = result.message
    await reload()
    basisData.value = await getArchiveBasis(id)
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '恢复失败'
  } finally {
    detailBusy.value = false
  }
}

async function confirmReport() {
  if (!detail.value || detail.value.kind !== 'report') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  detailError.value = ''
  detailNotice.value = ''
  try {
    const result = await applyAction('report_gen', id, '确认报告')
    detailNotice.value = result.message
    if (!result.ok) detailError.value = result.message
    await reload()
    await refreshReportDetail()
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '确认报告失败'
  } finally {
    detailBusy.value = false
  }
}

async function generateFromPanel() {
  if (!detail.value || detail.value.kind !== 'report') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  detailError.value = ''
  detailNotice.value = ''
  try {
    const result = await generateReportNow(id)
    detailNotice.value = result.message
    if (!result.ok) detailError.value = result.message
    await reload()
    await refreshReportDetail()
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '报告生成失败'
  } finally {
    detailBusy.value = false
  }
}

async function quickArchive(row: EntryRow) {
  await openReportDetail(row)
  await archiveConclusion()
}

async function archiveConclusion() {
  if (!detail.value || detail.value.kind !== 'report') return
  const id = Number(detail.value.row.id)
  detailBusy.value = true
  detailError.value = ''
  detailNotice.value = ''
  try {
    const result = await archiveReportNow(id)
    detailNotice.value = result.message
    if (!result.ok) detailError.value = result.message
    await reload()
    await refreshReportDetail()
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '归档结论失败'
  } finally {
    detailBusy.value = false
  }
}

function linkForMaterial(material: MaterialRef): { path: string; query: Record<string, string> } {
  const rawQuery = (material.link_query ?? material.route_query ?? {}) as Record<string, unknown>
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(rawQuery)) {
    if (value !== undefined && value !== null && value !== '') query[key] = String(value)
  }
  return {
    path: String(material.link_path ?? material.route_path ?? `/significance_test`),
    query,
  }
}

onMounted(async () => {
  await reload()
  await nextTick()
  if (route.query.new === '1') openCreate()
  if (focusId.value !== null) {
    const row = rows.value.find((item) => Number(item.id) === focusId.value)
    if (meta.key === 'report_gen' && row) {
      await openReportDetail(row)
    } else if (meta.key === 'exp_archive' && row) {
      await openArchiveDetail(row)
    } else {
      document.querySelector(`[data-testid="row-${focusId.value}"]`)?.scrollIntoView({
        block: 'center',
        behavior: 'smooth',
      })
    }
  }
})
</script>
