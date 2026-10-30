import { useEffect, useRef } from 'react'
import { API_BASE } from '../../config'
import { handleTerminalWorkflowEvent } from './workflowEventTerminal'
import { selectedNodeIdsFromRunState, toNodeStatus } from './workflowResume'
import { pollWorkflowRuntime } from './workflowRuntimeSync'
import type { WorkflowRecoveryContext } from './workflowContext'

export function useWorkflowRuntimeSync(context: WorkflowRecoveryContext) {
  const latest = useRef(context)
  latest.current = context
  useEffect(() => {
    if (!context.projectPath) return
    const project = context.projectPath
    let disposed = false
    let inFlight = false
    const reconcile = async () => {
      const snapshot = latest.current
      if (disposed || inFlight || snapshot.isResuming || snapshot.workflowStopRequestedRef.current) return
      inFlight = true
      const epoch = snapshot.runtimeStateEpochRef.current
      const isCurrent = () => !disposed && latest.current.projectPathRef.current === project
        && latest.current.runtimeStateEpochRef.current === epoch
        && !latest.current.isResuming && !latest.current.workflowStopRequestedRef.current
      try {
        await pollWorkflowRuntime({
          base: API_BASE, projectPath: project, currentRunId: snapshot.currentRunIdRef.current || snapshot.resumableState?.run_id || null,
          stopped: snapshot.manuallyStoppedRunIdsRef.current, isCurrent,
          onRunning: run => {
            const current = latest.current
            if (current.currentRunIdRef.current !== run.id || !current.isRunning) {
              current.setActiveRunId(run.id)
              current.setIsRunning(true)
              current.setResumableState(null)
              current.setWorkflowCompletion(null)
              const nodes = Object.fromEntries((run.nodes || []).map(node => [node.id, node.status]))
              const selected = selectedNodeIdsFromRunState({ run_id: run.id, current_node: '', nodes_status: nodes,
                config: { options: { selected_node_ids: run.selected_node_ids || Object.keys(nodes) } } })
              current.setNodes(previous => previous.map(node => ({ ...node,
                selected: selected.has(node.id), status: Object.hasOwn(nodes, node.id) ? toNodeStatus(nodes[node.id]) : node.status })))
              current.addLog('System', `已连接后台运行中的工作流: ${run.id}`, 'info')
            }
            current.connectWs()
          },
          onTerminal: event => {
            const current = latest.current
            if (!current.isRunning && current.resumableState?.run_id === event.run_id && event.type !== 'workflow_completed') return
            if (event.type === 'workflow_completed') current.setResumableState(null)
            handleTerminalWorkflowEvent(event, current.getSocketContext())
            void current.getSocketContext().recoverWorkflowDisplayLogs()
          },
        })
      } catch {
        // Network errors do not prove execution has ended; retry the read-only poll.
      } finally { inFlight = false }
    }
    void reconcile()
    const timer = window.setInterval(reconcile, 3000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [context.projectPath])
}
