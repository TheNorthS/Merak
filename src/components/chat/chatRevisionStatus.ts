import type { ChangeProposal } from './chatTypes'

export function appliedRevisionStatus(impact: ChangeProposal['impact']): string {
  if (impact?.completed_runs?.length) return '局部修改已保存；已完成工作流保持不变'
  if (impact?.affected_runs?.length) return '修改已应用；未完成流程可由你手动恢复'
  return '修改已应用'
}
