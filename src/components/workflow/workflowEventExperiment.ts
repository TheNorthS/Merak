import type { WorkflowSocketContext } from './workflowSocket'

const HANDLED_EVENTS = new Set(["experiment_phase","experiment_launched","experiment_reattached","experiment_preflight","experiment_provider_selected","experiment_log","experiment_resources","experiment_heartbeat","experiment_anomaly","experiment_finished","experiment_failed","job_stopping","job_attention_required","experiment_adjustment_proposed","experiment_adjustment_resolved","job_retrying","experiment_provider_cleanup","node_agent_watchdog_heartbeat","node_transport_heartbeat"])

export function handleExperimentWorkflowEvent(msg: Record<string, any>, context: WorkflowSocketContext): boolean | undefined {
  if (!HANDLED_EVENTS.has(String(msg.type || ''))) return false
  const { addLog, runtimeRunIdRef, runtimeLogOffsetRef, setExperimentMonitor, experimentLogLastEmitRef, setApprovalDialogOpen } = context
if (msg.type === 'experiment_phase') {
    const phaseLabels: Record<string, string> = {
      precheck: '环境预检', snapshot: '固定代码快照', sync: '同步并校验文件',
      launch: '启动进程', monitor: '实时监控', healthy: '运行正常',
      collect: '回收结果', stopping: '安全停止',
    }
    const phase = String(msg.phase || '')
    const runtimeRunId = String(msg.experiment_run_id || '')
    if (runtimeRunId && runtimeRunId !== runtimeRunIdRef.current) {
      runtimeRunIdRef.current = runtimeRunId
      runtimeLogOffsetRef.current = 0
    }
    setExperimentMonitor(prev => ({
      ...prev,
      active: true,
      backend: String(msg.backend || prev.backend),
      phase,
      experimentId: String(msg.experiment_id || prev.experimentId),
      jobId: String(msg.job_id || prev.jobId),
      runtimeRunId: String(msg.experiment_run_id || prev.runtimeRunId),
    }))
    addLog('Experiment', `${String(msg.backend || 'runner')} · ${phaseLabels[phase] || phase}`, 'tool')
  } else if (msg.type === 'experiment_launched') {
    const runtimeRunId = String(msg.experiment_run_id || '')
    if (runtimeRunId && runtimeRunId !== runtimeRunIdRef.current) {
      runtimeRunIdRef.current = runtimeRunId
      runtimeLogOffsetRef.current = 0
    }
    setExperimentMonitor(prev => ({
      ...prev,
      active: true,
      backend: String(msg.backend || prev.backend),
      phase: 'monitor',
      experimentId: String(msg.experiment_id || prev.experimentId),
      jobId: String(msg.job_id || prev.jobId),
      runtimeRunId: String(msg.experiment_run_id || prev.runtimeRunId),
    }))
    addLog('Experiment', `已启动 attempt ${String(msg.attempt || 1)}；日志 ${String(msg.log_path || '')}`, 'tool')
  } else if (msg.type === 'experiment_reattached') {
    const runtimeRunId = String(msg.experiment_run_id || '')
    if (runtimeRunId) runtimeRunIdRef.current = runtimeRunId
    setExperimentMonitor(prev => ({
      ...prev,
      active: true,
      backend: String(msg.backend || prev.backend),
      phase: 'monitor',
      runtimeRunId: runtimeRunId || prev.runtimeRunId,
    }))
    addLog('Experiment', `已重新附着远程 attempt ${String(msg.attempt || 1)}，不会重复启动训练`, 'tool')
  } else if (msg.type === 'experiment_preflight') {
    addLog('Experiment', msg.success ? `预检通过 · ${String(msg.log_path || '')}` : `预检失败 · ${String(msg.log_path || '')}`, msg.success ? 'tool' : 'error')
  } else if (msg.type === 'experiment_provider_selected') {
    const cost = msg.maximum_cost_usd != null ? `，预算上限 $${Number(msg.maximum_cost_usd).toFixed(2)}` : ''
    addLog('Experiment', `${String(msg.backend || '')} 已选择 ${String(msg.gpu || 'GPU')} @ $${Number(msg.hourly_usd || 0).toFixed(3)}/h${cost}`, 'tool')
  } else if (msg.type === 'experiment_log') {
    const metrics = msg.metrics && typeof msg.metrics === 'object' ? msg.metrics : {}
    setExperimentMonitor(prev => ({ ...prev, metrics }))
    const now = Date.now()
    if (now - experimentLogLastEmitRef.current > 2500) {
      const raw = String(msg.text || '').trim().split(/\r?\n/).filter(Boolean).pop() || ''
      if (raw) addLog('Train', raw.slice(0, 500), 'info')
      experimentLogLastEmitRef.current = now
    }
  } else if (msg.type === 'experiment_resources') {
    const gpus = Array.isArray(msg.gpus) ? msg.gpus : []
    setExperimentMonitor(prev => ({ ...prev, gpus }))
  } else if (msg.type === 'experiment_heartbeat') {
    const elapsed = Math.max(0, Number(msg.elapsed_seconds || 0))
    setExperimentMonitor(prev => ({
      ...prev,
      active: true,
      backend: String(msg.backend || prev.backend),
      phase: 'healthy',
    }))
    addLog(
      'Experiment',
      `${String(msg.backend || 'runtime')} attempt ${String(msg.attempt || 1)} 仍在运行（${Math.floor(elapsed / 60)}m ${Math.floor(elapsed % 60)}s，无新标准输出）`,
      'info',
    )
  } else if (msg.type === 'experiment_anomaly') {
    const finding = msg.finding || {}
    const message = `${String(finding.kind || 'anomaly')}: ${String(finding.message || '')}`
    setExperimentMonitor(prev => ({ ...prev, anomaly: message, phase: msg.auto_stop ? 'stopping' : prev.phase }))
    addLog('Monitor', `${msg.auto_stop ? '自动止损 · ' : ''}${message}`, msg.auto_stop ? 'error' : 'warn')
  } else if (msg.type === 'experiment_finished') {
    const runtimeRunId = String(msg.experiment_run_id || '')
    if (runtimeRunId) runtimeRunIdRef.current = runtimeRunId
    setExperimentMonitor(prev => ({
      ...prev,
      active: false,
      phase: String(msg.status || 'finished'),
      experimentId: String(msg.experiment_id || prev.experimentId),
      jobId: String(msg.job_id || prev.jobId),
      runtimeRunId: runtimeRunId || prev.runtimeRunId,
      diagnosisPath: String(msg.diagnosis_path || prev.diagnosisPath),
      manifestPath: String(msg.manifest_path || prev.manifestPath),
    }))
    addLog('Experiment', `${String(msg.status || 'finished')}；结果 ${String(msg.result_path || '未生成')}；清单 ${String(msg.manifest_path || '')}`, msg.status === 'completed' ? 'tool' : 'error')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'experiment_failed') {
    setExperimentMonitor(prev => ({
      ...prev,
      active: false,
      phase: 'failed',
      experimentId: String(msg.experiment_id || prev.experimentId),
      jobId: String(msg.job_id || prev.jobId),
      diagnosisPath: String(msg.diagnosis_path || prev.diagnosisPath),
    }))
    addLog('Experiment', `${String(msg.error || '远程实验失败')}；诊断 ${String(msg.diagnosis_path || '')}`, 'error')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'job_stopping') {
    setExperimentMonitor(prev => ({ ...prev, active: true, phase: 'stopping' }))
    addLog('Experiment', `正在安全停止 ${String(msg.job_id || '')}，随后回收日志和结果`, 'warn')
  } else if (msg.type === 'job_attention_required') {
    setExperimentMonitor(prev => ({
      ...prev,
      active: false,
      phase: 'awaiting_approval',
      experimentId: String(msg.experiment_id || prev.experimentId),
      jobId: String(msg.job_id || prev.jobId),
      diagnosisPath: String(msg.diagnosis_path || prev.diagnosisPath),
      proposalId: String(msg.proposal_id || prev.proposalId),
      proposalStatus: 'pending',
    }))
    addLog('Experiment', String(msg.reason || '实验需要人工审查后才能重试'), 'warn')
  } else if (msg.type === 'experiment_adjustment_proposed') {
    const decisionBrief = msg.decision_brief && typeof msg.decision_brief === 'object'
      ? msg.decision_brief
      : {}
    setExperimentMonitor(prev => ({
      ...prev,
      active: false,
      phase: 'awaiting_approval',
      experimentId: String(msg.experiment_id || prev.experimentId),
      jobId: String(msg.job_id || prev.jobId),
      proposalId: String(msg.proposal_id || ''),
      proposalStatus: 'pending',
      proposalSummary: String(msg.summary || ''),
      proposalRationale: String(msg.rationale || ''),
      proposalChanges: msg.changes && typeof msg.changes === 'object' ? msg.changes : {},
      proposalTrigger: String(decisionBrief.trigger || msg.source || 'runtime_monitor'),
      proposalImpact: String(decisionBrief.research_impact || ''),
      proposalQuestion: String(decisionBrief.approval_question || ''),
      proposalActions: Array.isArray(decisionBrief.proposed_action)
        ? decisionBrief.proposed_action.map((item: unknown) => String(item))
        : [],
      proposalRisks: Array.isArray(decisionBrief.risks)
        ? decisionBrief.risks.map((item: unknown) => String(item))
        : [],
      proposalPath: String(msg.proposal_path || ''),
    }))
    setApprovalDialogOpen(true)
    addLog('Experiment', `待审批调整：${String(msg.summary || msg.proposal_id || '')}`, 'warn')
  } else if (msg.type === 'experiment_adjustment_resolved') {
    setExperimentMonitor(prev => ({
      ...prev,
      proposalStatus: msg.approved ? 'approved' : 'rejected',
      phase: msg.approved ? 'ready_to_retry' : 'failed',
    }))
    setApprovalDialogOpen(false)
    addLog('Experiment', msg.approved ? '调整提案已批准，可以创建新 attempt' : '调整提案已拒绝', msg.approved ? 'info' : 'warn')
  } else if (msg.type === 'job_retrying') {
    setExperimentMonitor(prev => ({
      ...prev,
      active: true,
      phase: 'queued',
      proposalStatus: '',
      anomaly: '',
    }))
    addLog('Experiment', `已排队 attempt ${String(msg.next_attempt || '?')}，旧 attempt 保持只读`, 'tool')
  } else if (msg.type === 'experiment_provider_cleanup') {
    addLog('Experiment', msg.destroyed ? `Vast.ai 实例 ${String(msg.instance_id)} 已销毁` : `Vast.ai 实例 ${String(msg.instance_id)} 销毁失败，请立即检查计费`, msg.destroyed ? 'info' : 'error')
  } else if (msg.type === 'node_agent_watchdog_heartbeat') {
    addLog(
      'System',
      `${String(msg.node_id || '节点')} 会话累计 ${Math.floor(Number(msg.elapsed_seconds || 0))}s；距上次有效活动 ${Math.floor(Number(msg.idle_seconds || 0))}s（状态心跳）`,
      'info',
    )
  } else if (msg.type === 'node_transport_heartbeat') {
    addLog(
      'System',
      `${String(msg.node_id || '节点')} 正在等待模型服务重试（${Math.floor(Number(msg.remaining_delay_seconds || 0))}s 后继续）`,
      'warn',
    )
  }
  return true
}
