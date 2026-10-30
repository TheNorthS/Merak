/** Scheduled retries must be explicitly present; exhausted transport defaults to manual resume. */
export function transportRecoveryNotice(message: Record<string, unknown>): string {
  if (!message.transport_exhausted) return ''
  const attempt = Number(message.transport_retry_count || 0) + 1
  const limit = Number(message.max_transport_checkpoint_retries || 0)
  const delay = Number(message.retry_delay_seconds || 0)
  if (message.manual_resume_required !== true && limit >= attempt && delay > 0) {
    return `；后台将在约 ${Math.ceil(delay)} 秒后进行第 ${attempt}/${limit} 个恢复周期`
  }
  return '；本次执行已停止，请检查模型连接后手动恢复'
}
