import type { ReactNode } from 'react'


export interface WorkflowNode {
  id: string
  name: string
  icon: ReactNode
  status: 'idle' | 'running' | 'completed' | 'failed' | 'skipped'
  selected: boolean
  executionKind?: 'model_owned' | 'runtime_owned' | 'hybrid'
  ownerSkill?: string
  runtimeService?: string
  modelVerified?: boolean
  runtimeVerified?: boolean
  validationLabel?: string
}

export interface ResumableState {
  run_id: string
  current_node: string
  nodes_status: Record<string, string>
  config?: {
    direction?: string
    effort?: string
    assurance?: string
    options?: Record<string, any>
  }
  auto_rebuild_required?: {
    reason?: string
    blockers?: string[]
    detected_at?: number
  } | null
}

export interface DeliveryAttestation {
  applicable: boolean
  valid: boolean
  issue_count: number
  [key: string]: unknown
}

export interface WorkflowCompletion {
  execution_completed: boolean
  submission_ready: boolean
  completion_class: string
  label: string
  evidence_mode: string
  submission_blockers: string[]
  submission_advisories: string[]
  paper_pdf?: string
  attestations: Record<string, DeliveryAttestation>
}

export const toWorkflowCompletion = (
  raw: Record<string, unknown> = {},
): WorkflowCompletion => {
  const source = raw.attestations && typeof raw.attestations === 'object'
    ? raw.attestations as Record<string, unknown>
    : {}
  const attestations = Object.fromEntries(
    Object.entries(source).flatMap(([key, value]) => {
      if (!value || typeof value !== 'object') return []
      const item = value as Record<string, unknown>
      return [[key, {
        ...item,
        applicable: item.applicable !== false,
        valid: item.valid === true,
        issue_count: Number(item.issue_count || 0),
      }]]
    }),
  ) as Record<string, DeliveryAttestation>
  return {
    execution_completed: raw.execution_completed === true,
    submission_ready: raw.submission_ready === true,
    completion_class: String(raw.completion_class || 'partial_workflow_complete'),
    label: String(raw.label || 'Workflow complete'),
    evidence_mode: String(raw.evidence_mode || 'unspecified'),
    submission_blockers: Array.isArray(raw.submission_blockers)
      ? raw.submission_blockers.map(String).filter(Boolean) : [],
    submission_advisories: Array.isArray(raw.submission_advisories)
      ? raw.submission_advisories.map(String).filter(Boolean) : [],
    paper_pdf: raw.paper_pdf ? String(raw.paper_pdf) : undefined,
    attestations,
  }
}

export const DELIVERY_ATTESTATION_LABELS: Record<string, string> = {
  figures: '科研图',
  paper: 'PDF 编译',
  review: '独立评审',
  audit: '投稿审计（5+1）',
  simulation: '仿真证据包',
}

export interface RevisionDecisionBrief {
  headline: string
  whatHappened: string
  researchImpact: string
  plainIssues: string[]
  systemActions: string[]
  recommendedActions: string[]
  decisionQuestion: string
  protectedState: string
  technicalDetails: string[]
}

export interface GateComponentStatus {
  label: string
  applicable: boolean
  passed: boolean
  score?: number
  threshold?: number
  summary?: string
  issues: string[]
}

export const normalizeGateComponentStatuses = (
  raw: unknown,
): Record<string, GateComponentStatus> => {
  if (!raw || typeof raw !== 'object') return {}
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).flatMap(([key, value]) => {
      if (!value || typeof value !== 'object') return []
      const item = value as Record<string, unknown>
      const score = item.score == null ? undefined : Number(item.score)
      const threshold = item.threshold == null ? undefined : Number(item.threshold)
      return [[key, {
        label: String(item.label || key),
        applicable: item.applicable !== false,
        passed: item.passed === true,
        score: Number.isFinite(score) ? score : undefined,
        threshold: Number.isFinite(threshold) ? threshold : undefined,
        summary: item.summary == null ? undefined : String(item.summary),
        issues: Array.isArray(item.issues)
          ? item.issues.map(issue => String(issue)).filter(Boolean) : [],
      } satisfies GateComponentStatus]]
    }),
  )
}

export const formatGateNumber = (value: number): string => Number.isInteger(value)
  ? String(value)
  : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')

export interface LogEntry {
  time: string
  source: string
  message: string
  level: 'info' | 'warn' | 'error' | 'agent' | 'tool'
}

export type PaperStageStatus = 'pending' | 'running' | 'passed' | 'revision_required' | 'reused'
export type SpecialistNodeStatus = 'pending' | 'running' | 'completed' | 'failed' | 'reused'

export interface SpecialistNodeProgress {
  id: string
  nodeId: string
  name: string
  skill: string
  artifact: string
  status: SpecialistNodeStatus
}

export const normalizeSpecialistStatus = (value: unknown): SpecialistNodeStatus => {
  const status = String(value || 'pending')
  return ['pending', 'running', 'completed', 'failed', 'reused'].includes(status)
    ? status as SpecialistNodeStatus : 'pending'
}

export const toSpecialistNodeProgress = (
  value: Record<string, unknown>,
): SpecialistNodeProgress => ({
  id: String(value.id || value.subnode_id || ''),
  nodeId: String(value.node_id || ''),
  name: String(value.name || value.id || value.subnode_id || '领域专家'),
  skill: String(value.skill || ''),
  artifact: String(value.artifact || ''),
  status: normalizeSpecialistStatus(value.status),
})

export interface PaperStageProgress {
  id: string
  label: string
  status: PaperStageStatus
  attempt: number
  maximumAttempts: number
  issues: string[]
  agentStatus: string
}

export const PAPER_STAGE_DEFINITIONS = [
  { id: 'blueprint', label: '贡献与论证蓝图' },
  { id: 'introduction', label: 'Introduction' },
  { id: 'related_work', label: 'Related Work' },
  { id: 'method', label: 'Method' },
  { id: 'experiments', label: 'Experimental Setup' },
  { id: 'results', label: 'Results / Evaluation Protocol' },
  { id: 'discussion', label: 'Discussion' },
  { id: 'limitations', label: 'Limitations' },
  { id: 'conclusion', label: 'Conclusion' },
  { id: 'front_matter', label: '标题与摘要' },
  { id: 'consistency', label: '跨章节一致性' },
  { id: 'assembly', label: '投稿模板组装' },
] as const

export const createPaperStageProgress = (): PaperStageProgress[] => (
  PAPER_STAGE_DEFINITIONS.map(({ id, label }) => ({
    id, label, status: 'pending', attempt: 0, maximumAttempts: 0,
    issues: [], agentStatus: '',
  }))
)

export const normalizePersistedPaperStages = (raw: unknown): PaperStageProgress[] => {
  const records = raw && typeof raw === 'object'
    ? raw as Record<string, Record<string, unknown>> : {}
  return createPaperStageProgress().map(stage => {
    const record = records[stage.id] || {}
    const persisted = String(record.status || 'pending')
    const status: PaperStageStatus = persisted === 'completed' ? 'passed'
      : persisted === 'running' ? 'running'
        : persisted === 'revision_required' ? 'revision_required' : 'pending'
    return {
      ...stage,
      status,
      attempt: Number(record.attempts || 0),
      maximumAttempts: Number(record.attempts || 0),
      issues: Array.isArray(record.review_issues)
        ? record.review_issues.map(String).filter(Boolean) : [],
    }
  })
}

export interface ExperimentMonitorState {
  active: boolean
  backend: string
  phase: string
  experimentId: string
  metrics: Record<string, unknown>
  gpus: Array<Record<string, unknown>>
  anomaly: string
  jobId: string
  runtimeRunId: string
  diagnosisPath: string
  manifestPath: string
  proposalId: string
  proposalStatus: '' | 'pending' | 'approved' | 'rejected'
  proposalSummary: string
  proposalRationale: string
  proposalChanges: Record<string, unknown>
  proposalTrigger: string
  proposalImpact: string
  proposalQuestion: string
  proposalActions: string[]
  proposalRisks: string[]
  proposalPath: string
}

export const EMPTY_EXPERIMENT_MONITOR: ExperimentMonitorState = {
  active: false, backend: '', phase: '', experimentId: '', metrics: {}, gpus: [],
  anomaly: '', jobId: '', runtimeRunId: '', diagnosisPath: '', manifestPath: '',
  proposalId: '', proposalStatus: '', proposalSummary: '', proposalRationale: '',
  proposalChanges: {}, proposalTrigger: '', proposalImpact: '', proposalQuestion: '',
  proposalActions: [], proposalRisks: [], proposalPath: '',
}
