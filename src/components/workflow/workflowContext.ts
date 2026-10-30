import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { ExperimentMonitorState, GateComponentStatus, LogEntry, PaperStageProgress,
  ResumableState, RevisionDecisionBrief, SpecialistNodeProgress, WorkflowCompletion, WorkflowNode } from './workflowViewModels'

type Setter<T> = Dispatch<SetStateAction<T>>
type Ref<T> = MutableRefObject<T>

export interface WorkflowCheckpoint {
  id: string
  name: string
  timeoutSeconds: number
  kind: 'node' | 'research_revision'
  revisionRound: number
  revisionCycle: number
  summary: string
  issues: string[]
  score?: number
  threshold?: number
  reportPath: string
  persisted: boolean
  stopReason?: string
  decisionBrief?: RevisionDecisionBrief
  componentStatuses: Record<string, GateComponentStatus>
  interventionKind: 'researcher_decision' | 'platform_repair'
  requiresHumanDecision: boolean
}

interface WorkflowStateActions {
  setNodes: Setter<WorkflowNode[]>
  setCheckpointNode: Setter<WorkflowCheckpoint | null>
  setCheckpointFeedback: Setter<string>
  setPausedRunIdSafe: (id: string | null, preserve?: boolean) => void
  setActiveRunId: (id: string | null) => void
  setIsRunning: Setter<boolean>
  setResumableState: Setter<ResumableState | null>
  setWorkflowCompletion: Setter<WorkflowCompletion | null>
  closeWorkflowWs: () => void
  addLog: (source: string, message: string, level: LogEntry['level']) => void
}

export interface WorkflowSocketContext extends WorkflowStateActions {
  eventRunId?: string
  wsRef: Ref<WebSocket | null>
  allowWsReconnectRef: Ref<boolean>
  wsReconnectAttemptRef: Ref<number>
  wsReconnectTimerRef: Ref<ReturnType<typeof setTimeout> | null>
  currentRunIdRef: Ref<string | null>
  pausedRunIdRef: Ref<string | null>
  recoverWorkflowDisplayLogs: () => Promise<boolean>
  recoverExperimentRuntime: () => Promise<void>
  flushAgentOutput: () => void
  queueAgentOutput: (text: string) => void
  setSpecialistNodes: Setter<SpecialistNodeProgress[]>
  updatePaperStage: (id: string, patch: Partial<PaperStageProgress>) => void
  revisionLimitCheckpointRef: Ref<WorkflowCheckpoint | null>
  setCheckpointActionError: Setter<string>
  formatGateNumber: (value: number) => string
  runtimeRunIdRef: Ref<string>
  runtimeLogOffsetRef: Ref<number>
  setExperimentMonitor: Setter<ExperimentMonitorState>
  experimentLogLastEmitRef: Ref<number>
  setApprovalDialogOpen: Setter<boolean>
  handledCheckpointIdsRef: Ref<Set<string>>
  checkpointFeedbackRef: Ref<string>
  startCheckpointCountdown: (seconds: number) => void
  setIsResuming: Setter<boolean>
}

export interface WorkflowRecoveryContext extends WorkflowStateActions {
  runtimeStateEpochRef: Ref<number>
  currentRunIdRef: Ref<string | null>
  getSocketContext: () => WorkflowSocketContext
  projectPath: string | null
  projectPathRef: Ref<string | null>
  checkpointNode: WorkflowCheckpoint | null
  resumableState: ResumableState | null
  isRunning: boolean
  currentRunId: string | null
  isResuming: boolean
  backgroundRecoveryNoticeRef: Ref<string>
  manuallyStoppedRunIdsRef: Ref<Set<string>>
  workflowStopRequestedRef: Ref<boolean>
  connectWs: () => void
  logsEndRef: Ref<HTMLDivElement | null>
  logs: LogEntry[]
  focusedNode: string | null
  setNodeSchema: Setter<unknown>
  nodeParamsFocusedNodeRef: Ref<string | null>
  setNodeParams: Setter<Record<string, unknown>>
}
