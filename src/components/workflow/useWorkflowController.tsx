import type { WorkflowCheckpoint } from './workflowContext'
import { WORKFLOW_NODES, type WorkflowNodeId } from '@shared/workflow-nodes'
import type { ReactNode } from 'react'
import { useState, useEffect, useRef } from 'react'
import { API_BASE } from '../../config'
import {
  RotateCcw,
  BookOpen, Lightbulb, Sparkles, FlaskConical, Monitor,
  BarChart2, Image, ClipboardList, PenLine, Shield,
  FileOutput, Presentation,
} from 'lucide-react'
import { useWorkspaceStore } from '../../stores/workspace'
import {
  type IntegrationState,
} from '@/lib/connection-status'
import { useWorkflowConfigPersistence } from './useWorkflowConfigPersistence'
import {
  EMPTY_EXPERIMENT_MONITOR,
  type ExperimentMonitorState,
  type LogEntry,
  type PaperStageProgress,
  type ResumableState,
  type SpecialistNodeProgress,
  type WorkflowCompletion,
  type WorkflowNode,
  createPaperStageProgress,
  formatGateNumber,
  normalizePersistedPaperStages,
  toSpecialistNodeProgress,
} from './workflowViewModels'
import {
  toNodeStatus,
} from './workflowResume'
import { createWorkflowSocketConnector } from './workflowSocket'
import { useWorkflowCommands } from './useWorkflowCommands'
import { useWorkflowRecoveryEffects } from './useWorkflowRecoveryEffects'
import {
  loadWorkflowDisplayLogs,
  mergeWorkflowDisplayLogs,
} from './workflowLogRecovery'

/**
 * 全屏三栏 Workflow 模式
 *
 * ┌────────────────────────────────────────────────────────────┐
 * │  Merak Research Workflow                     [← Back to IDE] │
 * ├─────────────┬──────────────────┬───────────────────────────┤
 * │ 配置面板     │  工作流节点图     │  实时日志/输出              │
 * └─────────────┴──────────────────┴───────────────────────────┘
 */

const NODE_ICONS: Record<WorkflowNodeId, ReactNode> = {
  lit: <BookOpen size={14} />, idea: <Lightbulb size={14} />, novelty: <Sparkles size={14} />,
  'exp-design': <FlaskConical size={14} />, 'exp-run': <Monitor size={14} />,
  results: <BarChart2 size={14} />, narrative: <ClipboardList size={14} />, figure: <Image size={14} />,
  paper: <PenLine size={14} />, review: <RotateCcw size={14} />, audit: <Shield size={14} />,
  compile: <FileOutput size={14} />, ppt: <Presentation size={14} />,
}
const DEFAULT_NODES: WorkflowNode[] = WORKFLOW_NODES.map(node => ({
  id: node.id, name: node.name, icon: NODE_ICONS[node.id], status: 'idle', selected: node.id !== 'ppt',
}))

export function useWorkflowController() {
  const setWorkflowFullscreen = useWorkspaceStore(s => s.setWorkflowFullscreen)
  const projectPath = useWorkspaceStore(s => s.projectPath)
  const setProjectPath = useWorkspaceStore(s => s.setProjectPath)
  const [nodes, setNodes] = useState<WorkflowNode[]>(DEFAULT_NODES)
  const [isRunning, setIsRunning] = useState(false)
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [pausedRunId, setPausedRunId] = useState<string | null>(null)
  const [checkpointNode, setCheckpointNode] = useState<WorkflowCheckpoint | null>(null)
  const [checkpointFeedback, setCheckpointFeedback] = useState('')
  const [checkpointActionError, setCheckpointActionError] = useState('')
  const [checkpointSecondsLeft, setCheckpointSecondsLeft] = useState(0)
  const [isExtendingCheckpoint, setIsExtendingCheckpoint] = useState(false)
  const checkpointTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const checkpointFeedbackRef = useRef('')
  const handledCheckpointIdsRef = useRef<Set<string>>(new Set())
  const revisionLimitCheckpointRef = useRef<typeof checkpointNode>(null)
  const [isAcknowledgingCheckpoint, setIsAcknowledgingCheckpoint] = useState(false)
  const [resumableState, setResumableState] = useState<ResumableState | null>(null)
  const [workflowCompletion, setWorkflowCompletion] = useState<WorkflowCompletion | null>(null)
  const [isResuming, setIsResuming] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const logsEndRef = useRef<HTMLDivElement>(null)
  const [paperStages, setPaperStages] = useState<PaperStageProgress[]>(createPaperStageProgress)
  const [paperProgressVisible, setPaperProgressVisible] = useState(false)
  const [specialistNodes, setSpecialistNodes] = useState<SpecialistNodeProgress[]>([])
  const experimentLogLastEmitRef = useRef(0)
  const [experimentMonitor, setExperimentMonitor] = useState<ExperimentMonitorState>(EMPTY_EXPERIMENT_MONITOR)
  const [adjustmentDialogOpen, setAdjustmentDialogOpen] = useState(false)
  const [approvalDialogOpen, setApprovalDialogOpen] = useState(false)
  const [adjustmentBusy, setAdjustmentBusy] = useState(false)
  const [adjustmentDraft, setAdjustmentDraft] = useState({
    summary: '',
    rationale: '',
    batchSize: '',
    command: '',
  })
  const [focusedNode, setFocusedNode] = useState<string | null>(null)
  const [nodeSchema, setNodeSchema] = useState<any>(null)
  const [nodeParams, setNodeParams] = useState<Record<string, any>>({})
  const nodeParamsFocusedNodeRef = useRef<string | null>(null)
  const [showProjectForm, setShowProjectForm] = useState(false)
  const [pendingRunIds, setPendingRunIds] = useState<string[] | null>(null)
  const pendingRunIdsRef = useRef<string[] | null>(null)
  const [projectCreationError, setProjectCreationError] = useState('')
  const wsRef = useRef<WebSocket | null>(null)
  const wsReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wsReconnectAttemptRef = useRef(0)
  const allowWsReconnectRef = useRef(false)
  const runtimeRunIdRef = useRef('')
  const runtimeLogOffsetRef = useRef(0)
  const currentRunIdRef = useRef<string | null>(null)
  const runtimeStateEpochRef = useRef(0)
  const pausedRunIdRef = useRef<string | null>(null)
  // A manually stopped run may remain `running` in the backend for a short
  // cancellation window. Recovery polling must not resurrect it in the UI.
  const manuallyStoppedRunIdsRef = useRef<Set<string>>(new Set())
  const workflowStopRequestedRef = useRef(false)
  const projectPathRef = useRef<string | null>(projectPath || null)
  const agentOutputBufferRef = useRef('')
  const agentOutputFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const suppressedToolTextRef = useRef(false)
  const backgroundRecoveryNoticeRef = useRef('')

  const updatePaperStage = (stageId: string, patch: Partial<PaperStageProgress>) => {
    setPaperProgressVisible(true)
    setPaperStages(previous => previous.map(stage => (
      stage.id === stageId
        ? { ...stage, ...patch, id: stage.id }
        : stage
    )))
  }

  const setActiveRunId = (runId: string | null) => {
    runtimeStateEpochRef.current += 1
    currentRunIdRef.current = runId
    setCurrentRunId(runId)
  }

  const setPausedRunIdSafe = (runId: string | null, preserveCheckpoint = false) => {
    pausedRunIdRef.current = runId
    setPausedRunId(runId)
    if (!runId && !preserveCheckpoint) {
      setCheckpointNode(null)
      setCheckpointActionError('')
      checkpointFeedbackRef.current = ''
      setCheckpointFeedback('')
      setCheckpointSecondsLeft(0)
      if (checkpointTimerRef.current) {
        clearInterval(checkpointTimerRef.current)
        checkpointTimerRef.current = null
      }
    }
  }

  const closeWorkflowWs = () => {
    allowWsReconnectRef.current = false
    if (wsReconnectTimerRef.current) {
      clearTimeout(wsReconnectTimerRef.current)
      wsReconnectTimerRef.current = null
    }
    if (!wsRef.current) return
    const ws = wsRef.current
    wsRef.current = null
    ws.onclose = null
    ws.close()
  }

  const startCheckpointCountdown = (seconds: number) => {
    if (checkpointTimerRef.current) clearInterval(checkpointTimerRef.current)
    const initial = Math.max(0, Math.ceil(seconds || 0))
    setCheckpointSecondsLeft(initial)
    if (initial === 0) return
    checkpointTimerRef.current = setInterval(() => {
      setCheckpointSecondsLeft(prev => {
        if (prev <= 1) {
          if (checkpointTimerRef.current) {
            clearInterval(checkpointTimerRef.current)
            checkpointTimerRef.current = null
          }
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }

  useEffect(() => {
    projectPathRef.current = projectPath || null
    workflowStopRequestedRef.current = false
    manuallyStoppedRunIdsRef.current.clear()
    setSpecialistNodes([])
    setNodes(prev => prev.map(node => ({
      ...node,
      executionKind: undefined,
      ownerSkill: undefined,
      runtimeService: undefined,
      modelVerified: false,
      runtimeVerified: false,
    })))
  }, [projectPath])

  useEffect(() => {
    const runId = currentRunId || pausedRunId || resumableState?.run_id
    if (!projectPath || !runId) return
    let cancelled = false
    fetch(
      `${API_BASE}/api/merak/specialist-plan?project_path=${encodeURIComponent(projectPath)}&run_id=${encodeURIComponent(runId)}`,
    )
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        if (cancelled || !Array.isArray(payload?.subnodes)) return
        setSpecialistNodes(
          payload.subnodes
            .filter((item: unknown): item is Record<string, unknown> => (
              Boolean(item) && typeof item === 'object'
            ))
            .map(toSpecialistNodeProgress)
            .filter((item: SpecialistNodeProgress) => item.id),
        )
      })
      .catch(() => {})
    fetch(
      `${API_BASE}/api/merak/skill-usage?project_path=${encodeURIComponent(projectPath)}&run_id=${encodeURIComponent(runId)}`,
    )
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        if (cancelled || !payload || typeof payload !== 'object') return
        const stageExecution = payload.stage_execution && typeof payload.stage_execution === 'object'
          ? payload.stage_execution as Record<string, any>
          : {}
        const stagePlans = payload.stages && typeof payload.stages === 'object'
          ? payload.stages as Record<string, any>
          : {}
        setNodes(prev => prev.map(node => {
          const evidence = stageExecution[node.id]
          const plan = stagePlans[node.id]
          if (!evidence && !plan) return node
          return {
            ...node,
            executionKind: String(evidence?.execution_kind || plan?.execution_kind || 'model_owned') as WorkflowNode['executionKind'],
            ownerSkill: String(plan?.primary || node.ownerSkill || ''),
            runtimeService: String(plan?.runtime_service || node.runtimeService || ''),
            modelVerified: Boolean(
              evidence?.primary_model_execution_verified
              ?? evidence?.model_execution_verified
            ),
            runtimeVerified: Boolean(evidence?.runtime_execution_verified),
          }
        }))
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [projectPath, currentRunId, pausedRunId, resumableState?.run_id])

  const recoverExperimentRuntime = async () => {
    const runtimeRunId = runtimeRunIdRef.current
    const activeProjectPath = projectPathRef.current
    if (!runtimeRunId || !activeProjectPath) return
    const query = `project_path=${encodeURIComponent(activeProjectPath)}`
    const manifestResponse = await fetch(
      `${API_BASE}/api/experiments/runtime/${encodeURIComponent(runtimeRunId)}?${query}`,
    )
    if (!manifestResponse.ok) return
    const manifest = await manifestResponse.json()
    setExperimentMonitor(prev => ({
      ...prev,
      active: ['precheck', 'snapshot', 'sync', 'launch', 'monitor', 'healthy', 'collect', 'stopping'].includes(String(manifest.status || '')),
      phase: String(manifest.status || prev.phase),
      diagnosisPath: String(manifest.diagnosis_path || prev.diagnosisPath),
      manifestPath: String(manifest.manifest_path || prev.manifestPath),
      metrics: manifest.metrics && typeof manifest.metrics === 'object' ? manifest.metrics : prev.metrics,
    }))
    const logResponse = await fetch(
      `${API_BASE}/api/experiments/runtime/${encodeURIComponent(runtimeRunId)}/log?${query}&offset=${runtimeLogOffsetRef.current}&max_bytes=1048576`,
    )
    if (!logResponse.ok) return
    const logPayload = await logResponse.json()
    runtimeLogOffsetRef.current = Number(logPayload.next_offset || runtimeLogOffsetRef.current)
    const recoveredText = String(logPayload.text || '').trim()
    if (recoveredText) addLog('Train', `[断线补读]\n${recoveredText.slice(-4000)}`, 'info')
  }

  const recoverWorkflowDisplayLogs = async (): Promise<boolean> => {
    const activeProjectPath = projectPathRef.current
    if (!activeProjectPath) return false
    try {
      const runId = currentRunIdRef.current || pausedRunIdRef.current || ''
      const durableLogs = await loadWorkflowDisplayLogs(activeProjectPath, runId)
      if (activeProjectPath !== projectPathRef.current) return false
      setLogs(previous => mergeWorkflowDisplayLogs(durableLogs, previous))
      return true
    } catch {
      return false
    }
  }

  // 连接/复用 WebSocket
  const getSocketContext = () => ({
    wsRef,
    allowWsReconnectRef,
    wsReconnectAttemptRef,
    addLog,
    recoverWorkflowDisplayLogs,
    recoverExperimentRuntime,
    currentRunIdRef,
    pausedRunIdRef,
    wsReconnectTimerRef,
    flushAgentOutput,
    setPausedRunIdSafe,
    setNodes,
    setSpecialistNodes,
    updatePaperStage,
    setCheckpointNode,
    revisionLimitCheckpointRef,
    setCheckpointActionError,
    formatGateNumber,
    runtimeRunIdRef,
    runtimeLogOffsetRef,
    setExperimentMonitor,
    experimentLogLastEmitRef,
    setApprovalDialogOpen,
    queueAgentOutput,
    handledCheckpointIdsRef,
    checkpointFeedbackRef,
    setCheckpointFeedback,
    startCheckpointCountdown,
    setWorkflowCompletion,
    setIsRunning,
    setIsResuming,
    setActiveRunId,
    closeWorkflowWs,
    setResumableState,
    toNodeStatus,
  })
  const connectWs = createWorkflowSocketConnector(getSocketContext)

  // 切换项目时清空状态并重新加载日志
  useEffect(() => {
    // 清空上一个项目的状态
    setLogs([])
    setPaperStages(createPaperStageProgress())
    setPaperProgressVisible(false)
    const pendingSelection = pendingRunIdsRef.current
    setNodes(DEFAULT_NODES.map(node => ({
      ...node,
      selected: pendingSelection ? pendingSelection.includes(node.id) : node.selected,
    })))
    const requestedProjectPath = projectPath
    setIsRunning(false)
    setIsResuming(false)
    setIsExtendingCheckpoint(false)
    setIsAcknowledgingCheckpoint(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    setResumableState(null)
    setWorkflowCompletion(null)
    setExperimentMonitor(EMPTY_EXPERIMENT_MONITOR)
    setAdjustmentDialogOpen(false)
    setApprovalDialogOpen(false)
    setAdjustmentBusy(false)
    setAdjustmentDraft({ summary: '', rationale: '', batchSize: '', command: '' })
    setFocusedNode(null)
    setNodeSchema(null)
    setNodeParams({})
    nodeParamsFocusedNodeRef.current = null
    setShowProjectForm(false)
    setPendingRunIds(null)
    setProjectCreationError('')
    handledCheckpointIdsRef.current.clear()
    revisionLimitCheckpointRef.current = null
    backgroundRecoveryNoticeRef.current = ''
    experimentLogLastEmitRef.current = 0
    runtimeRunIdRef.current = ''
    runtimeLogOffsetRef.current = 0
    wsReconnectAttemptRef.current = 0
    closeWorkflowWs()
    agentOutputBufferRef.current = ''
    suppressedToolTextRef.current = false
    if (agentOutputFlushTimerRef.current) {
      clearTimeout(agentOutputFlushTimerRef.current)
      agentOutputFlushTimerRef.current = null
    }

    if (!projectPath) return
    const sep = projectPath.includes('\\') ? '\\' : '/'
    const paperStateFile = projectPath + sep + 'paper' + sep + 'DRAFT_STATE.json'
    fetch(`${API_BASE}/api/files/read?path=${encodeURIComponent(paperStateFile)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (requestedProjectPath !== projectPathRef.current || !data?.content) return
        try {
          const state = JSON.parse(data.content)
          if (!state?.stages || typeof state.stages !== 'object') return
          const restored = normalizePersistedPaperStages(state.stages)
          setPaperStages(restored)
          setPaperProgressVisible(
            restored.some(stage => stage.status !== 'pending') || state.status === 'completed',
          )
        } catch (error) {
          console.warn('Ignoring malformed staged paper state', error)
        }
      })
      .catch(() => {})

  }, [projectPath])

  // Project selection can be restored before the managed backend is ready.
  // Rehydrate once it becomes available instead of permanently keeping the
  // empty result of the first failed request.
  useEffect(() => {
    if (!projectPath) return
    let disposed = false
    let inFlight = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    const recover = async () => {
      if (disposed || inFlight) return
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      inFlight = true
      const loaded = await recoverWorkflowDisplayLogs()
      inFlight = false
      if (!loaded && !disposed) retryTimer = setTimeout(recover, 2000)
    }
    void recover()
    const unsubscribe = window.merakIDE?.backend?.onStatusChange?.(state => {
      if (state.status === 'ready') void recover()
    })
    return () => {
      disposed = true
      if (retryTimer) clearTimeout(retryTimer)
      unsubscribe?.()
    }
  }, [projectPath])

  // Workflow options are restored without allowing a late disk response to
  // overwrite a draft that the researcher has already started editing.
  const {
    config,
    setConfig,
    updateWorkflowConfig,
    setWorkflowUiHydratedProject,
  } = useWorkflowConfigPersistence({
    projectPath, nodes, nodeParams, focusedNode, setNodes, setNodeParams,
    setFocusedNode, setWorkflowCompletion, nodeParamsFocusedNodeRef,
  })

  // Esc 退出
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setWorkflowFullscreen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setWorkflowFullscreen])

  useEffect(() => {
    return () => {
      if (agentOutputFlushTimerRef.current) clearTimeout(agentOutputFlushTimerRef.current)
      allowWsReconnectRef.current = false
      if (wsReconnectTimerRef.current) clearTimeout(wsReconnectTimerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [])

  // 只有当前配置通过连接测试后，工作流才允许启用对应外部能力。
  const [integrationStatus, setIntegrationStatus] = useState<Record<string, IntegrationState>>({})
  useEffect(() => {
    const loadIntegrationStatus = () => {
      fetch(`${API_BASE}/api/settings/integration-status`)
        .then(r => r.ok ? r.json() : {})
        .then((data: Record<string, IntegrationState>) => {
          setIntegrationStatus(data)
          // Persisted runs from older versions may contain enabled integration
          // preferences even though the credentials were removed or never
          // verified.  Make the visible configuration match what the backend
          // can actually execute; a later successful connection test must not
          // silently re-enable an old preference.
          setConfig(previous => ({
            ...previous,
            enableGemini: data.gemini?.verified === true ? previous.enableGemini : false,
            enableGptImage: data.gpt_image?.verified === true ? previous.enableGptImage : false,
            enableZotero: data.zotero?.verified === true ? previous.enableZotero : false,
            enableObsidian: data.obsidian?.verified === true ? previous.enableObsidian : false,
            enablePatentSearch: data.patent?.verified === true ? previous.enablePatentSearch : false,
            literatureSources: previous.literatureSources.filter(source => (
              (source !== 'gemini' || data.gemini?.verified === true)
              && (source !== 'zotero' || data.zotero?.verified === true)
              && (source !== 'obsidian' || data.obsidian?.verified === true)
            )),
          }))
        })
        .catch(() => {})
    }
    loadIntegrationStatus()
    window.addEventListener('merak-ide:connection-status-changed', loadIntegrationStatus)
    return () => window.removeEventListener('merak-ide:connection-status-changed', loadIntegrationStatus)
  }, [projectPath])

  // 检查是否有可恢复的 session，并用持久化 run-state 校准节点状态
  // 单独执行聚焦的节点（带参数）
  const { handleRunSingleNode, addLog, flushAgentOutput, queueAgentOutput, handleRun, handleStop, handleResume, handleExtendCheckpoint, handleAcknowledgeRevisionCheckpoint, handleExperimentStop, openExperimentArtifact, handleCreateAdjustment, handleResolveAdjustment, handleRetryExperiment, handleReset } = useWorkflowCommands({
    DEFAULT_NODES,
    focusedNode,
    projectPath,
    config,
    setPaperStages,
    setPaperProgressVisible,
    setIsRunning,
    setWorkflowCompletion,
    nodeParams,
    integrationStatus,
    setActiveRunId,
    connectWs,
    setLogs,
    suppressedToolTextRef,
    agentOutputFlushTimerRef,
    agentOutputBufferRef,
    nodes,
    pendingRunIdsRef,
    setPendingRunIds,
    setProjectCreationError,
    setShowProjectForm,
    setSpecialistNodes,
    setNodes,
    closeWorkflowWs,
    currentRunId,
    setPausedRunIdSafe,
    pausedRunIdRef,
    isResuming,
    setConfig,
    checkpointFeedback,
    setCheckpointActionError,
    setIsResuming,
    setCheckpointNode,
    setCheckpointFeedback,
    setResumableState,
    checkpointNode,
    checkpointFeedbackRef,
    isExtendingCheckpoint,
    setIsExtendingCheckpoint,
    checkpointSecondsLeft,
    startCheckpointCountdown,
    isAcknowledgingCheckpoint,
    setIsAcknowledgingCheckpoint,
    experimentMonitor,
    setExperimentMonitor,
    adjustmentBusy,
    setAdjustmentBusy,
    adjustmentDraft,
    setAdjustmentDialogOpen,
    setApprovalDialogOpen,
    setWorkflowUiHydratedProject,
    setAdjustmentDraft,
    setFocusedNode,
    setNodeSchema,
    setNodeParams,
    nodeParamsFocusedNodeRef,
    manuallyStoppedRunIdsRef,
    workflowStopRequestedRef,
  })

  useWorkflowRecoveryEffects({
    runtimeStateEpochRef, currentRunIdRef, getSocketContext,
    projectPath,
    setResumableState,
    projectPathRef,
    checkpointNode,
    addLog,
    setNodes,
    setCheckpointNode,
    setPausedRunIdSafe,
    resumableState,
    isRunning, currentRunId, isResuming,
    setWorkflowCompletion,
    setCheckpointFeedback,
    setActiveRunId,
    setIsRunning, closeWorkflowWs,
    backgroundRecoveryNoticeRef,
    manuallyStoppedRunIdsRef,
    workflowStopRequestedRef,
    connectWs,
    logsEndRef,
    logs,
    focusedNode,
    setNodeSchema,
    nodeParamsFocusedNodeRef,
    setNodeParams,
  })

    return {
    setWorkflowFullscreen,
    projectPath,
    setProjectPath,
    nodes,
    setNodes,
    isRunning,
    pausedRunId,
    checkpointNode,
    checkpointFeedback,
    setCheckpointFeedback,
    checkpointActionError,
    checkpointSecondsLeft,
    isExtendingCheckpoint,
    checkpointFeedbackRef,
    isAcknowledgingCheckpoint,
    resumableState,
    setResumableState,
    workflowCompletion,
    setWorkflowCompletion,
    isResuming,
    logs,
    logsEndRef,
    paperStages,
    paperProgressVisible,
    specialistNodes,
    experimentMonitor,
    adjustmentDialogOpen,
    setAdjustmentDialogOpen,
    approvalDialogOpen,
    setApprovalDialogOpen,
    adjustmentBusy,
    adjustmentDraft,
    setAdjustmentDraft,
    focusedNode,
    setFocusedNode,
    nodeSchema,
    nodeParams,
    setNodeParams,
    showProjectForm,
    setShowProjectForm,
    pendingRunIds,
    setPendingRunIds,
    pendingRunIdsRef,
    projectCreationError,
    setProjectCreationError,
    setPausedRunIdSafe,
    config,
    setConfig,
    updateWorkflowConfig,
    integrationStatus,
    handleRunSingleNode,
    handleRun,
    handleStop,
    handleResume,
    handleExtendCheckpoint,
    handleAcknowledgeRevisionCheckpoint,
    handleExperimentStop,
    openExperimentArtifact,
    handleCreateAdjustment,
    handleResolveAdjustment,
    handleRetryExperiment,
    handleReset,
  }
}

export type WorkflowController = ReturnType<typeof useWorkflowController>
