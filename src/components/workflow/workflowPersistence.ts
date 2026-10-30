import { API_BASE } from '../../config'
import { applyResumeConfigPatch } from './workflowResume'
import type { ResumableState } from './workflowViewModels'

import {
  type WorkflowConfig,
} from './workflowTypes'


export interface PersistedWorkflowUiState {
  version: 1
  config?: Partial<WorkflowConfig>
  selectedNodeIds?: string[]
  nodeParams?: Record<string, unknown>
  focusedNode?: string | null
}

export const workflowUiStorageKey = (projectPath: string | null) => {
  const normalized = (projectPath || '__no_project__')
    .replace(/\\/g, '/')
    .replace(/\/+$/, '')
    .toLowerCase()
  return `merak-ide:workflow-ui:${encodeURIComponent(normalized)}`
}

const workflowUiDiskPath = (projectPath: string) => {
  const separator = projectPath.includes('\\') ? '\\' : '/'
  return `${projectPath.replace(/[\\/]+$/, '')}${separator}.merak${separator}workflow-ui.json`
}

export const readPersistedWorkflowUiState = (
  projectPath: string | null,
): PersistedWorkflowUiState | null => {
  try {
    const raw = localStorage.getItem(workflowUiStorageKey(projectPath))
    if (!raw) return null
    const parsed = JSON.parse(raw) as PersistedWorkflowUiState
    return parsed && parsed.version === 1 ? parsed : null
  } catch {
    return null
  }
}

export const writePersistedWorkflowUiState = (
  projectPath: string | null,
  state: PersistedWorkflowUiState,
) => {
  try {
    localStorage.setItem(workflowUiStorageKey(projectPath), JSON.stringify(state))
  } catch {
    // Persistence is best-effort and never blocks workflow execution.
  }
}

const isPersistedWorkflowUiState = (
  value: unknown,
): value is PersistedWorkflowUiState => Boolean(
  value
  && typeof value === 'object'
  && (value as PersistedWorkflowUiState).version === 1,
)

export const readDiskWorkflowUiState = async (
  projectPath: string,
): Promise<PersistedWorkflowUiState | null> => {
  try {
    const response = await fetch(
      `${API_BASE}/api/files/read?path=${encodeURIComponent(workflowUiDiskPath(projectPath))}`,
    )
    if (!response.ok) return null
    const payload = await response.json()
    const parsed = JSON.parse(String(payload?.content || '')) as unknown
    return isPersistedWorkflowUiState(parsed) ? parsed : null
  } catch {
    return null
  }
}

export const writeDiskWorkflowUiState = async (
  projectPath: string,
  state: PersistedWorkflowUiState,
): Promise<void> => {
  try {
    await fetch(`${API_BASE}/api/files/write`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: workflowUiDiskPath(projectPath),
        content: JSON.stringify(state, null, 2),
        encoding: 'utf-8',
      }),
    })
  } catch {
    // localStorage remains the fast fallback when disk persistence is unavailable.
  }
}

/**
 * Recover configuration from a current-schema run only when dedicated UI
 * persistence is absent. This uses the same mapper as explicit run resume.
 */
export const readRunWorkflowUiState = async (
  projectPath: string,
): Promise<PersistedWorkflowUiState | null> => {
  try {
    const query = `project_path=${encodeURIComponent(projectPath)}`
    const response = await fetch(`${API_BASE}/api/workflow/run-states?${query}`)
    if (!response.ok) return null
    const payload = await response.json() as { runs?: Array<{ run_id?: unknown }> }
    const run = payload.runs?.find(item => typeof item.run_id === 'string')
    if (!run || typeof run.run_id !== 'string') return null
    const detail = await fetch(
      `${API_BASE}/api/workflow/run-states/${encodeURIComponent(run.run_id)}?${query}`,
    )
    if (!detail.ok) return null
    const stored = await detail.json() as Record<string, unknown>
    if (stored.schema !== 1 || !stored.config || typeof stored.config !== 'object') return null
    // The shared mapper validates each consumed field; this cast is solely the
    // JSON adapter boundary, not a second historical configuration converter.
    const state: ResumableState = {
      run_id: run.run_id, current_node: '', nodes_status: {},
      config: stored.config as ResumableState['config'],
    }
    return { version: 1, config: applyResumeConfigPatch(state) }
  } catch {
    return null
  }
}
