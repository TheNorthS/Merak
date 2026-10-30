import type { WorkflowSocketContext } from './workflowSocket'

export function handleReportRevision(msg: Record<string, unknown>, context: WorkflowSocketContext): boolean {
  const type = String(msg.type || '')
  if (!['report_revision_started', 'report_revision_progress', 'report_revision_verifying', 'report_revision_waiting'].includes(type)) return false
  const nodeId = String(msg.node_id || '')
  const label = type === 'report_revision_started' ? '定向修订中'
    : type === 'report_revision_waiting' ? '修订待处理'
      : type === 'report_revision_verifying' || msg.status === 'impact_review' ? '修改后待复核' : '定向修订中'
  const affected = Array.isArray(msg.affected_nodes) ? msg.affected_nodes.map(String) : []
  context.setNodes(previous => previous.map(node => node.id === nodeId
    ? { ...node, validationLabel: label, status: type === 'report_revision_waiting' ? 'idle' : 'running' }
    : affected.includes(node.id) ? { ...node, status: 'idle', validationLabel: '已有产物待复核' } : node))
  if (type !== 'report_revision_progress' || msg.status === 'editing') {
    context.addLog('System', String(msg.message || `${nodeId}：${label}，责任节点 ${msg.owner_node || ''}`),
      type === 'report_revision_waiting' ? 'warn' : 'info')
  }
  return true
}
