import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

async function getJson<T>(url: string): Promise<T> {
  const response = await request(url)
  if (!response.ok) throw new Error('关联资料读取失败')
  return await response.json() as T
}

export type MaterialRef = {
  ref_id?: string
  material_type?: string
  module?: string
  type?: string
  类型?: string
  row_id?: number | string
  编号?: string
  材料编号?: string
  实验编码?: string
  status?: string
  状态?: string
  label?: string
  detail?: Record<string, unknown>
  明细?: Record<string, unknown>
  link_path?: string
  link_query?: Record<string, string | number | undefined>
  [key: string]: unknown
}

export type ReportMaterials = {
  ok: boolean
  message?: string
  摘要?: string
  结论条数?: number | string
  检验条数?: number
  归因条数?: number
  materials?: MaterialRef[]
  结论依据?: MaterialRef[]
  archives?: { id: number; archive_id?: number; status?: string; [key: string]: unknown }[]
  关联归档?: { id: number; archive_id?: number; status?: string; [key: string]: unknown }[]
  [key: string]: unknown
}

export type ArchiveBasis = {
  ok: boolean
  message?: string
  结论条数?: number | string
  依据状态?: string
  恢复准备状态?: string
  materials?: MaterialRef[]
  结论依据?: MaterialRef[]
  missing?: MaterialRef[]
  缺项?: MaterialRef[]
  恢复历史?: Record<string, unknown>[]
  [key: string]: unknown
}

export function getReportSummary(id: number): Promise<ReportMaterials> {
  return getJson<ReportMaterials>(`/api/report_gen/${id}/summary`)
}

export function getReportMaterials(id: number): Promise<ReportMaterials> {
  return getJson<ReportMaterials>(`/api/report_gen/${id}/materials`)
}

export function getArchiveBasis(id: number): Promise<ArchiveBasis> {
  return getJson<ArchiveBasis>(`/api/exp_archive/${id}/basis`)
}

export async function claimArchiveBasis(id: number): Promise<ActionResult> {
  const response = await request(`/api/exp_archive/${id}/claim`, { method: 'POST' })
  return await response.json()
}

export async function restoreArchiveBasis(id: number): Promise<ActionResult> {
  const response = await request(`/api/exp_archive/${id}/restore`, { method: 'POST' })
  return await response.json()
}

export async function generateReportNow(id: number): Promise<ActionResult> {
  const response = await request(`/api/report_gen/${id}/generate`, { method: 'POST' })
  return await response.json()
}

export async function archiveReportNow(id: number): Promise<ActionResult> {
  const response = await request(`/api/report_gen/${id}/archive_finished`, { method: 'POST' })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}
