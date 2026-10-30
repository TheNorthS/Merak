import { WORKFLOW_NODES } from '@shared/workflow-nodes'
import { useEffect } from 'react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { normalizeGateComponentStatuses, toWorkflowCompletion, type ResumableState, type WorkflowNode } from './workflowViewModels'
import { toNodeStatus } from './workflowResume'
import { normalizeRevisionDecisionBrief } from './workflowRevisionUi'
import { useWorkflowRuntimeSync } from './useWorkflowRuntimeSync'

import type { WorkflowRecoveryContext, WorkflowCheckpoint } from './workflowContext'

export function useWorkflowRecoveryEffects(context: WorkflowRecoveryContext) {
  const { projectPath, setResumableState, projectPathRef, addLog, setNodes, setCheckpointNode, setPausedRunIdSafe, setWorkflowCompletion, logsEndRef, logs, focusedNode, setNodeSchema, nodeParamsFocusedNodeRef, setNodeParams } = context
  useWorkflowRuntimeSync(context)
  useEffect(() => {
    if (!projectPath) {
      setResumableState(null)
      return
    }
    const requestedProjectPath = projectPath
    let disposed = false
    let inFlight = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const scheduleRetry = () => {
      if (disposed || retryTimer) return
      retryTimer = setTimeout(() => {
        retryTimer = null
        void loadSessionState()
      }, 2000)
    }

    const loadSessionState = async () => {
      if (disposed || inFlight) return
      inFlight = true
      const epoch = context.runtimeStateEpochRef.current
      const stale = () => disposed || requestedProjectPath !== projectPathRef.current || epoch !== context.runtimeStateEpochRef.current
      try {
        const response = await fetch(
          `${API_BASE}/api/workflow/session-state?project_path=${encodeURIComponent(requestedProjectPath)}`,
        )
        if (!response.ok) throw new Error(`session-state HTTP ${response.status}`)
        const data = await response.json()
        if (stale()) return
        if (!data?.resumable || !data.run_id) {
          setResumableState(null)
          return
        }
        let resumeState: ResumableState = data
        let persistedRevisionCheckpoint: WorkflowCheckpoint | null = null
        let persistedRevisionPromptAcknowledged = false
        const validationLabels: Record<string, string> = {}
        try {
          const stateRes = await fetch(`${API_BASE}/api/workflow/run-states/${encodeURIComponent(data.run_id)}?project_path=${encodeURIComponent(requestedProjectPath)}`)
          if (stale()) return
          if (stateRes.ok) {
            const runState = await stateRes.json()
            if (!runState?.error && runState.phases) {
              for (const [id, raw] of Object.entries(runState.phases)) {
                const phase = raw as { details?: { current_validation?: { status?: string } } }
                if (phase.details?.current_validation?.status === 'revision_pending') validationLabels[id] = '已有产物待复核'
              }
              resumeState = {
                run_id: runState.run_id || data.run_id,
                current_node: data.current_node || '',
                nodes_status: Object.fromEntries(Object.entries(runState.phases).map(([id, phase]: [string, any]) => [id, phase?.status || 'pending'])),
                config: runState.config || data.config,
                auto_rebuild_required: runState.auto_rebuild_required || data.auto_rebuild_required || null,
              }
              const awaitingEntry = Object.entries(runState.phases).find(
                ([, phase]: [string, any]) => phase?.status === 'awaiting_revision',
              ) as [string, any] | undefined
              if (awaitingEntry) {
                const [nodeId, phase] = awaitingEntry
                const revision = phase?.details?.revision || {}
                const lastGate = revision.last_gate || {}
                persistedRevisionPromptAcknowledged = revision.prompt_acknowledged === true
                const persistedIssues = Array.isArray(lastGate.issues)
                  ? lastGate.issues.map((item: unknown) => String(item))
                  : []
                const persistedRound = Number(revision.round || 0)
                const requiresHumanDecision = lastGate.requires_human_decision === true
                  || revision.requires_human_decision === true
                const interventionKind = String(
                  lastGate.intervention_kind || revision.intervention_kind || 'platform_repair',
                ) === 'researcher_decision'
                  ? 'researcher_decision'
                  : 'platform_repair'
                const candidateCheckpoint: WorkflowCheckpoint = {
                  id: nodeId,
                  name: phase?.name || nodeId,
                  timeoutSeconds: Number(runState.config?.options?.checkpoint_timeout_seconds || 300),
                  kind: 'research_revision',
                  revisionRound: persistedRound,
                  revisionCycle: Number(revision.cycle || 1),
                  summary: String(lastGate.summary || lastGate.reason || ''),
                  issues: persistedIssues,
                  score: lastGate.score != null ? Number(lastGate.score) : undefined,
                  threshold: lastGate.threshold != null ? Number(lastGate.threshold) : undefined,
                  reportPath: String(lastGate.report_path || ''),
                  persisted: true,
                  componentStatuses: normalizeGateComponentStatuses(lastGate.component_statuses),
                  interventionKind,
                  requiresHumanDecision,
                  stopReason: revision.transport_exhausted
                    ? '模型连接中断，未消耗科研修订轮数'
                    : revision.stopped_for_deterministic_stage
                      ? '图片渲染/产物修复未通过，等待平台修复'
                      : revision.stopped_for_no_progress
                        ? '产物没有语义变化，已停止重复调用'
                        : '已达到自动修订上限',
                  decisionBrief: normalizeRevisionDecisionBrief(lastGate.decision_brief, {
                    nodeId,
                    nodeName: phase?.name || nodeId,
                    round: persistedRound,
                    maxRounds: Number(runState.config?.options?.max_revision_rounds || persistedRound || 1),
                    summary: String(lastGate.summary || lastGate.reason || ''),
                    issues: persistedIssues,
                  }),
                }
                if (requiresHumanDecision) {
                  persistedRevisionCheckpoint = candidateCheckpoint
                } else {
                  addLog(
                    'System',
                    `${nodeId} 等待平台或产物修复；自动模式不会弹出科研决策框。`,
                    'warn',
                  )
                }
              }
            }
          }
        } catch (error) {
          console.warn('Failed to load persisted workflow run state', error)
          addLog('System', '持久化运行状态读取失败，将使用会话级断点信息恢复。', 'warn')
        }
        if (stale()) return
        setResumableState(resumeState)
        setNodes((prev: WorkflowNode[]) => prev.map(n => ({
          ...n,
          status: toNodeStatus(resumeState.nodes_status?.[n.id]),
          validationLabel: validationLabels[n.id],
        })))
        if (persistedRevisionCheckpoint) {
          setCheckpointNode(persistedRevisionCheckpoint)
          if (!persistedRevisionPromptAcknowledged) {
            setPausedRunIdSafe(resumeState.run_id)
          }
        }
      } catch {
        if (!stale()) {
          setResumableState(null)
          scheduleRetry()
        }
      } finally {
        inFlight = false
      }
    }

    void loadSessionState()
    const onResearchChanged = () => {
      setWorkflowCompletion(null)
      void loadSessionState()
    }
    window.addEventListener('merak-ide:research-changed', onResearchChanged)
    const unsubscribe = window.merakIDE?.backend?.onStatusChange?.(state => {
      if (state.status === 'ready') void loadSessionState()
    })
    return () => {
      disposed = true
      if (retryTimer) clearTimeout(retryTimer)
      unsubscribe?.()
      window.removeEventListener('merak-ide:research-changed', onResearchChanged)
    }
  }, [projectPath])

  // Keep the last delivery verdict visible after closing and reopening a project.
  useEffect(() => {
    if (!projectPath) {
      setWorkflowCompletion(null)
      return
    }
    const requestedProjectPath = projectPath
    fetch(`${API_BASE}/api/workflow/run-states?project_path=${encodeURIComponent(requestedProjectPath)}`)
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        if (requestedProjectPath !== projectPathRef.current) return
        const runs = Array.isArray(payload?.runs) ? payload.runs : []
        const completed = runs.find((run: any) => (
          run?.status === 'completed'
          && run?.completion
          && typeof run.completion === 'object'
        ))
        setWorkflowCompletion(
          completed ? toWorkflowCompletion(completed.completion) : null,
        )
      })
      .catch(() => {})
  }, [projectPath])

  // 自动滚动日志到底部
  const workflowFullscreen = useWorkspaceStore(s => s.workflowFullscreen)
  useEffect(() => {
    // 延迟一帧确保 DOM 可见后再滚动
    requestAnimationFrame(() => {
      const marker = logsEndRef.current
      const viewport = marker?.closest("[data-radix-scroll-area-viewport]") as HTMLElement | null
      viewport?.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" })
    })
  }, [logs, workflowFullscreen])

  // 加载聚焦节点的输入 schema
  useEffect(() => {
    if (!focusedNode) { setNodeSchema(null); return }
    const requestedNode = focusedNode
    let cancelled = false
    // 节点 ID → skill 名称的映射
    const skillId = WORKFLOW_NODES.find(node => node.id === focusedNode)?.skill || focusedNode
    fetch(`${API_BASE}/api/merak/skills/${skillId}/input-schema`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!cancelled && data?.schema) {
          setNodeSchema(data.schema)
          const defaults: Record<string, any> = {}
          for (const f of data.schema.fields) {
            if (f.default !== undefined) defaults[f.name] = f.default
          }
          const preserveCurrent = nodeParamsFocusedNodeRef.current === requestedNode
          setNodeParams((previous: Record<string, any>) => (
            preserveCurrent ? { ...defaults, ...previous } : defaults
          ))
          nodeParamsFocusedNodeRef.current = requestedNode
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [focusedNode, projectPath])
}
