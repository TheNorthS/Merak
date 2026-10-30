import type { WorkflowConfig } from './workflowTypes'
import {
  normalizeResearchLoopCycles,
  normalizeRevisionRounds,
} from './workflowTypes'
import type { ResumableState, WorkflowNode } from './workflowViewModels'


export const WORKFLOW_NODE_IDS = [
  'lit', 'idea', 'novelty', 'exp-design', 'exp-run', 'results', 'narrative',
  'figure', 'paper', 'review', 'audit', 'compile', 'ppt',
] as const

export const selectedNodeIdsFromRunState = (
  state: ResumableState | null,
): Set<string> => {
  const persisted = state?.config?.options?.selected_node_ids
  const rawIds = Array.isArray(persisted) ? persisted : Object.keys(state?.nodes_status || {})
  const known = new Set<string>(WORKFLOW_NODE_IDS)
  return new Set(rawIds.map(String).filter(id => known.has(id)))
}

export const toNodeStatus = (status?: string): WorkflowNode['status'] => {
  if (status === 'accepted' || status === 'completed') return 'completed'
  if (status === 'running') return 'running'
  if (status === 'failed') return 'failed'
  if (status === 'skipped') return 'skipped'
  return 'idle'
}

export const incompleteNodeIdsFromState = (
  state: ResumableState | null,
  fallbackNodes: WorkflowNode[],
): string[] => {
  if (!state?.nodes_status) {
    return fallbackNodes
      .filter(node => node.selected && node.status !== 'completed')
      .map(node => node.id)
  }
  const terminal = new Set(['accepted', 'completed'])
  return WORKFLOW_NODE_IDS.filter(id => (
    Object.hasOwn(state.nodes_status, id) && !terminal.has(state.nodes_status[id])
  ))
}

const applyRunPolicy = (
  patch: Partial<WorkflowConfig>,
  options: Record<string, any>,
): void => {
  if (typeof options.research_quality_mode === 'string' && options.research_quality_mode !== 'off') {
    patch.researchQualityMode = options.research_quality_mode as WorkflowConfig['researchQualityMode']
  }
  if (typeof options.auto_proceed === 'boolean') patch.autoProceed = options.auto_proceed
  if (typeof options.human_checkpoint === 'boolean') patch.humanCheckpoint = options.human_checkpoint
  if (Array.isArray(options.human_checkpoint_nodes)) {
    patch.humanCheckpointNodes = options.human_checkpoint_nodes.map(String)
  }
  if (typeof options.checkpoint_timeout_seconds === 'number') {
    const allowed = [60, 120, 300, 600, 1800, 3600]
    patch.checkpointTimeoutSeconds = allowed.includes(options.checkpoint_timeout_seconds)
      ? options.checkpoint_timeout_seconds : 300
  }
  if (typeof options.max_revision_rounds === 'number') {
    patch.maxRevisionRounds = normalizeRevisionRounds(options.max_revision_rounds)
  }
  if (typeof options.max_research_loop_cycles === 'number') {
    patch.maxResearchLoopCycles = normalizeResearchLoopCycles(options.max_research_loop_cycles)
  }
  if (typeof options.code_review === 'boolean') patch.codeReview = options.code_review
  if (typeof options.review_difficulty === 'string') {
    patch.reviewerDifficulty = options.review_difficulty as WorkflowConfig['reviewerDifficulty']
  }
  if (typeof options.compact === 'boolean') patch.compact = options.compact
  if (typeof options.wandb === 'boolean') patch.wandb = options.wandb
}

const applyExecutionPolicy = (
  patch: Partial<WorkflowConfig>,
  options: Record<string, any>,
): void => {
  if (typeof options.run_experiment === 'boolean') patch.runExperiment = options.run_experiment
  if (typeof options.non_experiment_evidence_mode === 'string') {
    patch.nonExperimentEvidenceMode = options.non_experiment_evidence_mode as WorkflowConfig['nonExperimentEvidenceMode']
  }
  if (typeof options.gpu_target === 'string') {
    patch.gpu = options.gpu_target as WorkflowConfig['gpu']
  }
  if (typeof options.ssh_server_id === 'string') patch.sshServer = options.ssh_server_id
  if (typeof options.gpu_info === 'string') patch.gpuInfo = options.gpu_info
  if (typeof options.max_retries === 'number') patch.maxRetries = options.max_retries
  if (typeof options.experiment_timeout_seconds === 'number') {
    patch.experimentTimeoutMinutes = Math.max(1, Math.round(options.experiment_timeout_seconds / 60))
  }
  if (typeof options.sync_project_data === 'boolean') patch.syncProjectData = options.sync_project_data
  if (typeof options.auto_stop_on_anomaly === 'boolean') patch.autoStopOnAnomaly = options.auto_stop_on_anomaly
  if (typeof options.remote_gpu_type === 'string') patch.remoteGpuType = options.remote_gpu_type
  if (typeof options.max_remote_cost_usd === 'number') patch.maxRemoteCostUsd = options.max_remote_cost_usd
  if (typeof options.vast_max_hourly_usd === 'number') patch.vastMaxHourlyUsd = options.vast_max_hourly_usd
  if (typeof options.auto_destroy_vast === 'boolean') patch.autoDestroyVast = options.auto_destroy_vast
  if (typeof options.ref_paper === 'string') patch.refPaper = options.ref_paper
  if (typeof options.base_repo === 'string') patch.baseRepo = options.base_repo
  if (Array.isArray(options.input_files)) patch.inputFiles = options.input_files.map(String).filter(Boolean)
}

const applyResearchPolicy = (
  patch: Partial<WorkflowConfig>,
  options: Record<string, any>,
): void => {
  if (options.delivery_goal === 'reviewable_draft' || options.delivery_goal === 'submission_candidate') {
    patch.deliveryGoal = options.delivery_goal
  }
  if (typeof options.research_mode === 'string') {
    patch.researchMode = options.research_mode as WorkflowConfig['researchMode']
  }
  if (typeof options.innovation_focus === 'string') patch.innovationFocus = options.innovation_focus
  if (typeof options.research_family === 'string') {
    patch.researchFamily = options.research_family as WorkflowConfig['researchFamily']
  }
  if (typeof options.study_archetype === 'string') {
    patch.studyArchetype = options.study_archetype as WorkflowConfig['studyArchetype']
  }
  if (typeof options.target_pages === 'number') patch.targetPages = options.target_pages
  if (typeof options.target_page_tolerance === 'number') patch.targetPageTolerance = options.target_page_tolerance
  if (typeof options.target_venue === 'string') patch.venue = options.target_venue
  if (typeof options.venue_template_path === 'string') patch.venueTemplatePath = options.venue_template_path
  if (typeof options.enable_patent_search === 'boolean') patch.enablePatentSearch = options.enable_patent_search
  if (typeof options.patent_date_from === 'number') patch.patentDateFrom = options.patent_date_from
  if (typeof options.patent_date_to === 'number') patch.patentDateTo = options.patent_date_to
  if (typeof options.patent_max_results === 'number') patch.patentMaxResults = options.patent_max_results
  if (typeof options.enable_meta_optimization === 'boolean') patch.enableMetaOptimization = options.enable_meta_optimization
  if (typeof options.enable_gemini === 'boolean') patch.enableGemini = options.enable_gemini
  if (typeof options.enable_gpt_image === 'boolean') patch.enableGptImage = options.enable_gpt_image
  if (typeof options.enable_zotero === 'boolean') patch.enableZotero = options.enable_zotero
  if (typeof options.enable_obsidian === 'boolean') patch.enableObsidian = options.enable_obsidian
  if (typeof options.enable_overleaf_sync === 'boolean') patch.enableOverleafSync = options.enable_overleaf_sync
  if (typeof options.overleaf_project_id === 'string') patch.overleafProjectId = options.overleaf_project_id
}

const applyLiteratureStrategy = (
  patch: Partial<WorkflowConfig>,
  strategy: Record<string, any>,
): void => {
  if (typeof strategy.literature_year_from === 'number') patch.literatureYearFrom = strategy.literature_year_from
  if (typeof strategy.literature_year_to === 'number') patch.literatureYearTo = strategy.literature_year_to
  if (typeof strategy.literature_max_papers === 'number') patch.literatureMaxPapers = strategy.literature_max_papers
  if (Array.isArray(strategy.literature_sources)) patch.literatureSources = strategy.literature_sources
  if (typeof strategy.literature_venues === 'string') patch.literatureVenues = strategy.literature_venues
  if (typeof strategy.include_keywords === 'string') patch.includeKeywords = strategy.include_keywords
  if (typeof strategy.exclude_keywords === 'string') patch.excludeKeywords = strategy.exclude_keywords
  if (typeof strategy.seed_papers === 'string') patch.seedPapers = strategy.seed_papers
  if (typeof strategy.evidence_policy === 'string') {
    patch.evidencePolicy = strategy.evidence_policy as WorkflowConfig['evidencePolicy']
  }
  if (typeof strategy.novelty_window_years === 'number') patch.noveltyWindowYears = strategy.novelty_window_years
}

export const applyResumeConfigPatch = (
  state: ResumableState | null,
): Partial<WorkflowConfig> => {
  const options = state?.config?.options || {}
  const strategy = options.research_strategy || {}
  const patch: Partial<WorkflowConfig> = {}
  if (state?.config?.direction) patch.researchDirection = state.config.direction
  if (state?.config?.effort) patch.effort = state.config.effort as WorkflowConfig['effort']
  if (state?.config?.assurance) patch.assurance = state.config.assurance as WorkflowConfig['assurance']
  applyRunPolicy(patch, options)
  applyExecutionPolicy(patch, options)
  applyResearchPolicy(patch, options)
  applyLiteratureStrategy(patch, strategy)
  return patch
}
