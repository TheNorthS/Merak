import type { WorkflowCheckpoint } from './workflowContext'
import { PAPER_STAGE_DEFINITIONS, normalizeGateComponentStatuses, toSpecialistNodeProgress, type WorkflowNode, type SpecialistNodeProgress } from './workflowViewModels'
import { normalizeRevisionDecisionBrief } from './workflowRevisionUi'
import { useWorkspaceStore } from '../../stores/workspace'
import type { WorkflowSocketContext } from './workflowSocket'
import { handleSpecialistProgress } from './workflowSpecialistProgress'
import { transportRecoveryNotice } from './workflowTransportNotice'
import { handleReportRevision } from './workflowReportRevision'

const HANDLED_EVENTS = new Set(["node_started","node_dependency_reused","implementation_stage_started","implementation_stage_accepted","implementation_stage_needs_revision","implementation_stage_reused","skill_plan_selected","specialist_plan_ready","specialist_node_started","specialist_node_completed","specialist_node_reused","specialist_node_failed","specialist_stage_incomplete","runtime_execution_started","runtime_execution_completed","runtime_execution_failed","skill_invocation_started","skill_invocation_completed","skill_invocation_recovered","skill_invocation_progress","skill_invocation_reused","paper_stage_started","paper_stage_reviewed","paper_stage_reused","paper_stage_agent_status","skill_invocation_revision_required","skill_invocation_failed","node_completed","node_accepted","node_revision_started","owner_acceptance_revoked","node_revision_completed","node_revision_no_progress","source_integrity_repaired","node_preparation_deferred","upstream_owner_revalidated","narrative_artifact_recovered","deterministic_compile_completed","slide_artifact_recovered","node_revision_gate","node_quality_advisory","workflow_risk_snapshot","node_platform_auto_recovery_started","node_platform_repair_required","node_revision_waiting","node_revision_error","node_blocked","node_failed","node_skipped","node_tool_fallback","node_recovered","exp_design_depth_repaired","node_artifact_canonicalized","figure_artifact_failed","figure_artifact_generated","planned_result_templates_generated","patent_search_completed","knowledge_sources_collected","overleaf_sync_started","overleaf_sync_result","notification_delivery","notification_configuration_required","meta_optimization_observed","paper_page_target_missed","paper_length_revision_started","paper_length_revision_completed","paper_artifact_repaired","specialist_stage_incomplete"])

HANDLED_EVENTS.add('paper_print_layout_repaired')
HANDLED_EVENTS.add('implementation_stage_progress')
HANDLED_EVENTS.add('implementation_stage_budget_exhausted')

export function handleCoreWorkflowEvent(msg: Record<string, any>, context: WorkflowSocketContext): boolean | undefined {
  if (handleReportRevision(msg, context)) return true
  if (handleSpecialistProgress(msg, context)) return true
  if (!HANDLED_EVENTS.has(String(msg.type || ''))) return false
  const { eventRunId, flushAgentOutput, pausedRunIdRef, setPausedRunIdSafe, setNodes, addLog, setSpecialistNodes, updatePaperStage, setCheckpointNode, revisionLimitCheckpointRef, setCheckpointActionError, formatGateNumber } = context
if (msg.type === 'node_started') {
    flushAgentOutput()
    if (pausedRunIdRef.current && (!eventRunId || pausedRunIdRef.current === eventRunId)) {
      setPausedRunIdSafe(null)
    }
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'running' } : n))
    addLog('Agent', `Running: ${msg.name || msg.node_id}`, 'agent')
  } else if (msg.type === 'node_dependency_reused') {
    addLog(
      'System',
      `${String(msg.node_id || '当前节点')} 已复用并重新验收现存上游产物：${String(msg.dependency_id || '')}`,
      'info',
    )
  } else if (msg.type === 'implementation_stage_budget_exhausted') {
    addLog('System', `实验实现阶段 ${msg.stage_id}：步骤预算已用完，正在验收已保存文件。`, 'warn')
  } else if (msg.type === 'implementation_stage_progress') {
    const request = msg.model_request || {}
    const stage = String(msg.stage_id || '')
    if (msg.status === 'iteration_budget') {
      addLog('System', `实验实现阶段 ${stage}：本轮模型步骤剩余 ${request.iterations_remaining}，即将转入产物验收。`, 'warn')
    } else if (msg.status === 'retrying_provider') {
      addLog('System', `实验实现阶段 ${stage}：模型请求重试 ${request.next_attempt ?? request.attempt}/${request.max_attempts}；${request.retry_in_seconds}s 后重试，总预算剩余 ${request.remaining_seconds}s`, 'warn')
    } else if (msg.status === 'waiting_model' || msg.status === 'streaming_model') {
      addLog('System', `实验实现阶段 ${stage}：${msg.status === 'streaming_model' ? '正在接收模型输出' : '等待模型响应'}，本次 ${request.elapsed ?? 0}s，第 ${request.attempt ?? 1}/${request.max_attempts ?? 1} 次尝试，本次截止剩余 ${request.attempt_remaining_seconds ?? request.remaining_seconds ?? '?'}s，总预算剩余 ${request.remaining_seconds ?? '?'}s`, 'info')
    }
  } else if (msg.type === 'implementation_stage_started') {
    const attempt = msg.attempt && msg.max_attempts
      ? `（尝试 ${String(msg.attempt)}/${String(msg.max_attempts)}）`
      : ''
    const issues = Array.isArray(msg.issues) && msg.issues.length
      ? `；待修复：${String(msg.issues[0])}`
      : ''
    addLog(
      'Agent',
      `实验实现阶段 ${String(msg.stage_id || '')}：开始 ${String(msg.title || '')}${attempt}${issues}`,
      'agent',
    )
  } else if (msg.type === 'implementation_stage_accepted') {
    addLog(
      'Agent',
      `实验实现阶段 ${String(msg.stage_id || '')}：验收通过`,
      'info',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'implementation_stage_needs_revision') {
    const issues = Array.isArray(msg.issues) && msg.issues.length
      ? `；${String(msg.issues[0])}`
      : ''
    addLog(
      'System',
      `实验实现阶段 ${String(msg.stage_id || '')}：需要修订（尝试 ${String(msg.attempt || '?')}）${issues}`,
      'warn',
    )
  } else if (msg.type === 'implementation_stage_reused') {
    addLog(
      'Agent',
      `实验实现阶段 ${String(msg.stage_id || '')}：复用已验收产物`,
      'info',
    )
  } else if (msg.type === 'skill_plan_selected') {
    const executionKind = String(msg.execution_kind || 'model_owned') as WorkflowNode['executionKind']
    setNodes(prev => prev.map(node => node.id === String(msg.node_id || '')
      ? {
          ...node,
          executionKind,
          ownerSkill: String(msg.primary || ''),
          runtimeService: String(msg.runtime_service || ''),
        }
      : node))
    const specialists = Array.isArray(msg.specialists) ? msg.specialists.join(', ') : ''
    const validators = Array.isArray(msg.validators) ? msg.validators.join(', ') : ''
    const runtimeService = String(msg.runtime_service || '')
    const ownerText = executionKind === 'runtime_owned'
      ? `运行时执行: ${runtimeService || 'workflow runtime'}（该路径不加载模型 skill）`
      : executionKind === 'hybrid'
        ? `混合执行: /${msg.primary || 'stage-owner'} + ${runtimeService || 'runtime validator'}`
        : `模型执行: /${msg.primary || 'stage-owner'}`
    addLog(
      'Agent',
      `${ownerText}${specialists ? `；按需候选: ${specialists}` : ''}${validators ? `；后续校验: ${validators}` : ''}`,
      'agent',
    )
  } else if (msg.type === 'specialist_plan_ready') {
    const profile = msg.profile && typeof msg.profile === 'object' ? msg.profile : {}
    const subnodes = Array.isArray(msg.subnodes) ? msg.subnodes : []
    setSpecialistNodes(
      subnodes
        .filter((item: unknown): item is Record<string, unknown> => (
          Boolean(item) && typeof item === 'object'
        ))
        .map(toSpecialistNodeProgress)
        .filter((item: SpecialistNodeProgress) => item.id),
    )
    addLog(
      'System',
      `科研画像: ${String(profile.family || 'auto')} / ${String(profile.study_archetype || 'auto')}；动态专家子节点 ${subnodes.length} 个`,
      'info',
    )
  } else if (msg.type === 'specialist_node_started') {
    const incoming = toSpecialistNodeProgress({ ...msg, status: 'running' })
    setSpecialistNodes(prev => {
      const exists = prev.some(item => item.id === incoming.id)
      return exists
        ? prev.map(item => item.id === incoming.id ? { ...item, ...incoming } : item)
        : [...prev, incoming]
    })
    addLog(
      'Agent',
      `专家子节点: ${String(msg.name || msg.subnode_id)}，加载 /${String(msg.skill || 'unknown')}`,
      'agent',
    )
  } else if (msg.type === 'specialist_node_completed') {
    const incoming = toSpecialistNodeProgress({ ...msg, status: 'completed' })
    setSpecialistNodes(prev => {
      const exists = prev.some(item => item.id === incoming.id)
      return exists
        ? prev.map(item => item.id === incoming.id ? { ...item, ...incoming } : item)
        : [...prev, incoming]
    })
    addLog(
      'Agent',
      `✓ 专家子节点完成: ${String(msg.name || msg.subnode_id)} -> ${String(msg.artifact || '')}`,
      'agent',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'specialist_node_reused') {
    const incoming = toSpecialistNodeProgress({ ...msg, status: 'reused' })
    setSpecialistNodes(prev => {
      const exists = prev.some(item => item.id === incoming.id)
      return exists
        ? prev.map(item => item.id === incoming.id ? { ...item, ...incoming } : item)
        : [...prev, incoming]
    })
    addLog(
      'System',
      `复用当前科研画像下的专家产物: ${String(msg.name || msg.subnode_id)}`,
      'info',
    )
  } else if (msg.type === 'specialist_node_failed' || msg.type === 'specialist_stage_incomplete') {
    const failedId = String(msg.subnode_id || '')
    setSpecialistNodes(prev => prev.map(item => (
      failedId
        ? item.id === failedId
          ? { ...item, status: 'failed' }
          : item
        : item.nodeId === String(msg.node_id || '') && !['completed', 'reused'].includes(item.status)
          ? { ...item, status: 'failed' }
          : item
    )))
    addLog(
      'System',
      `专家子节点未通过，将进入修订循环: ${String(msg.error || msg.name || msg.subnode_id || '')}`,
      'warn',
    )
  } else if (msg.type === 'runtime_execution_started') {
    addLog(
      'Tool',
      `运行时服务开始: ${String(msg.runtime_service || 'workflow runtime')}`,
      'tool',
    )
  } else if (msg.type === 'runtime_execution_completed') {
    setNodes(prev => prev.map(node => node.id === String(msg.node_id || '')
      ? { ...node, runtimeVerified: true }
      : node))
    addLog(
      'Tool',
      `✓ 运行时服务完成: ${String(msg.runtime_service || 'workflow runtime')}`,
      'tool',
    )
  } else if (msg.type === 'runtime_execution_failed') {
    addLog(
      'Tool',
      `✗ 运行时服务失败: ${String(msg.runtime_service || 'workflow runtime')}：${String(msg.error || '')}`,
      'error',
    )
  } else if (msg.type === 'skill_invocation_started') {
    addLog(
      'Agent',
      `执行 skill: /${String(msg.skill || 'unknown')}${msg.role === 'delegate' ? '（独立子会话）' : ''}`,
      'agent',
    )
  } else if (msg.type === 'skill_invocation_completed') {
    if (String(msg.role || 'primary') === 'primary') {
      setNodes(prev => prev.map(node => node.id === String(msg.node_id || '')
        ? { ...node, modelVerified: true }
        : node))
    }
    addLog(
      'Agent',
      `✓ skill 完成: /${String(msg.skill || 'unknown')}`,
      'agent',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'skill_invocation_recovered') {
    addLog(
      'System',
      `skill 未完整执行，已由确定性服务恢复: /${String(msg.skill || 'unknown')}`,
      'warn',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'skill_invocation_progress') {
    const elapsed = Number(msg.elapsed || 0)
    if (elapsed > 0) {
      addLog(
        'Agent',
        `/${String(msg.skill || 'skill')} 正在执行：${String(msg.status || 'running')}（本次 ${elapsed}s，第 ${msg.attempt ?? '?'}/${msg.max_attempts ?? '?'} 次请求，总预算剩余 ${msg.remaining_seconds ?? '?'}s）`,
        'info',
      )
    }
  } else if (msg.type === 'skill_invocation_reused') {
    addLog(
      'Agent',
      `复用已验收 skill 产物: /${String(msg.skill || 'unknown')}`,
      'info',
    )
  } else if (msg.type === 'paper_stage_started') {
    flushAgentOutput()
    const stageId = String(msg.stage_id || '')
    const stageIndex = Number(msg.stage_index || PAPER_STAGE_DEFINITIONS.findIndex(stage => stage.id === stageId) + 1)
    const stageTotal = Number(msg.stage_total || PAPER_STAGE_DEFINITIONS.length)
    const attempt = Number(msg.attempt || 1)
    updatePaperStage(stageId, {
      status: 'running',
      attempt,
      maximumAttempts: Number(msg.maximum_attempts || attempt),
      issues: [],
      agentStatus: '正在撰写',
    })
    const stage = PAPER_STAGE_DEFINITIONS.find(item => item.id === stageId)
    addLog(
      'Agent',
      `论文分章 ${stageIndex}/${stageTotal}：开始 ${stage?.label || String(msg.stage_label || stageId)}（第 ${attempt} 次）`,
      'agent',
    )
  } else if (msg.type === 'paper_stage_reviewed') {
    flushAgentOutput()
    const stageId = String(msg.stage_id || '')
    const issues = Array.isArray(msg.issues)
      ? msg.issues.map((item: unknown) => String(item)).filter(Boolean)
      : []
    const passed = msg.passed === true
    updatePaperStage(stageId, {
      status: passed ? 'passed' : 'revision_required',
      attempt: Number(msg.attempt || 0),
      issues,
      agentStatus: '',
    })
    const stage = PAPER_STAGE_DEFINITIONS.find(item => item.id === stageId)
    addLog(
      'Agent',
      passed
        ? `${stage?.label || String(msg.stage_label || stageId)} 章节验收通过`
        : `${stage?.label || String(msg.stage_label || stageId)} 需要局部返修：${issues[0] || '未满足章节契约'}`,
      passed ? 'agent' : 'warn',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'paper_stage_reused') {
    const stageId = String(msg.stage_id || '')
    updatePaperStage(stageId, {
      status: 'reused',
      attempt: Number(msg.attempt || 0),
      issues: [],
      agentStatus: '',
    })
  } else if (msg.type === 'paper_stage_agent_status') {
    const stageId = String(msg.stage_id || '')
    const status = String(msg.status || '')
    const statusLabel = status === 'thinking'
      ? '模型正在斟酌本章节'
      : status === 'waiting_model'
        ? `等待模型：本次 ${msg.elapsed ?? 0}s，第 ${msg.attempt ?? '?'}/${msg.max_attempts ?? '?'} 次请求，总预算剩余 ${msg.remaining_seconds ?? '?'}s`
        : status === 'retrying_provider'
          ? `请求重试 ${msg.next_attempt ?? msg.attempt ?? '?'}/${msg.max_attempts ?? '?'}；${msg.retry_in_seconds ?? '?'}s 后重试，总预算剩余 ${msg.remaining_seconds ?? '?'}s`
      : status === 'switching_provider'
        ? `切换模型到 ${String(msg.model || msg.provider || '')}`
        : status === 'partial_stream_recovered'
          ? '已保留流式输出并继续'
          : status
    updatePaperStage(stageId, { agentStatus: statusLabel })
  } else if (msg.type === 'skill_invocation_revision_required') {
    flushAgentOutput()
    const stageId = String(msg.stage_id || '')
    const issues = Array.isArray(msg.issues)
      ? msg.issues.map((item: unknown) => String(item)).filter(Boolean)
      : []
    updatePaperStage(stageId, {
      status: 'revision_required',
      issues,
      agentStatus: '',
    })
    const stage = PAPER_STAGE_DEFINITIONS.find(item => item.id === stageId)
    addLog(
      'System',
      `论文写作停在 ${stage?.label || String(msg.stage_label || stageId)}；已通过章节保持不变。${issues[0] ? `当前问题：${issues[0]}` : ''}`,
      'warn',
    )
  } else if (msg.type === 'skill_invocation_failed') {
    addLog(
      'Agent',
      `✗ skill 失败: /${String(msg.skill || 'unknown')}：${String(msg.error || '未生成必需产物')}`,
      'error',
    )
  } else if (msg.type === 'node_completed') {
    flushAgentOutput()
    const dur = msg.duration ? ` (${(msg.duration / 60).toFixed(1)}min)` : ''
    addLog('Agent', `${msg.node_id} 执行阶段结束${dur}，尚未通过验收`, 'agent')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'node_accepted') {
    flushAgentOutput()
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'completed', validationLabel: undefined } : n))
    addLog('Agent', `✓ ${msg.node_id} accepted by ${msg.reviewer || 'gate'}`, 'agent')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'owner_acceptance_revoked') {
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'running' } : n))
    addLog('System', String(msg.message), 'warn')
  } else if (msg.type === 'node_revision_started') {
    flushAgentOutput()
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'running' } : n))
    const score = msg.score != null && msg.threshold != null
      ? '，质量 ' + String(msg.score) + '/' + String(msg.threshold)
      : ''
    const owner = msg.revision_owner_id && msg.revision_owner_id !== msg.node_id
      ? '，交由上游“' + String(msg.revision_owner_name || msg.revision_owner_id) + '”修复'
      : ''
    addLog(
      'Agent',
      String(msg.node_id) + ' 开始科研修订第 ' + String(msg.round || 1)
        + ' 轮（周期 ' + String(msg.cycle || 1) + '）' + owner + score,
      'agent',
    )
  } else if (msg.type === 'node_revision_completed') {
    flushAgentOutput()
    addLog(
      'Agent',
      String(msg.node_id) + ' 第 ' + String(msg.round || '?')
        + ' 轮已更新目标产物，正在重新验收',
      msg.preparation_error ? 'warn' : 'agent',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'node_revision_no_progress') {
    flushAgentOutput()
    addLog(
      'System',
      String(msg.node_id) + ' 第 ' + String(msg.round || '?')
        + (msg.execution_succeeded === false
          ? ' 轮修订执行失败，且未检测到目标产物或语义变化'
          : ' 轮修订未检测到目标产物或语义变化')
        + '，正在重新验收',
      'warn',
    )
  } else if (msg.type === 'source_integrity_repaired') {
    flushAgentOutput()
    const repairs = Array.isArray(msg.repairs) ? msg.repairs : []
    const files = repairs
      .slice(0, 4)
      .map((item: any) => String(item?.path || ''))
      .filter(Boolean)
      .join('、')
    addLog(
      'System',
      `检测到模型编辑造成的可确定修复语法问题，已修复 ${String(repairs.length)} 个文件并保留原始备份${files ? `：${files}` : ''}`,
      'info',
    )
    if (msg.report_path) addLog('System', `修复审计记录：${String(msg.report_path)}`, 'info')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'node_preparation_deferred') {
    flushAgentOutput()
    const owners = Array.isArray(msg.owner_node_ids)
      ? msg.owner_node_ids.map((item: unknown) => String(item)).filter(Boolean).join('、')
      : '关键上游节点'
    const issue = Array.isArray(msg.issues) && msg.issues.length
      ? `：${String(msg.issues[0])}`
      : ''
    addLog(
      'System',
      `${String(msg.node_id || '当前节点')} 暂不生成新产物，先修复上游 ${owners}${issue}`,
      'warn',
    )
  } else if (msg.type === 'upstream_owner_revalidated') {
    flushAgentOutput()
    addLog(
      'System',
      msg.accepted
        ? `上游 ${String(msg.owner_node_id || '')} 已在修复后重新通过验收`
        : `上游 ${String(msg.owner_node_id || '')} 修复后仍未通过验收，当前节点继续等待`,
      msg.accepted ? 'info' : 'warn',
    )
  } else if (msg.type === 'narrative_artifact_recovered') {
    flushAgentOutput()
    addLog(
      'System',
      `已从冻结 Idea、方法契约和证据状态生成保守叙事底稿（${String(msg.evidence_mode || 'planned')}）`,
      'info',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'deterministic_compile_completed') {
    flushAgentOutput()
    addLog(
      'System',
      msg.success
        ? `${String(msg.node_id || 'compile')} 已完成确定性编译${msg.pages ? `，共 ${String(msg.pages)} 页` : ''}`
        : `${String(msg.node_id || 'compile')} 编译失败，将根据真实编译错误修复源文件`,
      msg.success ? 'info' : 'warn',
    )
    if (msg.success) window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'slide_artifact_recovered') {
    flushAgentOutput()
    addLog(
      'System',
      `模型未生成可用演示源文件，已从冻结契约和 paper-selected 图表生成 Beamer 底稿（${String(msg.evidence_mode || 'planned')}）`,
      'info',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'node_revision_gate') {
    flushAgentOutput()
    if (msg.accepted && Number(msg.round || 0) > 0) {
      addLog('Agent', String(msg.node_id) + ' 在第 ' + String(msg.round) + ' 轮达到科研质量门', 'agent')
    } else if (!msg.accepted) {
      const issues = Array.isArray(msg.issues)
        ? msg.issues.slice(0, 5).map((item: unknown) => String(item)).join('；')
        : String(msg.summary || msg.reason || '')
      const score = msg.score != null && msg.threshold != null
        ? '质量 ' + String(msg.score) + '/' + String(msg.threshold) + '；'
        : ''
      const contentScorePassed = msg.score != null && msg.threshold != null
        && Number(msg.score) >= Number(msg.threshold)
      addLog(
        'System',
        String(msg.node_id)
          + (contentScorePassed
            ? ' 内容评分已达标，但节点验收仍有阻塞，进入修订：'
            : ' 未达门槛，进入修订：')
          + score
          + issues,
        'warn',
      )
      if (msg.report_path) addLog('System', '科研质量报告：' + String(msg.report_path), 'info')
    }
  } else if (msg.type === 'node_quality_advisory') {
    flushAgentOutput()
    const issues = Array.isArray(msg.issues)
      ? msg.issues.slice(0, 3).map((item: unknown) => String(item)).join('；')
      : ''
    if (msg.kind === 'node_risk') {
      addLog(
        'System',
        `${String(msg.node_id || '节点')} 已通过硬门禁，但风险审计发现 ${String(msg.warning_count || 1)} 项潜在问题${issues ? `：${issues}` : ''}`,
        'warn',
      )
      if (msg.report_path) addLog('System', `节点风险报告：${String(msg.report_path)}`, 'info')
      return
    }
    addLog(
      'System',
      `${String(msg.node_id || '节点')} 已通过结构门禁，仍有质量建议 ${String(msg.score ?? '')}/${String(msg.threshold ?? '')}${issues ? `：${issues}` : ''}`,
      'warn',
    )
    if (msg.report_path) addLog('System', `科研质量报告：${String(msg.report_path)}`, 'info')
  } else if (msg.type === 'workflow_risk_snapshot') {
    flushAgentOutput()
    const blockers = Array.isArray(msg.latent_blockers) ? msg.latent_blockers : []
    const newFindings = Array.isArray(msg.new_findings) ? msg.new_findings : []
    const warnings = newFindings.filter(
      (item: { severity?: unknown }) => String(item?.severity || '') === 'warning',
    )
    if (blockers.length > 0) {
      const first = blockers[0] as { node_id?: unknown; plain_message?: unknown }
      addLog(
        'System',
        `跨节点复核发现 ${String(blockers.length)} 项既有上游产物失效：${String(first.node_id || '上游节点')}，${String(first.plain_message || '需要重新验收')}`,
        'warn',
      )
      if (msg.report_path) addLog('System', `全工作流风险快照：${String(msg.report_path)}`, 'info')
    }
    if (warnings.length > 0) {
      const first = warnings[0] as {
        node_id?: unknown
        owner_node?: unknown
        plain_message?: unknown
      }
      addLog(
        'System',
        `跨节点复核新增 ${String(warnings.length)} 项科研风险：${String(first.node_id || '节点')}，`
          + `${String(first.plain_message || '需要研究者判断')}`
          + `（责任节点：${String(first.owner_node || first.node_id || '未确定')}）`,
        'warn',
      )
      if (msg.report_path && blockers.length === 0) {
        addLog('System', `全工作流风险快照：${String(msg.report_path)}`, 'info')
      }
    }
  } else if (msg.type === 'node_platform_auto_recovery_started') {
    flushAgentOutput()
    setCheckpointNode(null)
    revisionLimitCheckpointRef.current = null
    addLog(
      'System',
      `${String(msg.node_id || '当前节点')} 正在自动执行平台恢复周期 `
        + `${String(msg.cycle || 1)}/${String(msg.max_cycles || 1)}`
        + `；${String(msg.reason || '重新准备产物并验收')}`,
      'info',
    )
  } else if (msg.type === 'node_platform_repair_required') {
    flushAgentOutput()
    setCheckpointNode(null)
    revisionLimitCheckpointRef.current = null
    const componentStatuses = normalizeGateComponentStatuses(msg.component_statuses)
    const statusText = Object.values(componentStatuses)
      .map(status => `${status.label}：${status.passed ? '已通过' : '未通过'}`)
      .join('；')
    addLog(
      'System',
      `${String(msg.node_id || '当前节点')} 已停止在平台/产物修复状态`
        + `（责任节点：${String(msg.owner_node_id || msg.node_id || '未确定')}）`
        + `${statusText ? `；${statusText}` : ''}`
        + `；${String(msg.summary || msg.reason || '无需用户确认，修复后重新验收')}`,
      'error',
    )
  } else if (msg.type === 'node_revision_waiting') {
    flushAgentOutput()
    setCheckpointActionError('')
    const revisionIssues = Array.isArray(msg.issues)
      ? msg.issues.map((item: unknown) => String(item))
      : []
    const revisionRound = Number(msg.round || 0)
    const interventionKind = String(msg.intervention_kind || 'platform_repair') === 'researcher_decision'
      ? 'researcher_decision'
      : 'platform_repair'
    const requiresHumanDecision = msg.requires_human_decision === true
    const stopReason = msg.transport_exhausted
      ? '模型连接中断，未消耗科研修订轮数'
      : msg.stopped_for_deterministic_stage
        ? '图片渲染/产物修复未通过，等待平台修复'
        : msg.stopped_for_no_progress
          ? '产物没有语义变化，已停止重复调用'
          : '已达到自动修订上限'
    const transportRetrySuffix = transportRecoveryNotice(msg)
    const revisionCheckpoint: WorkflowCheckpoint = {
      id: String(msg.node_id || ''),
      name: String(msg.name || msg.node_id || '当前节点'),
      timeoutSeconds: 0,
      kind: 'research_revision',
      revisionRound,
      revisionCycle: Number(msg.cycle || 1),
      summary: String(msg.summary || msg.reason || ''),
      issues: revisionIssues,
      score: msg.score != null ? Number(msg.score) : undefined,
      threshold: msg.threshold != null ? Number(msg.threshold) : undefined,
      reportPath: String(msg.report_path || ''),
      persisted: true,
      stopReason,
      componentStatuses: normalizeGateComponentStatuses(msg.component_statuses),
      interventionKind,
      requiresHumanDecision,
      decisionBrief: normalizeRevisionDecisionBrief(msg.decision_brief, {
        nodeId: String(msg.node_id || ''),
        nodeName: String(msg.name || msg.node_id || '当前节点'),
        round: revisionRound,
        maxRounds: Number(msg.max_revision_rounds || revisionRound || 1),
        summary: String(msg.summary || msg.reason || ''),
        issues: revisionIssues,
      }),
    }
    revisionLimitCheckpointRef.current = requiresHumanDecision ? revisionCheckpoint : null
    if (!requiresHumanDecision) setCheckpointNode(null)
    addLog(
      'System',
      String(msg.node_id) + ' ' + stopReason
        + (requiresHumanDecision
          ? '，存在明确科研决策，已保留可恢复检查点'
          : '，已归类为平台/产物修复问题，不要求用户确认')
        + transportRetrySuffix,
      'warn',
    )
  } else if (msg.type === 'node_revision_error') {
    flushAgentOutput()
    const transportError = String(msg.error_category || '') === 'transport'
    addLog(
      'System',
      String(msg.node_id) + ' 第 ' + String(msg.round || '?')
        + (transportError ? ' 轮模型连接中断：' : ' 轮节点修订执行失败：')
        + String(msg.error || '未提供异常详情')
        + (transportError
          ? '；该次不计入科研修订轮数，系统将按传输重试策略处理'
          : '；该次计入有界修订轮数，错误已归属当前责任节点'),
      'warn',
    )
  } else if (msg.type === 'node_blocked') {
    flushAgentOutput()
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'failed' } : n))
    const reason = String(msg.error || 'acceptance gate failed')
    const summary = String(msg.details?.summary || '')
    const quality = msg.details?.details?.research_quality
    const qualityIssues = Array.isArray(quality?.issues)
      ? quality.issues.slice(0, 5).map((issue: unknown) => String(issue)).join('；')
      : ''
    const qualityScore = quality?.score == null ? undefined : Number(quality.score)
    const qualityThreshold = quality?.threshold == null ? undefined : Number(quality.threshold)
    const qualityStatus = qualityScore != null && qualityThreshold != null
      ? `内容质量：${qualityScore >= qualityThreshold ? '已通过' : '未通过'}（${formatGateNumber(qualityScore)} ${qualityScore >= qualityThreshold ? '≥' : '<'} ${formatGateNumber(qualityThreshold)}）`
      : ''
    const implementation = msg.details?.details?.implementation_contract
    const implementationStatus = implementation && typeof implementation === 'object'
      ? `实现契约：${implementation.passed === true ? '已通过' : '未通过'}`
      : ''
    const detail = [summary && summary !== reason ? summary : '', qualityStatus, implementationStatus, qualityIssues]
      .filter(Boolean)
      .join('；')
    addLog('System', `Gate blocked ${msg.node_id}: ${reason}${detail ? `；${detail}` : ''}`, 'error')
    if (quality?.report_path) addLog('System', `科研质量报告：${String(quality.report_path)}`, 'info')
  } else if (msg.type === 'node_failed') {
    flushAgentOutput()
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'failed' } : n))
    addLog('System', `✗ ${msg.node_id}: ${msg.error || ''}`, 'error')
  } else if (msg.type === 'node_skipped') {
    flushAgentOutput()
    setNodes(prev => prev.map(n => n.id === msg.node_id ? { ...n, status: 'skipped' } : n))
    addLog('System', `跳过 ${msg.node_id}: ${msg.reason || '依赖节点尚未验收'}`, 'warn')
  } else if (msg.type === 'node_tool_fallback') {
    flushAgentOutput()
    addLog('System', `${msg.node_id}: 工具参数无效，已切换到文本兜底写入`, 'warn')
  } else if (msg.type === 'node_recovered') {
    flushAgentOutput()
    addLog('System', `${msg.node_id}: ${msg.message || '模型执行中断，已使用本地产物兜底继续'}`, 'warn')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'exp_design_depth_repaired') {
    flushAgentOutput()
    const remaining = Array.isArray(msg.remaining_issues) ? msg.remaining_issues.length : 0
    addLog(
      'System',
      `实验设计深度补全：${String(msg.before_score ?? '?')} → ${String(msg.after_score ?? '?')}，门槛 ${String(msg.threshold ?? '?')}${remaining ? `；仍有 ${remaining} 项待处理` : '；契约已满足'}`,
      remaining ? 'warn' : 'info',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'node_artifact_canonicalized') {
    flushAgentOutput()
    const action = msg.generated_missing_artifacts
      ? '已补齐缺失的标准实验产物'
      : msg.research_depth_passed != null
        ? '已校验并保留标准实验产物'
        : '已将产物移动到标准路径'
    addLog('System', `${msg.node_id}: ${action}`, 'info')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'figure_artifact_failed') {
    flushAgentOutput()
    addLog(
      'Tool',
      'Figure generation failed: ' + String(msg.error || msg.description || msg.figure_type || ''),
      'warn',
    )
  } else if (msg.type === 'figure_artifact_generated') {
    flushAgentOutput()
    const outputPath = String(msg.output_path || '')
    const sourcePath = String(msg.source_path || '')
    addLog(
      'Tool',
      'Saved figure: ' + (outputPath || sourcePath || msg.description || msg.figure_type || 'artifact'),
      'tool',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'planned_result_templates_generated') {
    flushAgentOutput()
    addLog(
      'System',
      '已生成确定性仿真基准的主结果、消融、训练动态、鲁棒性、误差、风险覆盖与效率图表',
      'info',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'patent_search_completed') {
    addLog('Tool', `专利检索完成：${String(msg.records || 0)} 条，范围 ${String(msg.date_from)}-${String(msg.date_to)}；产物 ${String(msg.artifact || '')}`, 'tool')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'knowledge_sources_collected') {
    const records = msg.records && typeof msg.records === 'object'
      ? Object.entries(msg.records).map(([source, count]) => `${source}=${String(count)}`).join(' · ')
      : ''
    addLog('Tool', `个人知识源已读取：${records || String((msg.sources || []).join(', '))}`, 'tool')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'overleaf_sync_started') {
    addLog('Tool', 'Overleaf：编译前同步已开始', 'tool')
  } else if (msg.type === 'overleaf_sync_result') {
    const conflictText = Array.isArray(msg.conflicts) && msg.conflicts.length
      ? '；冲突文件 ' + msg.conflicts.join(', ')
      : ''
    addLog(
      'Tool',
      'Overleaf ' + String(msg.phase || 'sync') + '：' + String(msg.message || '') + conflictText,
      msg.success ? 'tool' : 'error',
    )
    if (msg.success) window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'notification_configuration_required') {
    addLog('System', String(msg.message || '通知配置需要验证'), 'warn')
  } else if (msg.type === 'notification_delivery') {
    const sent = Array.isArray(msg.sent) ? msg.sent.join(', ') : ''
    const errors = msg.errors && typeof msg.errors === 'object'
      ? Object.entries(msg.errors).map(([channel, error]) => channel + ': ' + String(error)).join('; ')
      : ''
    const notConfigured = Boolean(msg.errors?.configuration)
    addLog(
      'System',
      msg.success ? '通知已投递：' + sent : notConfigured ? '通知未启用' : '通知未投递：' + (errors || '未知错误'),
      msg.success || notConfigured ? 'info' : 'warn',
    )
  } else if (msg.type === 'meta_optimization_observed') {
    const detail = msg.proposed
      ? `已生成待审批 skill 提案 ${String(msg.mutation_id || '')}`
      : `已记录失败模式（${String(msg.observations || 1)}/2），尚不修改 skill`
    addLog('System', `自进化 /${String(msg.skill || '')}: ${detail}`, msg.proposed ? 'warn' : 'info')
    window.dispatchEvent(new Event('merak-ide:meta-optimize-changed'))
  } else if (msg.type === 'paper_page_target_missed') {
    flushAgentOutput()
    addLog(
      'System',
      `论文共 ${String(msg.actual_pages || '?')} 页，偏离建议范围 ${String(msg.minimum_pages)}-${String(msg.maximum_pages)} 页；页数为软目标，工作流继续`,
      'warn',
    )
  } else if (msg.type === 'paper_length_revision_started') {
    flushAgentOutput()
    addLog('Agent', '论文页数修订第 ' + String(msg.round) + ' 轮：当前 ' + String(msg.actual_pages) + ' 页，目标 ' + String(msg.minimum_pages) + '-' + String(msg.maximum_pages) + ' 页', 'agent')
  } else if (msg.type === 'paper_length_revision_completed') {
    flushAgentOutput()
    addLog('Agent', '论文页数修订完成：' + String(msg.before_pages) + ' → ' + String(msg.after_pages) + ' 页', msg.accepted ? 'agent' : 'warn')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'paper_print_layout_repaired') {
    flushAgentOutput()
    const assets = Array.isArray(msg.asset_ids) ? msg.asset_ids.join(', ') : ''
    addLog('System', '已按论文实际尺寸局部重排插图：' + assets + '；未修改科学数据，等待编译复核', 'info')
    window.dispatchEvent(new Event('merak-ide:files-changed'))
  } else if (msg.type === 'paper_artifact_repaired') {
    flushAgentOutput()
    const pdfPath = String(msg.pdf_path || '')
    addLog(
      'System',
      'Paper verified and compiled (' + String(msg.mode || 'artifact repair') + ', ' + String(msg.pages || '?') + ' pages)',
      'info',
    )
    window.dispatchEvent(new Event('merak-ide:files-changed'))
    if (pdfPath) {
      useWorkspaceStore.getState().openFile({
        path: pdfPath,
        name: pdfPath.split(/[/\\]/).pop() || 'main.pdf',
        language: 'pdf',
        content: '',
      })
    }
  }
  return true
}
