import { API_BASE } from '../../config'

export async function evidenceVersionApproval(projectPath: string, runId: string): Promise<Record<string, string> | null | undefined> {
  const response = await fetch(`${API_BASE}/api/workflow/runs/${encodeURIComponent(runId)}/evidence-version-plan?project_path=${encodeURIComponent(projectPath)}`)
  if (!response.ok) throw new Error('无法读取证据版本计划，请重试')
  const plan = await response.json()
  if (!plan.required) return undefined
  const sources = Array.isArray(plan.changed_sources) ? plan.changed_sources.join('\n') : ''
  const explanation = plan.prior_identity_known ? '变化来源' : '原版本缺少逐来源指纹，以下输入需重新核对'
  if (!confirm(`现有证据已过期。${explanation}：\n${sources}\n\n是否在恢复后的检查通过后创建新证据版本？旧证据会归档保留，生成失败不替换现有文件。`)) return null
  return { input_sha256: String(plan.input_sha256), manifest_sha256: String(plan.manifest_sha256) }
}
