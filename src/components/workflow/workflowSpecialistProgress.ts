import type { WorkflowSocketContext } from './workflowSocket'

export function handleSpecialistProgress(msg: Record<string, unknown>, context: WorkflowSocketContext): boolean {
  if (msg.type !== 'specialist_node_progress') return false
  const status = String(msg.status || '')
  if (status !== 'waiting_model' && status !== 'retrying_provider') return true
  const name = String(msg.name || msg.subnode_id || '专家子节点')
  const attempt = msg.next_attempt ?? msg.attempt ?? '?'
  const action = status === 'retrying_provider'
    ? `模型请求重试，${msg.retry_in_seconds ?? '?'}s 后继续`
    : `等待模型响应，本次 ${msg.elapsed ?? 0}s`
  context.addLog('System', `${name}：${action}，第 ${attempt}/${msg.max_attempts ?? '?'} 次请求，总预算剩余 ${msg.remaining_seconds ?? '?'}s`,
    status === 'retrying_provider' ? 'warn' : 'info')
  return true
}
