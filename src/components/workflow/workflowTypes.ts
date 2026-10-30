export interface WorkflowConfig {
  researchDirection: string
  researchMode: 'from_scratch' | 'paper_code_innovation'
  innovationFocus: string
  researchFamily: 'auto' | 'machine_learning' | 'computer_systems' | 'computational_biology' | 'clinical_biomedical' | 'experimental_natural_science' | 'social_behavioral' | 'engineering_systems' | 'theoretical_formal' | 'qualitative_humanities' | 'generic_quantitative'
  studyArchetype: 'auto' | 'algorithm_benchmark' | 'observational_cohort' | 'diagnostic_prognostic' | 'intervention_trial' | 'omics_discovery' | 'controlled_experiment' | 'systems_testbed' | 'simulation_modeling' | 'formal_theory' | 'qualitative_mixed' | 'generic_empirical'
  targetPages: number
  targetPageTolerance: number
  effort: 'lite' | 'balanced' | 'max' | 'beast'
  assurance: 'draft' | 'polished' | 'conference-ready' | 'submission'
  deliveryGoal: 'submission_candidate' | 'reviewable_draft'
  researchQualityMode: 'standard' | 'rigorous'
  autoProceed: boolean
  humanCheckpoint: boolean
  humanCheckpointNodes: string[]
  checkpointTimeoutSeconds: number
  maxRevisionRounds: number
  maxResearchLoopCycles: number
  venue: string
  venueTemplatePath: string
  gpu: 'none' | 'local' | 'remote' | 'vast' | 'modal'
  sshServer: string
  runExperiment: boolean
  nonExperimentEvidenceMode: 'design_only' | 'synthetic_preview' | 'existing_results' | 'secondary_analysis'
  gpuInfo: string
  maxRetries: number
  experimentTimeoutMinutes: number
  syncProjectData: boolean
  autoStopOnAnomaly: boolean
  remoteGpuType: string
  maxRemoteCostUsd: number
  vastMaxHourlyUsd: number
  autoDestroyVast: boolean
  reviewerDifficulty: 'medium' | 'hard' | 'nightmare'
  literatureYearFrom: number
  literatureYearTo: number
  literatureMaxPapers: number
  literatureSources: string[]
  literatureVenues: string
  includeKeywords: string
  excludeKeywords: string
  seedPapers: string
  evidencePolicy: 'recent_balanced' | 'frontier_first' | 'classic_balanced' | 'systematic'
  noveltyWindowYears: number
  enablePatentSearch: boolean
  patentDateFrom: number
  patentDateTo: number
  patentMaxResults: number
  enableMetaOptimization: boolean
  refPaper: string
  baseRepo: string
  inputFiles: string[]
  compact: boolean
  codeReview: boolean
  wandb: boolean
  enableGemini: boolean
  enableGptImage: boolean
  enableZotero: boolean
  enableObsidian: boolean
  enableOverleafSync: boolean
  overleafProjectId: string
}

export const DEFAULT_AUTONOMOUS_REVISION_ROUNDS = 6
export const MIN_AUTONOMOUS_REVISION_ROUNDS = 1
export const MAX_AUTONOMOUS_REVISION_ROUNDS = 12
export const DEFAULT_RESEARCH_LOOP_CYCLES = 3
export const MAX_RESEARCH_LOOP_CYCLES = 6

export const normalizeRevisionRounds = (value: unknown): number => {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return DEFAULT_AUTONOMOUS_REVISION_ROUNDS
  return Math.min(
    MAX_AUTONOMOUS_REVISION_ROUNDS,
    Math.max(MIN_AUTONOMOUS_REVISION_ROUNDS, Math.round(parsed)),
  )
}

export const normalizeResearchLoopCycles = (value: unknown): number => {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return DEFAULT_RESEARCH_LOOP_CYCLES
  return Math.min(MAX_RESEARCH_LOOP_CYCLES, Math.max(1, Math.round(parsed)))
}

export const createDefaultWorkflowConfig = (): WorkflowConfig => ({
  researchDirection: '',
  researchMode: 'from_scratch',
  innovationFocus: '',
  researchFamily: 'auto',
  studyArchetype: 'auto',
  targetPages: 9,
  targetPageTolerance: 1,
  effort: 'balanced',
  assurance: 'draft',
  deliveryGoal: 'reviewable_draft',
  researchQualityMode: 'rigorous',
  autoProceed: true,
  humanCheckpoint: false,
  humanCheckpointNodes: ['exp-design', 'exp-run', 'paper'],
  checkpointTimeoutSeconds: 300,
  maxRevisionRounds: DEFAULT_AUTONOMOUS_REVISION_ROUNDS,
  maxResearchLoopCycles: DEFAULT_RESEARCH_LOOP_CYCLES,
  venue: 'ICLR',
  venueTemplatePath: '',
  gpu: 'none',
  sshServer: '',
  runExperiment: false,
  nonExperimentEvidenceMode: 'design_only',
  gpuInfo: '',
  maxRetries: 3,
  experimentTimeoutMinutes: 360,
  syncProjectData: false,
  autoStopOnAnomaly: true,
  remoteGpuType: 'A100',
  maxRemoteCostUsd: 10,
  vastMaxHourlyUsd: 2,
  autoDestroyVast: true,
  reviewerDifficulty: 'medium',
  literatureYearFrom: 2021,
  literatureYearTo: new Date().getFullYear(),
  literatureMaxPapers: 35,
  literatureSources: ['arxiv', 'semantic_scholar'],
  literatureVenues: '',
  includeKeywords: '',
  excludeKeywords: '',
  seedPapers: '',
  evidencePolicy: 'recent_balanced',
  noveltyWindowYears: 3,
  enablePatentSearch: false,
  patentDateFrom: 2000,
  patentDateTo: new Date().getFullYear(),
  patentMaxResults: 15,
  enableMetaOptimization: false,
  refPaper: '',
  baseRepo: '',
  inputFiles: [],
  compact: false,
  codeReview: true,
  wandb: false,
  enableGemini: false,
  enableGptImage: false,
  enableZotero: false,
  enableObsidian: false,
  enableOverleafSync: false,
  overleafProjectId: '',
})
