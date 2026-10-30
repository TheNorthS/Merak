import { useWorkflowController } from './useWorkflowController'
import { WorkflowFullscreenView } from './WorkflowFullscreenView'

export function WorkflowFullscreen() {
  return <WorkflowFullscreenView model={useWorkflowController()} />
}
