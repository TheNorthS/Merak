import { normalizeGateComponentStatuses, toWorkflowCompletion, type ResumableState } from './workflowViewModels'
import { selectedNodeIdsFromRunState, toNodeStatus } from './workflowResume'
import { normalizeRevisionDecisionBrief } from './workflowRevisionUi'
import type { WorkflowSocketContext } from './workflowSocket'

const HANDLED_EVENTS = new Set(["agent_output","agent_step","agent_tool_call","agent_tool_result","agent_error","agent_status","checkpoint_waiting","checkpoint_extended","checkpoint_resumed","checkpoint_auto_resumed","code_review_started","code_review_completed","workflow_completed","workflow_incomplete","workflow_failed","workflow_error","workflow_cancelled","workflow_interrupted"])

export function handleTerminalWorkflowEvent(msg: Record<string, any>, context: WorkflowSocketContext): boolean | undefined {
  if (!HANDLED_EVENTS.has(String(msg.type || ''))) return false
  const { currentRunIdRef, flushAgentOutput, setPausedRunIdSafe, setNodes, addLog, updatePaperStage, setCheckpointNode, revisionLimitCheckpointRef, setCheckpointActionError, queueAgentOutput, handledCheckpointIdsRef, checkpointFeedbackRef, setCheckpointFeedback, startCheckpointCountdown, setWorkflowCompletion, setIsRunning, setIsResuming, setActiveRunId, closeWorkflowWs, setResumableState } = context
if (['workflow_error', 'workflow_cancelled', 'workflow_interrupted'].includes(msg.type) && msg.nodes_status) {
    const recoveryState: ResumableState = {
      run_id: String(msg.run_id || currentRunIdRef.current || ''),
      current_node: String(msg.current_node || ''), nodes_status: msg.nodes_status,
      config: msg.config || undefined,
    }
    setResumableState(recoveryState)
    setNodes(prev => prev.map(node => ({ ...node, status: toNodeStatus(recoveryState.nodes_status[node.id]) })))
  }
  if (msg.type === 'agent_output') {
    queueAgentOutput(msg.text || '')
  } else if (msg.type === 'agent_step') {
    flushAgentOutput()
    if (msg.paper_stage) {
      updatePaperStage(String(msg.paper_stage), {
        agentStatus: String(msg.title || msg.kind || '正在处理章节'),
      })
    } else {
      const detail = msg.detail ? `：${msg.detail}` : ''
      addLog('Agent', `${msg.title || msg.kind || 'Step'}${detail}`, 'agent')
    }
  } else if (msg.type === 'agent_tool_call') {
    flushAgentOutput()
    if (msg.paper_stage) {
      updatePaperStage(String(msg.paper_stage), {
        agentStatus: `${String(msg.tool || '工具')}处理中`,
      })
    } else {
      addLog('Tool', `${msg.tool}(${String(msg.args || '').slice(0, 160)})`, 'tool')
    }
  } else if (msg.type === 'agent_tool_result') {
    flushAgentOutput()
    if (msg.paper_stage) {
      updatePaperStage(String(msg.paper_stage), {
        agentStatus: msg.success === false
          ? `${String(msg.tool || '工具')}执行失败，正在处理`
          : `${String(msg.tool || '工具')}已完成`,
      })
    } else {
      const mark = msg.success === false ? '✗' : '↩'
      addLog('Tool', `${mark} ${msg.tool}: ${String(msg.output || '').slice(0, 240)}`, msg.success === false ? 'warn' : 'tool')
    }
    if (msg.tool === 'Write' || msg.tool === 'Edit' || msg.tool === 'generate_figure') {
      window.dispatchEvent(new Event('merak-ide:files-changed'))
    }
  } else if (msg.type === 'agent_error') {
    flushAgentOutput()
    addLog('System', `Agent error: ${msg.error || ''}`, 'error')
  } else if (msg.type === 'agent_status') {
    if (msg.status === 'iteration_budget') addLog('System', `本轮模型步骤剩余 ${msg.iterations_remaining}，请等待当前尝试结束及产物验收。`, 'warn')
    if (msg.status === 'thinking') addLog('Agent', '思考中...', 'agent')
    if (msg.status === 'switching_provider') addLog('Agent', `切换模型: ${msg.to || msg.model || ''}`, 'agent')
    if (msg.status === 'retrying_provider') addLog('System', `模型请求重试 ${msg.next_attempt || msg.attempt}/${msg.max_attempts}；${msg.retry_in_seconds}s 后重试，总预算剩余 ${msg.remaining_seconds}s`, 'warn')
    if (['waiting_model', 'streaming_model'].includes(msg.status) && msg.elapsed) addLog('System', `${msg.status === 'streaming_model' ? '正在接收模型输出' : '等待模型响应'}：本次 ${msg.elapsed}s，第 ${msg.attempt || 1}/${msg.max_attempts || 1} 次尝试，本次截止剩余 ${msg.attempt_remaining_seconds ?? msg.remaining_seconds ?? '?'}s，总预算剩余 ${msg.remaining_seconds ?? '?'}s`, 'info')
    if (msg.status === 'partial_stream_interrupted') addLog('System', '模型流已中断；已有输出保留，停止后可手动恢复', 'warn')
  } else if (msg.type === 'checkpoint_waiting') {
    flushAgentOutput()
    setCheckpointActionError('')
    const checkpointId = String(
      msg.checkpoint_id || `${msg.run_id || currentRunIdRef.current}:${msg.node_id}:human`,
    )
    if (handledCheckpointIdsRef.current.has(checkpointId)) return
    handledCheckpointIdsRef.current.add(checkpointId)
    const isRevision = msg.checkpoint_kind === 'research_revision'
    const checkpointIssues = Array.isArray(msg.issues)
      ? msg.issues.map((item: unknown) => String(item))
      : []
    addLog('System', `人工检查点: 可为 ${msg.name || msg.node_id} 输入调整意见，超时将自动继续`, 'warn')
    const timeoutSeconds = Number(msg.timeout_seconds || 300)
    setCheckpointNode({
      id: msg.node_id || '',
      name: msg.name || msg.node_id || '下一节点',
      timeoutSeconds,
      kind: isRevision ? 'research_revision' : 'node',
      revisionRound: Number(msg.revision_round || 0),
      revisionCycle: Number(msg.revision_cycle || 0),
      summary: String(msg.summary || msg.reason || ''),
      issues: checkpointIssues,
      score: msg.score != null ? Number(msg.score) : undefined,
      threshold: msg.threshold != null ? Number(msg.threshold) : undefined,
      reportPath: String(msg.report_path || ''),
      persisted: false,
      componentStatuses: normalizeGateComponentStatuses(msg.component_statuses),
      interventionKind: isRevision ? 'researcher_decision' : 'platform_repair',
      requiresHumanDecision: true,
      decisionBrief: isRevision
        ? normalizeRevisionDecisionBrief(msg.decision_brief, {
            nodeId: String(msg.node_id || ''),
            nodeName: String(msg.name || msg.node_id || '当前节点'),
            round: Number(msg.revision_round || 0),
            maxRounds: Number(msg.max_revision_rounds || msg.revision_round || 1),
            summary: String(msg.summary || msg.reason || ''),
            issues: checkpointIssues,
          })
        : undefined,
    })
    checkpointFeedbackRef.current = ''
    setCheckpointFeedback('')
    setPausedRunIdSafe(msg.run_id || currentRunIdRef.current)
    startCheckpointCountdown(timeoutSeconds)
  } else if (msg.type === 'checkpoint_extended') {
    const remainingSeconds = Number(msg.remaining_seconds || 300)
    setCheckpointNode(prev => prev ? { ...prev, timeoutSeconds: remainingSeconds } : prev)
    startCheckpointCountdown(remainingSeconds)
    addLog('System', `人工检查点已延长 ${Math.ceil(Number(msg.added_seconds || 300) / 60)} 分钟`, 'info')
  } else if (msg.type === 'checkpoint_resumed') {
    flushAgentOutput()
    setPausedRunIdSafe(null)
    addLog('System', msg.has_feedback ? '已提交人工调整意见，继续执行' : '已继续执行', 'info')
  } else if (msg.type === 'checkpoint_auto_resumed') {
    flushAgentOutput()
    setPausedRunIdSafe(null)
    addLog('System', '人工检查点超时，已自动继续执行', 'info')
  } else if (msg.type === 'code_review_started') {
    addLog('Agent', '代码审查中...', 'agent')
  } else if (msg.type === 'code_review_completed') {
    addLog('Agent', '代码审查完成', 'agent')
  } else if (msg.type === 'workflow_completed') {
    flushAgentOutput()
    const completion = toWorkflowCompletion(msg)
    setWorkflowCompletion(completion)
    setIsRunning(false)
    setIsResuming(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    closeWorkflowWs()
    if (completion.submission_ready) {
      addLog(
        'System',
        completion.submission_advisories.length > 0
          ? `流程执行完成；投稿候选稿已就绪，仍有 ${completion.submission_advisories.length} 项作者复核提醒。`
          : '流程执行完成；证据、独立审稿、五层审计、独立证明审计和编译均通过，可作为投稿候选稿。',
        completion.submission_advisories.length > 0 ? 'warn' : 'info',
      )
    } else if (completion.completion_class === 'reviewable_draft_ready') {
      addLog('System', '可审查草稿流程已完成；审稿分数、科学限制和待补实验证据均保留，当前不可作为投稿候选稿。', 'warn')
    } else if (completion.completion_class === 'synthetic_preview_ready') {
      addLog('System', '流程执行完成：完整仿真研究论文已生成；平台投稿资格仍保持隔离，需作者按目标期刊要求复核方法披露与证据类型。', 'warn')
    } else if (completion.completion_class === 'protocol_ready') {
      addLog('System', '流程执行完成：研究方案稿已生成，实证证据尚未形成，当前不可投稿。', 'warn')
    } else {
      addLog('System', `流程执行完成，但投稿门仍有 ${completion.submission_blockers.length} 项未通过。`, 'warn')
    }
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'workflow_incomplete') {
    flushAgentOutput()
    const pendingNodes = Array.isArray(msg.pending_nodes) ? msg.pending_nodes.map(String) : []
    const recoveryRunId = String(msg.run_id || currentRunIdRef.current || '')
    const recoveryState: ResumableState = {
      run_id: recoveryRunId,
      current_node: String(msg.current_node || pendingNodes[0] || ''),
      nodes_status: msg.nodes_status || {},
      config: msg.config || undefined,
      auto_rebuild_required: msg.auto_rebuild_required || null,
    }
    setIsRunning(false)
    setIsResuming(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    setResumableState(recoveryState)
    const selectedNodeIds = selectedNodeIdsFromRunState(recoveryState)
    setNodes(prev => prev.map(node => ({
      ...node,
      selected: selectedNodeIds.has(node.id),
      status: Object.prototype.hasOwnProperty.call(recoveryState.nodes_status, node.id)
        ? toNodeStatus(recoveryState.nodes_status[node.id])
        : node.status,
    })))
    if (revisionLimitCheckpointRef.current) {
      setCheckpointNode(revisionLimitCheckpointRef.current)
      setPausedRunIdSafe(recoveryRunId)
      revisionLimitCheckpointRef.current = null
    }
    closeWorkflowWs()
    addLog('System', `本次执行已结束，仍有 ${pendingNodes.length} 个节点待恢复`, 'warn')
  } else if (msg.type === 'workflow_failed') {
    flushAgentOutput()
    const recoveryRunId = String(msg.run_id || currentRunIdRef.current || '')
    if (recoveryRunId && msg.nodes_status) {
      const pendingNodes = Array.isArray(msg.pending_nodes) ? msg.pending_nodes.map(String) : []
      const recoveryState: ResumableState = {
        run_id: recoveryRunId,
        current_node: String(msg.current_node || pendingNodes[0] || ''),
        nodes_status: msg.nodes_status,
        config: msg.config || undefined,
        auto_rebuild_required: msg.auto_rebuild_required || null,
      }
      setResumableState(recoveryState)
      const selectedNodeIds = selectedNodeIdsFromRunState(recoveryState)
      setNodes(prev => prev.map(node => ({
        ...node,
        selected: selectedNodeIds.has(node.id),
        status: Object.prototype.hasOwnProperty.call(recoveryState.nodes_status, node.id)
          ? toNodeStatus(recoveryState.nodes_status[node.id])
          : node.status,
      })))
    }
    setIsRunning(false)
    setIsResuming(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    closeWorkflowWs()
    addLog('System', `工作流失败: ${(msg.failed_nodes || []).join(', ')}；断点已保留`, 'error')
  } else if (msg.type === 'workflow_error') {
    flushAgentOutput()
    setIsRunning(false)
    setIsResuming(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    closeWorkflowWs()
    addLog('System', `错误: ${msg.error}`, 'error')
  } else if (msg.type === 'workflow_cancelled' || msg.type === 'workflow_interrupted') {
    flushAgentOutput()
    setIsRunning(false)
    setIsResuming(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    closeWorkflowWs()
    addLog('System', '工作流已停止；产物和断点已保留，可手动恢复', 'warn')
  }
  return true
}
