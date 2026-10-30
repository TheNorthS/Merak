import { API_BASE } from '../../config'
import type { LogEntry } from './workflowViewModels'

export const WORKFLOW_LOG_VIEW_LIMIT = 5000

interface DisplayLogResponse {
  entries?: unknown
}

function isLogEntry(value: unknown): value is LogEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Partial<LogEntry>
  return typeof entry.time === 'string'
    && typeof entry.source === 'string'
    && typeof entry.message === 'string'
    && ['info', 'warn', 'error', 'agent', 'tool'].includes(String(entry.level))
}

export async function loadWorkflowDisplayLogs(
  projectPath: string,
  runId = '',
): Promise<LogEntry[]> {
  const query = new URLSearchParams({
    project_path: projectPath,
    limit: String(WORKFLOW_LOG_VIEW_LIMIT),
  })
  if (runId) query.set('run_id', runId)
  const response = await fetch(`${API_BASE}/api/workflow/display-logs?${query}`)
  if (!response.ok) {
    throw new Error(`Workflow log recovery failed (${response.status})`)
  }
  const payload = await response.json() as DisplayLogResponse
  return Array.isArray(payload.entries) ? payload.entries.filter(isLogEntry) : []
}

export function mergeWorkflowDisplayLogs(
  durableLogs: LogEntry[],
  localLogs: LogEntry[],
): LogEntry[] {
  const durableKeys = new Set(durableLogs.map(entry => (
    `${entry.time}\u0000${entry.source}\u0000${entry.message}\u0000${entry.level}`
  )))
  const localOnly = localLogs.filter(entry => !durableKeys.has(
    `${entry.time}\u0000${entry.source}\u0000${entry.message}\u0000${entry.level}`,
  ))
  return [...durableLogs, ...localOnly].slice(-WORKFLOW_LOG_VIEW_LIMIT)
}
