export interface RuntimeRunSnapshot {
  id: string
  status: string
  project_path: string
  nodes?: Array<{ id: string; status: string }>
  selected_node_ids?: string[]
  completion?: Record<string, unknown>
}

interface DurableRunSnapshot {
  run_id: string
  status: string
  runtime_active?: boolean
  phases?: Record<string, { status?: string }>
  config?: Record<string, unknown>
  completion?: Record<string, unknown>
}

export const projectKey = (value: string) => value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
const terminalTypes: Record<string, string> = {
  completed: 'workflow_completed', incomplete: 'workflow_incomplete', failed: 'workflow_failed',
  cancelled: 'workflow_cancelled', interrupted: 'workflow_interrupted',
}

/** Reuse the same terminal handler for push events and authoritative HTTP snapshots. */
export function runtimeTerminalEvent(run: RuntimeRunSnapshot, durable: DurableRunSnapshot | null) {
  if (durable?.runtime_active === true && ['running', 'paused'].includes(durable.status)) return null
  const type = terminalTypes[run.status]
  if (!type) return null
  const nodes = durable?.phases
    ? Object.fromEntries(Object.entries(durable.phases).map(([id, phase]) => [id, String(phase.status || 'pending')]))
    : Object.fromEntries((run.nodes || []).map(node => [node.id, node.status === 'running' ? 'pending' : node.status]))
  const pending = Object.keys(nodes).filter(id => !['accepted', 'completed'].includes(nodes[id]))
  return { ...(durable?.completion || run.completion || {}), type, run_id: run.id,
    nodes_status: nodes, pending_nodes: pending, current_node: pending[0] || '', config: durable?.config }
}

interface RuntimePoll {
  base: string
  projectPath: string
  currentRunId: string | null
  stopped: ReadonlySet<string>
  isCurrent(): boolean
  onRunning(run: RuntimeRunSnapshot): void
  onTerminal(event: Record<string, unknown>): void
}

/** Never let an HTTP response issued before a terminal event or new attempt restore stale UI state. */
export async function pollWorkflowRuntime(poll: RuntimePoll, request = fetch): Promise<void> {
  const response = await request(`${poll.base}/api/workflow/runs`)
  if (!response.ok || !poll.isCurrent()) return
  const runs: RuntimeRunSnapshot[] = await response.json()
  if (!Array.isArray(runs) || !poll.isCurrent()) return
  const matching = runs.filter(run => run && typeof run.id === 'string'
    && projectKey(String(run.project_path || '')) === projectKey(poll.projectPath))
  const active = matching.find(run => ['running', 'paused'].includes(run.status) && !poll.stopped.has(run.id))
  if (active) { poll.onRunning(active); return }
  if (!poll.currentRunId) return
  const observed = matching.find(run => run.id === poll.currentRunId)
  if (observed && !terminalTypes[observed.status]) return
  const state = await request(`${poll.base}/api/workflow/run-states/${encodeURIComponent(poll.currentRunId)}`
    + `?project_path=${encodeURIComponent(poll.projectPath)}`)
  const durable: DurableRunSnapshot | null = state.ok ? await state.json() : null
  if (!poll.isCurrent() || (durable && durable.run_id !== poll.currentRunId)) return
  if (!observed && (!durable || durable.runtime_active === true)) return
  const run = observed || { id: poll.currentRunId, project_path: poll.projectPath,
    status: terminalTypes[durable!.status] ? durable!.status : 'incomplete' }
  const event = runtimeTerminalEvent(run, durable)
  if (event) poll.onTerminal(event)
}
