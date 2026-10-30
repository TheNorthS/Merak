import { useEffect, useRef, useState } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'

import {
  readDiskWorkflowUiState,
  readPersistedWorkflowUiState,
  readRunWorkflowUiState,
  writeDiskWorkflowUiState,
  writePersistedWorkflowUiState,
  type PersistedWorkflowUiState,
} from './workflowPersistence'
import {
  createDefaultWorkflowConfig,
  type WorkflowConfig,
} from './workflowTypes'
import type { WorkflowCompletion, WorkflowNode } from './workflowViewModels'


const toProjectIndependentConfig = (config: WorkflowConfig): WorkflowConfig => ({
  ...config,
  inputFiles: [],
  enableOverleafSync: false,
  overleafProjectId: '',
})


interface WorkflowConfigPersistenceInput {
  projectPath: string | null
  nodes: WorkflowNode[]
  nodeParams: Record<string, unknown>
  focusedNode: string | null
  setNodes: Dispatch<SetStateAction<WorkflowNode[]>>
  setNodeParams: Dispatch<SetStateAction<Record<string, any>>>
  setFocusedNode: Dispatch<SetStateAction<string | null>>
  setWorkflowCompletion: Dispatch<SetStateAction<WorkflowCompletion | null>>
  nodeParamsFocusedNodeRef: MutableRefObject<string | null>
}


export function useWorkflowConfigPersistence({
  projectPath,
  nodes,
  nodeParams,
  focusedNode,
  setNodes,
  setNodeParams,
  setFocusedNode,
  setWorkflowCompletion,
  nodeParamsFocusedNodeRef,
}: WorkflowConfigPersistenceInput) {
  const [config, setConfig] = useState<WorkflowConfig>(createDefaultWorkflowConfig)
  const configProjectRef = useRef(projectPath)
  const resetNoProjectConfigRef = useRef(false)
  const configEditRevisionRef = useRef(0)
  // `undefined` means hydration is pending; `null` is the hydrated no-project
  // draft. Keeping these states distinct prevents premature persistence.
  const [hydratedProject, setHydratedProject] = useState<string | null | undefined>(undefined)

  useEffect(() => {
    if (configProjectRef.current === projectPath) return
    const previousProjectPath = configProjectRef.current
    configProjectRef.current = projectPath
    setHydratedProject(undefined)
    setWorkflowCompletion(null)
    // Closing a project is an explicit return to the blank workflow state.
    // Mark that transition so the hydration effect cannot restore an older
    // no-project draft over these defaults.
    if (!projectPath && previousProjectPath) {
      resetNoProjectConfigRef.current = true
      setConfig(createDefaultWorkflowConfig())
    } else if (projectPath) {
      resetNoProjectConfigRef.current = false
      setConfig(createDefaultWorkflowConfig())
    }
  }, [projectPath, setWorkflowCompletion])

  useEffect(() => {
    setHydratedProject(undefined)
    let cancelled = false
    const editRevisionAtStart = configEditRevisionRef.current
    const apply = (persisted: PersistedWorkflowUiState | null) => {
      if (cancelled) return
      if (persisted?.config && configEditRevisionRef.current === editRevisionAtStart) {
        setConfig(previous => ({ ...previous, ...persisted.config }))
      }
      if (Array.isArray(persisted?.selectedNodeIds)) {
        const selected = new Set(persisted.selectedNodeIds.map(String))
        setNodes(previous => previous.map(node => ({
          ...node, selected: selected.has(node.id),
        })))
      }
      setNodeParams(
        persisted?.nodeParams && typeof persisted.nodeParams === 'object'
          ? persisted.nodeParams
          : {},
      )
      const persistedFocus = persisted?.focusedNode || null
      nodeParamsFocusedNodeRef.current = persistedFocus
      setFocusedNode(persistedFocus)
      setHydratedProject(projectPath)
    }
    const hydrate = async () => {
      if (!projectPath) {
        // A project-to-no-project transition must show fresh defaults. Only a
        // cold start may restore the saved no-project draft.
        const resetToDefaults = resetNoProjectConfigRef.current
        resetNoProjectConfigRef.current = false
        const persisted = resetToDefaults ? null : readPersistedWorkflowUiState(null)
        if (resetToDefaults && configEditRevisionRef.current === editRevisionAtStart) {
          setConfig(createDefaultWorkflowConfig())
        } else if (persisted?.config && configEditRevisionRef.current === editRevisionAtStart) {
          setConfig(previous => toProjectIndependentConfig({
            ...previous,
            ...persisted.config,
          }))
        } else {
          setConfig(previous => toProjectIndependentConfig(previous))
        }
        setNodeParams({})
        nodeParamsFocusedNodeRef.current = null
        setFocusedNode(null)
        setHydratedProject(null)
        return
      }
      const local = readPersistedWorkflowUiState(projectPath)
      const disk = await readDiskWorkflowUiState(projectPath)
      const run = disk || local ? null : await readRunWorkflowUiState(projectPath)
      apply(disk || local || run)
    }
    void hydrate()
    return () => { cancelled = true }
  }, [projectPath, setFocusedNode, setNodeParams, setNodes, nodeParamsFocusedNodeRef])

  useEffect(() => {
    if (hydratedProject === undefined || hydratedProject !== projectPath) return
    const state: PersistedWorkflowUiState = projectPath
      ? {
          version: 1,
          config,
          selectedNodeIds: nodes.filter(node => node.selected).map(node => node.id),
          nodeParams,
          focusedNode,
        }
      : {
          version: 1,
          config: toProjectIndependentConfig(config),
        }
    writePersistedWorkflowUiState(projectPath, state)
    if (projectPath) void writeDiskWorkflowUiState(projectPath, state)
  }, [projectPath, hydratedProject, config, nodes, nodeParams, focusedNode])

  const updateWorkflowConfig = (patch: Partial<WorkflowConfig>) => {
    configEditRevisionRef.current += 1
    setConfig(previous => ({ ...previous, ...patch }))
  }
  return {
    config,
    setConfig,
    updateWorkflowConfig,
    workflowUiHydratedProject: hydratedProject,
    setWorkflowUiHydratedProject: setHydratedProject,
  }
}
