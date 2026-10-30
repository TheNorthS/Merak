import { useState, useEffect } from 'react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { type IntegrationState, type SshServerConfig, readSshServers, syncSshServers } from '@/lib/connection-status'
import { type WorkflowConfig } from './workflowTypes'
import { ConfigPanelPrimary } from './ConfigPanelPrimary'
import { ConfigPanelSecondary } from './ConfigPanelSecondary'

export interface ConfigPanelModel {
  config: WorkflowConfig
  onUpdate: (patch: Partial<WorkflowConfig>) => void
  integrationStatus: Record<string, IntegrationState>
  experimentNodeSelected: boolean
  compileNodeSelected: boolean
  venuePageLimits: Record<string, number>
  experimentExecutionEnabled: boolean
  submissionAssurance: boolean
  importedEvidenceMode: boolean
  workflowProjectPath: string | null
  inputFileError: string
  addWorkflowInput: () => Promise<void>
  overleafProjects: { project_id: string; local_path: string; branch: string; credentials_available: boolean; verified: boolean; }[]
  sshServers: SshServerConfig[]
  verifiedSshServers: SshServerConfig[]
  sourceOptions: { id: string; label: string; }[]
  toggleLiteratureSource: (source: string, checked: boolean) => void
  isSourceConfigured: (source: string) => boolean
}

export function useConfigPanelModel({ config, onUpdate, integrationStatus, experimentNodeSelected, compileNodeSelected }: {
  config: WorkflowConfig
  onUpdate: (patch: Partial<WorkflowConfig>) => void
  integrationStatus: Record<string, IntegrationState>
  experimentNodeSelected: boolean
  compileNodeSelected: boolean
}) {
  type OverleafProjectOption = {
    project_id: string
    local_path: string
    branch: string
    credentials_available: boolean
    verified: boolean
  }
  const venuePageLimits: Record<string, number> = { ICLR: 9, NeurIPS: 9, ICML: 9, CVPR: 8, ACL: 8, AAAI: 7 }
  const experimentExecutionEnabled = config.runExperiment && experimentNodeSelected
  const submissionAssurance = ['conference-ready', 'submission'].includes(config.assurance)
  const importedEvidenceMode = ['existing_results', 'secondary_analysis'].includes(
    config.nonExperimentEvidenceMode,
  )
  useEffect(() => {
    if (!experimentExecutionEnabled) {
      if (config.gpu !== 'none' || config.sshServer || config.gpuInfo || config.wandb) {
        onUpdate({ gpu: 'none', sshServer: '', gpuInfo: '', wandb: false })
      }
      return
    }
    if (config.gpu === 'none') onUpdate({ gpu: 'local' })
  }, [config.gpu, config.gpuInfo, config.sshServer, config.wandb, experimentExecutionEnabled])
  const workflowProjectPath = useWorkspaceStore(state => state.projectPath)
  const [inputFileError, setInputFileError] = useState('')
  const addWorkflowInput = async () => {
    const selected = await window.merakIDE?.fs.openFile([
      { name: 'Research files', extensions: ['md', 'txt', 'tex', 'bib', 'json', 'yaml', 'yml', 'csv', 'tsv', 'py', 'ipynb', 'pdf'] },
      { name: 'All files', extensions: ['*'] },
    ])
    if (!selected) return
    const normalize = (value: string) => value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    const projectKey = normalize(workflowProjectPath || '')
    const selectedKey = normalize(selected)
    if (!projectKey || (selectedKey !== projectKey && !selectedKey.startsWith(projectKey + '/'))) {
      setInputFileError('补充输入必须位于当前项目内；外部论文和代码请使用“基于论文 + 代码创新”模式。')
      return
    }
    if (config.inputFiles.some(path => normalize(path) === selectedKey)) {
      setInputFileError('')
      return
    }
    setInputFileError('')
    onUpdate({ inputFiles: [...config.inputFiles, selected] })
  }
  const [overleafProjects, setOverleafProjects] = useState<OverleafProjectOption[]>([])
  const [sshServers, setSshServers] = useState<SshServerConfig[]>(readSshServers)
  useEffect(() => {
    let active = true
    const normalize = (value: string) => value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    const refresh = () => {
      fetch(API_BASE + '/api/overleaf/projects')
        .then(response => response.ok ? response.json() : [])
        .then(data => {
          if (!active) return
          const expected = workflowProjectPath ? normalize(workflowProjectPath + '/paper') : ''
          const projects = Array.isArray(data)
            ? data.filter(item => item?.verified && normalize(String(item.local_path || '')) === expected)
            : []
          setOverleafProjects(projects)
        })
        .catch(() => { if (active) setOverleafProjects([]) })
    }
    refresh()
    window.addEventListener('merak-ide:overleaf-changed', refresh)
    return () => {
      active = false
      window.removeEventListener('merak-ide:overleaf-changed', refresh)
    }
  }, [workflowProjectPath])
  const overleafProjectIds = overleafProjects.map(project => project.project_id).join('|')
  useEffect(() => {
    if (!config.enableOverleafSync) return
    if (!compileNodeSelected || !overleafProjects.some(project => project.project_id === config.overleafProjectId)) {
      onUpdate({ enableOverleafSync: false, overleafProjectId: '' })
    }
  }, [compileNodeSelected, config.enableOverleafSync, config.overleafProjectId, overleafProjectIds])

  useEffect(() => {
    let active = true
    const refreshFromStorage = () => setSshServers(readSshServers())
    syncSshServers()
      .then(servers => { if (active) setSshServers(servers) })
      .catch(() => { if (active) refreshFromStorage() })
    window.addEventListener('merak-ide:ssh-servers-changed', refreshFromStorage)
    return () => {
      active = false
      window.removeEventListener('merak-ide:ssh-servers-changed', refreshFromStorage)
    }
  }, [])

  const verifiedSshServers = sshServers.filter(server => server.verification?.verified)
  const verifiedSshServerIds = verifiedSshServers.map(server => server.id).join('|')
  useEffect(() => {
    if (config.gpu !== 'remote') return
    if (verifiedSshServers.length === 0) {
      onUpdate({ gpu: 'local', sshServer: '' })
    } else if (config.sshServer && !verifiedSshServers.some(server => server.id === config.sshServer)) {
      onUpdate({ sshServer: '' })
    }
  }, [config.gpu, config.sshServer, verifiedSshServerIds])

  useEffect(() => {
    const selectedStatus = config.gpu === 'vast'
      ? integrationStatus.vastai
      : config.gpu === 'modal'
        ? integrationStatus.modal
        : undefined
    if (selectedStatus && !selectedStatus.verified) onUpdate({ gpu: 'local', sshServer: '' })
  }, [config.gpu, integrationStatus.vastai?.verified, integrationStatus.modal?.verified])
  const sourceOptions = [
    { id: 'arxiv', label: 'arXiv' },
    { id: 'semantic_scholar', label: 'Semantic Scholar' },
    { id: 'openalex', label: 'OpenAlex' },
    { id: 'pubmed', label: 'PubMed' },
    { id: 'web', label: 'Web' },
    { id: 'gemini', label: 'Gemini' },
    { id: 'zotero', label: 'Zotero' },
    { id: 'obsidian', label: 'Obsidian' },
  ]
  const toggleLiteratureSource = (source: string, checked: boolean) => {
    const next = checked
      ? Array.from(new Set([...config.literatureSources, source]))
      : config.literatureSources.filter(s => s !== source)
    onUpdate({ literatureSources: next.length > 0 ? next : ['arxiv'] })
  }
  const isSourceConfigured = (source: string) => {
    if (source === 'web') return integrationStatus.exa?.verified === true
    if (source === 'gemini') return integrationStatus.gemini?.verified === true
    if (source === 'zotero') return integrationStatus.zotero?.verified === true
    if (source === 'obsidian') return integrationStatus.obsidian?.verified === true
    return true
  }

    return {
    config,
    onUpdate,
    integrationStatus,
    experimentNodeSelected,
    compileNodeSelected,
    venuePageLimits,
    experimentExecutionEnabled,
    submissionAssurance,
    importedEvidenceMode,
    workflowProjectPath,
    inputFileError,
    addWorkflowInput,
    overleafProjects,
    sshServers,
    verifiedSshServers,
    sourceOptions,
    toggleLiteratureSource,
    isSourceConfigured,
  }
}

export function ConfigPanel(props: {
  config: WorkflowConfig
  onUpdate: (patch: Partial<WorkflowConfig>) => void
  integrationStatus: Record<string, IntegrationState>
  experimentNodeSelected: boolean
  compileNodeSelected: boolean
}) {
  const model = useConfigPanelModel(props)
  return (
    <div className="h-full overflow-y-auto bg-card">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Configuration</h3>
      </div>
      <div className="p-4 space-y-4">
        <ConfigPanelPrimary model={model} />
        <ConfigPanelSecondary model={model} />
      </div>
    </div>
  )
}
