import { WORKFLOW_NODES } from '@shared/workflow-nodes'

type Envelope = { type: string; run_id?: string } & Record<string, unknown>
export type WorkflowMessage = Envelope & (
  | { type: 'node_started' | 'node_accepted' | 'node_failed'; node_id: string }
  | { type: 'workflow_completed' | 'workflow_failed' | 'workflow_cancelled'; run_id: string }
  | { type: string }
)
const nodeIds = new Set<string>(WORKFLOW_NODES.map(node => node.id))
const nodeEvents = new Set(['node_started', 'node_accepted', 'node_failed'])
const terminalEvents = new Set(['workflow_completed', 'workflow_failed', 'workflow_cancelled', 'workflow_error', 'workflow_interrupted', 'workflow_incomplete'])

/** Validate state-changing envelopes before events can mutate the active UI. */
export function decodeWorkflowMessage(text: string): WorkflowMessage {
  const raw: unknown = JSON.parse(text)
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid workflow envelope')
  const value = raw as Record<string, unknown>
  if (typeof value.type !== 'string' || !value.type) throw new Error('Workflow event type is missing')
  if (value.run_id !== undefined && typeof value.run_id !== 'string') throw new Error('Invalid run identity')
  if (nodeEvents.has(value.type) && (typeof value.node_id !== 'string' || !nodeIds.has(value.node_id))) {
    throw new Error('Unknown workflow node')
  }
  if (terminalEvents.has(value.type) && !value.run_id) throw new Error('Terminal event has no run identity')
  if (value.nodes_status !== undefined && (!value.nodes_status || typeof value.nodes_status !== 'object' || Array.isArray(value.nodes_status))) {
    throw new Error('Invalid workflow state map')
  }
  return value as WorkflowMessage
}
