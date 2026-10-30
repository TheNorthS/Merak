import { evidenceVersionApproval } from './evidenceVersionApproval'
import { useEffect } from 'react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { createDefaultWorkflowConfig } from './workflowTypes'
import { EMPTY_EXPERIMENT_MONITOR, createPaperStageProgress, toWorkflowCompletion, type ExperimentMonitorState, type LogEntry, type ResumableState, type WorkflowNode } from './workflowViewModels'
import { applyResumeConfigPatch, incompleteNodeIdsFromState, selectedNodeIdsFromRunState, toNodeStatus } from './workflowResume'
import { workflowUiStorageKey } from './workflowPersistence'

type WorkflowCommandContext = Record<string, any>

export function useWorkflowCommands(context: WorkflowCommandContext) {
  const { DEFAULT_NODES, focusedNode, projectPath, config, setPaperStages, setPaperProgressVisible, setIsRunning, setWorkflowCompletion, nodeParams, integrationStatus, setActiveRunId, connectWs, setLogs, suppressedToolTextRef, agentOutputFlushTimerRef, agentOutputBufferRef, nodes, pendingRunIdsRef, setPendingRunIds, setProjectCreationError, setShowProjectForm, setSpecialistNodes, setNodes, closeWorkflowWs, currentRunId, setPausedRunIdSafe, pausedRunIdRef, isResuming, setConfig, checkpointFeedback, setCheckpointActionError, setIsResuming, setCheckpointNode, setCheckpointFeedback, setResumableState, checkpointNode, checkpointFeedbackRef, isExtendingCheckpoint, setIsExtendingCheckpoint, checkpointSecondsLeft, startCheckpointCountdown, isAcknowledgingCheckpoint, setIsAcknowledgingCheckpoint, experimentMonitor, setExperimentMonitor, adjustmentBusy, setAdjustmentBusy, adjustmentDraft, setAdjustmentDialogOpen, setApprovalDialogOpen, setWorkflowUiHydratedProject, setAdjustmentDraft, setFocusedNode, setNodeSchema, setNodeParams, nodeParamsFocusedNodeRef, manuallyStoppedRunIdsRef, workflowStopRequestedRef } = context
const handleRunSingleNode = async () => {
    if (!focusedNode) return
    if (!projectPath) {
      addLog('System', '请先打开或创建研究项目，再执行单个节点。', 'warn')
      return
    }
    if (config.researchMode === 'paper_code_innovation' && (!config.refPaper.trim() || !config.baseRepo.trim())) {
      addLog('System', '论文 + 代码创新模式需要选择本地参考论文和代码目录。', 'error')
      return
    }
    if (focusedNode === 'paper') {
      setPaperStages(createPaperStageProgress())
      setPaperProgressVisible(true)
    }
    workflowStopRequestedRef.current = false
    setIsRunning(true)
    setWorkflowCompletion(null)
    addLog('System', `Running single node: ${focusedNode}`, 'info')

    try {
      const res = await fetch(`${API_BASE}/api/workflow/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_ids: [focusedNode],
          project_path: projectPath,
          research_direction: nodeParams.query || nodeParams.direction || nodeParams.idea || config.researchDirection,
          effort: config.effort,
          assurance: config.assurance,
          delivery_goal: config.deliveryGoal,
          research_quality_mode: config.researchQualityMode,
          auto_proceed: config.autoProceed,
          human_checkpoint: config.humanCheckpoint,
          human_checkpoint_nodes: config.humanCheckpointNodes,
          checkpoint_timeout_seconds: config.checkpointTimeoutSeconds,
          max_revision_rounds: config.maxRevisionRounds,
          max_research_loop_cycles: config.maxResearchLoopCycles,
          code_review: config.codeReview,
          compact: config.compact,
          wandb: config.wandb,
          review_difficulty: config.reviewerDifficulty,
          gpu_target: config.gpu,
          ssh_server_id: config.sshServer,
          run_experiment: config.runExperiment,
          non_experiment_evidence_mode: config.nonExperimentEvidenceMode,
          illustration_mode: 'auto',
          gpu_info: config.gpuInfo,
          max_retries: config.maxRetries,
          experiment_timeout_seconds: config.experimentTimeoutMinutes * 60,
          sync_project_data: config.syncProjectData,
          auto_stop_on_anomaly: config.autoStopOnAnomaly,
          remote_gpu_type: config.remoteGpuType,
          max_remote_cost_usd: config.maxRemoteCostUsd,
          vast_max_hourly_usd: config.vastMaxHourlyUsd,
          auto_destroy_vast: config.autoDestroyVast,
          research_mode: config.researchMode,
          innovation_focus: config.innovationFocus,
          ref_paper: config.refPaper,
          base_repo: config.baseRepo,
          input_files: config.inputFiles,
          node_inputs: nodeParams,
          research_family: config.researchFamily,
          study_archetype: config.studyArchetype,
          target_venue: config.venue,
          venue_template_path: config.venueTemplatePath,
          target_pages: config.targetPages,
          target_page_tolerance: config.targetPageTolerance,
          literature_year_from: config.literatureYearFrom,
          literature_year_to: config.literatureYearTo,
          literature_max_papers: config.literatureMaxPapers,
          literature_sources: config.literatureSources.filter((source: string) => (
            (source !== 'gemini' || integrationStatus.gemini?.verified === true)
            && (source !== 'zotero' || integrationStatus.zotero?.verified === true)
            && (source !== 'obsidian' || integrationStatus.obsidian?.verified === true)
          )),
          literature_venues: config.literatureVenues,
          include_keywords: config.includeKeywords,
          exclude_keywords: config.excludeKeywords,
          seed_papers: config.seedPapers,
          evidence_policy: config.evidencePolicy,
          novelty_window_years: config.noveltyWindowYears,
          enable_patent_search: config.enablePatentSearch && integrationStatus.patent?.verified === true,
          patent_date_from: config.patentDateFrom,
          patent_date_to: config.patentDateTo,
          patent_max_results: config.patentMaxResults,
          enable_meta_optimization: config.enableMetaOptimization,
          enable_gemini: config.enableGemini && integrationStatus.gemini?.verified === true,
          enable_gpt_image: config.enableGptImage && integrationStatus.gpt_image?.verified === true,
          enable_zotero: config.enableZotero && integrationStatus.zotero?.verified === true,
          enable_obsidian: config.enableObsidian && integrationStatus.obsidian?.verified === true,
          enable_overleaf_sync: config.enableOverleafSync && focusedNode === 'compile' && Boolean(config.overleafProjectId),
          overleaf_project_id: config.overleafProjectId,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        addLog('System', `节点已提交: ${data.run_id}`, 'info')
        setActiveRunId(data.run_id)
        connectWs()
      } else {
        const data = await res.json().catch(() => null)
        const issues = Array.isArray(data?.detail?.issues) ? data.detail.issues.join('；') : data?.detail
        addLog('System', `无法启动节点: ${issues || res.statusText}`, 'error')
        setIsRunning(false)
      }
    } catch (err: any) {
      addLog('System', `Error: ${err.message}`, 'error')
      setIsRunning(false)
    }
  }

  const addLog = (source: string, message: string, level: LogEntry['level'] = 'info') => {
    const clean = String(message || '').trim()
    if (!clean) return
    setLogs((prev: LogEntry[]) => {
      const last = prev[prev.length - 1]
      if (last && last.source === source && last.message === clean) return prev
      return [...prev, { time: new Date().toLocaleTimeString(), source, message: clean, level }]
    })
  }

  const cleanAgentOutput = (text: string) => {
    const raw = String(text || '')
    if (/<\/?tool_use\b|<arg\s+name=/i.test(raw)) {
      if (!suppressedToolTextRef.current) {
        suppressedToolTextRef.current = true
        addLog('System', '已拦截模型输出的伪工具调用文本，后端会按工具协议处理。', 'warn')
      }
      return ''
    }
    return raw.replace(/\r/g, '').replace(/\s+/g, ' ').trim()
  }

  const flushAgentOutput = () => {
    if (agentOutputFlushTimerRef.current) {
      clearTimeout(agentOutputFlushTimerRef.current)
      agentOutputFlushTimerRef.current = null
    }
    const clean = cleanAgentOutput(agentOutputBufferRef.current)
    agentOutputBufferRef.current = ''
    if (clean) addLog('Agent', clean.slice(0, 1200), 'agent')
  }

  const queueAgentOutput = (chunk: string) => {
    if (!chunk) return
    if (/<\/?tool_use\b|<arg\s+name=/i.test(chunk)) {
      cleanAgentOutput(chunk)
      return
    }
    agentOutputBufferRef.current += chunk
    const buffered = agentOutputBufferRef.current
    if (buffered.length >= 500 || /[。！？.!?\n]$/.test(chunk)) {
      flushAgentOutput()
      return
    }
    if (agentOutputFlushTimerRef.current) clearTimeout(agentOutputFlushTimerRef.current)
    agentOutputFlushTimerRef.current = setTimeout(flushAgentOutput, 700)
  }

  const handleRun = async (overrideNodeIds?: string[], forceProjectPath?: string) => {
    workflowStopRequestedRef.current = false
    if (!config.researchDirection.trim()) return
    const selectedIds = overrideNodeIds || nodes.filter((n: WorkflowNode) => n.selected).map((n: WorkflowNode) => n.id)
    const submissionAssurance = ['conference-ready', 'submission'].includes(config.assurance)
    const experimentExecutionSelected = config.runExperiment && selectedIds.includes('exp-run')
    const syntheticPreviewSelected = (
      !experimentExecutionSelected
      && config.nonExperimentEvidenceMode === 'synthetic_preview'
    )
    if (
      submissionAssurance
      && !experimentExecutionSelected
      && config.nonExperimentEvidenceMode === 'design_only'
    ) {
      addLog(
        'System',
        '投稿级工作流不能只使用研究设计。请选择完整仿真结果稿、已有真实结果或公开结果二次分析，或启用并选择真实实验节点。',
        'error',
      )
      return
    }
    if (syntheticPreviewSelected) {
      addLog(
        'System',
        submissionAssurance
          ? '将按投稿级结构生成完整仿真研究论文及配套结果图表；论文只在 Experimental Setup 中以普通科研语言说明一次确定性仿真基准，详细来源与投稿资格保留在侧车清单。'
          : '将生成完整仿真研究论文及配套结果图表；论文只在 Experimental Setup 中说明一次确定性仿真基准，图题、表题和正文不重复警示。',
        'warn',
      )
    }
    if (config.researchMode === 'paper_code_innovation' && (!config.refPaper.trim() || !config.baseRepo.trim())) {
      addLog('System', '论文 + 代码创新模式需要选择本地参考论文和代码目录。', 'error')
      return
    }

    const effectivePath = forceProjectPath || projectPath

    // 检查是否有项目打开
    if (!effectivePath || effectivePath === '.') {
      pendingRunIdsRef.current = selectedIds
      setPendingRunIds(selectedIds)
      setProjectCreationError('')
      setShowProjectForm(true)
      return
    }

    // 确保项目有约定目录
    try {
      const scaffoldResponse = await fetch(`${API_BASE}/api/projects/scaffold`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: effectivePath,
          name: effectivePath.split(/[\\/]/).pop() || 'research',
          venue: config.venue,
          mode: 'ensure',
        }),
      })
      const scaffoldPayload = await scaffoldResponse.json().catch(() => ({}))
      if (!scaffoldResponse.ok) {
        throw new Error(scaffoldPayload.detail || scaffoldResponse.statusText)
      }
    } catch (error) {
      addLog('System', `项目结构初始化失败：${error instanceof Error ? error.message : String(error)}`, 'error')
      return
    }

    setIsRunning(true)
    setWorkflowCompletion(null)
    setSpecialistNodes([])
    setNodes((prev: WorkflowNode[]) => prev.map(node => ({
      ...node,
      executionKind: undefined,
      ownerSkill: undefined,
      runtimeService: undefined,
      modelVerified: false,
      runtimeVerified: false,
    })))
    addLog('System', '启动工作流...', 'info')

    if (selectedIds.includes('paper')) {
      setPaperStages(createPaperStageProgress())
      setPaperProgressVisible(true)
    }
    addLog('System', `运行 ${selectedIds.length} 个节点: ${selectedIds.join(', ')}`, 'info')

    try {
      const res = await fetch(`${API_BASE}/api/workflow/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_ids: selectedIds,
          project_path: effectivePath,
          research_direction: config.researchDirection,
          effort: config.effort,
          assurance: config.assurance,
          delivery_goal: config.deliveryGoal,
          research_quality_mode: config.researchQualityMode,
          auto_proceed: config.autoProceed,
          human_checkpoint: config.humanCheckpoint,
          human_checkpoint_nodes: config.humanCheckpointNodes,
          checkpoint_timeout_seconds: config.checkpointTimeoutSeconds,
          max_revision_rounds: config.maxRevisionRounds,
          max_research_loop_cycles: config.maxResearchLoopCycles,
          code_review: config.codeReview,
          compact: config.compact,
          wandb: config.wandb,
          review_difficulty: config.reviewerDifficulty,
          gpu_target: config.gpu,
          ssh_server_id: config.sshServer,
          run_experiment: config.runExperiment,
          non_experiment_evidence_mode: config.nonExperimentEvidenceMode,
          illustration_mode: 'auto',
          gpu_info: config.gpuInfo,
          max_retries: config.maxRetries,
          experiment_timeout_seconds: config.experimentTimeoutMinutes * 60,
          sync_project_data: config.syncProjectData,
          auto_stop_on_anomaly: config.autoStopOnAnomaly,
          remote_gpu_type: config.remoteGpuType,
          max_remote_cost_usd: config.maxRemoteCostUsd,
          vast_max_hourly_usd: config.vastMaxHourlyUsd,
          auto_destroy_vast: config.autoDestroyVast,
          research_mode: config.researchMode,
          innovation_focus: config.innovationFocus,
          ref_paper: config.refPaper,
          base_repo: config.baseRepo,
          input_files: config.inputFiles,
          research_family: config.researchFamily,
          study_archetype: config.studyArchetype,
          target_venue: config.venue,
          venue_template_path: config.venueTemplatePath,
          target_pages: config.targetPages,
          target_page_tolerance: config.targetPageTolerance,
          literature_year_from: config.literatureYearFrom,
          literature_year_to: config.literatureYearTo,
          literature_max_papers: config.literatureMaxPapers,
          literature_sources: config.literatureSources.filter((source: string) => (
            (source !== 'gemini' || integrationStatus.gemini?.verified === true)
            && (source !== 'zotero' || integrationStatus.zotero?.verified === true)
            && (source !== 'obsidian' || integrationStatus.obsidian?.verified === true)
          )),
          literature_venues: config.literatureVenues,
          include_keywords: config.includeKeywords,
          exclude_keywords: config.excludeKeywords,
          seed_papers: config.seedPapers,
          evidence_policy: config.evidencePolicy,
          novelty_window_years: config.noveltyWindowYears,
          enable_patent_search: config.enablePatentSearch && integrationStatus.patent?.verified === true,
          patent_date_from: config.patentDateFrom,
          patent_date_to: config.patentDateTo,
          patent_max_results: config.patentMaxResults,
          enable_meta_optimization: config.enableMetaOptimization,
          enable_gemini: config.enableGemini && integrationStatus.gemini?.verified === true,
          enable_gpt_image: config.enableGptImage && integrationStatus.gpt_image?.verified === true,
          enable_zotero: config.enableZotero && integrationStatus.zotero?.verified === true,
          enable_obsidian: config.enableObsidian && integrationStatus.obsidian?.verified === true,
          enable_overleaf_sync: config.enableOverleafSync && selectedIds.includes('compile') && Boolean(config.overleafProjectId),
          overleaf_project_id: config.overleafProjectId,
        }),
      })
      pendingRunIdsRef.current = null
      if (res.ok) {
        const data = await res.json()
        const submittedNodeIds = new Set(selectedIds)
        setNodes((prev: WorkflowNode[]) => prev.map(node => ({
          ...node,
          selected: submittedNodeIds.has(node.id),
        })))
        addLog('System', `工作流已提交: ${data.run_id}`, 'info')
        setActiveRunId(data.run_id)
        connectWs()
      } else {
        const data = await res.json().catch(() => null)
        const issues = Array.isArray(data?.detail?.issues) ? data.detail.issues.join('；') : data?.detail
        addLog('System', `无法启动工作流: ${issues || res.statusText}`, 'error')
        setIsRunning(false)
        setActiveRunId(null)
        closeWorkflowWs()
      }
    } catch (err: any) {
      pendingRunIdsRef.current = null
      addLog('System', `Connection error: ${err.message}`, 'error')
      setIsRunning(false)
      setActiveRunId(null)
      closeWorkflowWs()
    }
  }

  const handleStop = async () => {
    workflowStopRequestedRef.current = true
    // 询问是否同时终止正在运行的实验
    const killExperiment = confirm('是否同时终止正在运行的实验进程？\n\n选择"确定"终止实验，选择"取消"仅停止工作流（实验继续在后台运行）')

    if (currentRunId) {
      manuallyStoppedRunIdsRef?.current.add(currentRunId)
      try {
      const response = await fetch(`${API_BASE}/api/workflow/runs/${currentRunId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kill_experiment: killExperiment,
          project_path: projectPath,
        }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = await response.json()
      if (payload.resume_state?.run_id) setResumableState(payload.resume_state)
      } catch (error) {
        workflowStopRequestedRef.current = false
        addLog('System', `停止尚未确认：${String(error)}。保留运行连接，请重试。`, 'error')
        return
      }
    }
    setIsRunning(false)
    setPausedRunIdSafe(null)
    setActiveRunId(null)
    closeWorkflowWs()
    addLog('System', `${killExperiment ? '已停止工作流和实验' : '已停止工作流（实验继续运行）'}；断点已保留，可手动恢复`, 'warn')
    setNodes((prev: WorkflowNode[]) => prev.map(n => n.status === 'running' ? { ...n, status: 'idle' } : n))
  }

  const handleResume = async (state: ResumableState | null = null, checkpointFeedbackOverride?: string) => {
    const runId = state?.run_id || pausedRunIdRef.current
    if (!runId || isResuming || !projectPath) return
    workflowStopRequestedRef.current = false
    manuallyStoppedRunIdsRef?.current.delete(runId)
    const resumeProjectPath = projectPath
    const incompleteIds = incompleteNodeIdsFromState(state, nodes)
    const persistedConfigPatch = applyResumeConfigPatch(state)
    const resumeConfig = { ...config, ...persistedConfigPatch }
    const selectedNodeIds = selectedNodeIdsFromRunState(state)
    if (state) {
      // Discovering an old resumable run must not overwrite the user's current
      // project draft. Apply its saved configuration only on explicit resume.
      setConfig(resumeConfig)
      setNodes((previous: WorkflowNode[]) => previous.map((node: WorkflowNode) => ({
        ...node,
        selected: selectedNodeIds.has(node.id),
      })))
    }
    const feedbackToSend = typeof checkpointFeedbackOverride === 'string' ? checkpointFeedbackOverride : checkpointFeedback
    setCheckpointActionError('')
    setIsResuming(true)
    setIsRunning(true)
    setActiveRunId(runId)
    addLog('System', feedbackToSend.trim() ? '提交人工意见并继续执行' : `恢复执行 ${incompleteIds.length || '剩余'} 个未完成节点`, 'info')
    try {
      const versionApproval = await evidenceVersionApproval(resumeProjectPath, runId)
      if (versionApproval === null) {
        setIsRunning(false)
        setActiveRunId(null)
        return
      }
      const res = await fetch(`${API_BASE}/api/workflow/runs/${encodeURIComponent(runId)}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_path: resumeProjectPath,
          evidence_version_approval: versionApproval,
          node_ids: incompleteIds.length ? incompleteIds : undefined,
          research_direction: resumeConfig.researchDirection || state?.config?.direction || '',
          effort: state?.config?.effort || resumeConfig.effort,
          assurance: state?.config?.assurance || resumeConfig.assurance,
          delivery_goal: resumeConfig.deliveryGoal,
          checkpoint_feedback: feedbackToSend,
          max_revision_rounds: resumeConfig.maxRevisionRounds,
          max_research_loop_cycles: resumeConfig.maxResearchLoopCycles,
        }),
      })
      const data = await res.json().catch(() => ({}))
      const detail = typeof data.detail === 'string'
        ? data.detail
        : data.detail?.issues
          ? data.detail.issues.join('；')
          : ''
      if (!res.ok || data.error) throw new Error(data.error || detail || res.statusText)
      const resumedRunId = data.run_id || runId
      if (data.status === 'completed' || data.already_completed === true) {
        const statusByNode = data.nodes_status && typeof data.nodes_status === 'object'
          ? data.nodes_status as Record<string, string>
          : {}
        setNodes((prev: WorkflowNode[]) => prev.map(node => ({
          ...node,
          status: toNodeStatus(statusByNode[node.id]),
        })))
        setWorkflowCompletion(toWorkflowCompletion(data.completion))
        setCheckpointNode(null)
        setCheckpointFeedback('')
        setPausedRunIdSafe(null)
        setResumableState(null)
        setActiveRunId(null)
        setIsRunning(false)
        addLog('System', `工作流已在平台恢复期间完成: ${resumedRunId}`, 'info')
        return
      }
      setPausedRunIdSafe(null)
      setResumableState(null)
      setActiveRunId(resumedRunId)
      connectWs()
      addLog('System', data.resumed_from_state ? `工作流已从断点恢复: ${resumedRunId}` : '已继续暂停的工作流', 'info')
    } catch (err: any) {
      setIsRunning(false)
      setActiveRunId(null)
      const rawMessage = String(err.message || err || '')
      const artifactUnchanged = rawMessage.includes('科研产物自上次质量检查后没有变化')
      const researcherDecision = checkpointNode?.requiresHumanDecision === true
      setCheckpointActionError(
        artifactUnchanged
          ? researcherDecision
            ? '该节点需要研究者作出科研取舍。请在检查点提交明确意见；系统会据此定向修订，而不是要求你直接编辑运行文件。'
            : '节点仍在后台校验或平台恢复中，无需为了触发恢复而修改文件。请稍后重试；若持续出现，平台会保留原始产物和诊断。'
          : rawMessage || '恢复执行失败，请保留当前弹窗并稍后重试。',
      )
      addLog('System', `恢复失败: ${err.message || err}`, 'error')
    } finally {
      setIsResuming(false)
    }
  }

  useEffect(() => {
    checkpointFeedbackRef.current = checkpointFeedback
  }, [checkpointFeedback])

  const handleExtendCheckpoint = async () => {
    const runId = pausedRunIdRef.current
    if (!runId || isExtendingCheckpoint) return
    setIsExtendingCheckpoint(true)
    try {
      const res = await fetch(`${API_BASE}/api/workflow/runs/${encodeURIComponent(runId)}/checkpoint/extend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ seconds: 300 }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.error) throw new Error(data.detail || data.error || res.statusText)
      const remainingSeconds = Number(data.remaining_seconds || checkpointSecondsLeft + 300)
      setCheckpointNode((prev: Record<string, any> | null) => prev ? { ...prev, timeoutSeconds: remainingSeconds } : prev)
      startCheckpointCountdown(remainingSeconds)
    } catch (err: any) {
      addLog('System', `延长检查点失败: ${err.message || err}`, 'error')
    } finally {
      setIsExtendingCheckpoint(false)
    }
  }

  const handleAcknowledgeRevisionCheckpoint = async () => {
    const runId = pausedRunIdRef.current
    if (!runId || !checkpointNode?.persisted || isAcknowledgingCheckpoint) return
    setIsAcknowledgingCheckpoint(true)
    try {
      const res = await fetch(
        `${API_BASE}/api/workflow/runs/${encodeURIComponent(runId)}/revision-checkpoint/acknowledge`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_path: projectPath || '.',
            node_id: checkpointNode.id,
          }),
        },
      )
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || res.statusText)
      setPausedRunIdSafe(null, true)
      addLog('System', '已收起科研质量问题；节点仍保持可恢复，质量门没有被跳过', 'info')
    } catch (err: any) {
      addLog('System', `收起检查点失败: ${err.message || err}`, 'error')
    } finally {
      setIsAcknowledgingCheckpoint(false)
    }
  }

  const experimentEndpoint = () => {
    if (!experimentMonitor.experimentId || !experimentMonitor.jobId) return ''
    return `${API_BASE}/api/experiments/${encodeURIComponent(experimentMonitor.experimentId)}/jobs/${encodeURIComponent(experimentMonitor.jobId)}`
  }

  const handleExperimentStop = async () => {
    const endpoint = experimentEndpoint()
    if (!endpoint) return
    try {
      const response = await fetch(`${endpoint}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Stopped from the workflow experiment monitor' }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || response.statusText)
      setExperimentMonitor((prev: ExperimentMonitorState) => ({ ...prev, active: true, phase: 'stopping' }))
      addLog('Experiment', '安全停止请求已提交；正在终止进程组并回收证据', 'warn')
    } catch (error: any) {
      addLog('Experiment', `停止失败：${error.message || error}`, 'error')
    }
  }

  const openExperimentArtifact = (path: string) => {
    if (!path) return
    const name = path.split(/[/\\]/).pop() || 'artifact'
    const extension = name.split('.').pop()?.toLowerCase()
    useWorkspaceStore.getState().openFile({
      path,
      name,
      language: extension === 'json' ? 'json' : extension === 'md' ? 'markdown' : 'plaintext',
      content: '',
    })
  }

  const handleCreateAdjustment = async () => {
    const endpoint = experimentEndpoint()
    if (!endpoint || adjustmentBusy) return
    setAdjustmentBusy(true)
    try {
      const batchSize = adjustmentDraft.batchSize.trim()
        ? Number(adjustmentDraft.batchSize)
        : undefined
      const response = await fetch(`${endpoint}/adjustments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          summary: adjustmentDraft.summary.trim(),
          rationale: adjustmentDraft.rationale.trim(),
          batch_size: batchSize,
          command: adjustmentDraft.command.trim(),
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || response.statusText)
      setExperimentMonitor((prev: ExperimentMonitorState) => ({
        ...prev,
        phase: 'awaiting_approval',
        proposalId: String(payload.proposal_id || ''),
        proposalStatus: 'pending',
        proposalSummary: String(payload.summary || adjustmentDraft.summary),
        proposalRationale: String(payload.rationale || adjustmentDraft.rationale),
        proposalChanges: payload.changes && typeof payload.changes === 'object' ? payload.changes : {},
        proposalTrigger: String(payload.decision_brief?.trigger || 'researcher_proposed_adjustment'),
        proposalImpact: String(payload.decision_brief?.research_impact || ''),
        proposalQuestion: String(payload.decision_brief?.approval_question || ''),
        proposalActions: Array.isArray(payload.decision_brief?.proposed_action)
          ? payload.decision_brief.proposed_action.map((item: unknown) => String(item))
          : [],
        proposalRisks: Array.isArray(payload.decision_brief?.risks)
          ? payload.decision_brief.risks.map((item: unknown) => String(item))
          : [],
        proposalPath: String(payload.proposal_path || ''),
      }))
      setAdjustmentDialogOpen(false)
      setApprovalDialogOpen(true)
      addLog('Experiment', `调整提案 ${String(payload.proposal_id || '')} 已保存，尚未修改运行配置`, 'warn')
    } catch (error: any) {
      addLog('Experiment', `创建调整提案失败：${error.message || error}`, 'error')
    } finally {
      setAdjustmentBusy(false)
    }
  }

  const handleResolveAdjustment = async (approved: boolean) => {
    const endpoint = experimentEndpoint()
    if (!endpoint || !experimentMonitor.proposalId || adjustmentBusy) return
    setAdjustmentBusy(true)
    try {
      const response = await fetch(`${endpoint}/adjustments/${encodeURIComponent(experimentMonitor.proposalId)}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approved,
          note: approved ? 'Approved from workflow experiment monitor' : 'Rejected from workflow experiment monitor',
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || response.statusText)
      setExperimentMonitor((prev: ExperimentMonitorState) => ({
        ...prev,
        proposalStatus: approved ? 'approved' : 'rejected',
        phase: approved ? 'ready_to_retry' : 'failed',
      }))
      setApprovalDialogOpen(false)
      addLog('Experiment', approved ? '调整已批准，但尚未启动新 attempt' : '调整已拒绝，实验保持停止', approved ? 'info' : 'warn')
    } catch (error: any) {
      addLog('Experiment', `审批失败：${error.message || error}`, 'error')
    } finally {
      setAdjustmentBusy(false)
    }
  }

  const handleRetryExperiment = async () => {
    const endpoint = experimentEndpoint()
    if (!endpoint || !experimentMonitor.proposalId || adjustmentBusy) return
    setAdjustmentBusy(true)
    try {
      const response = await fetch(`${endpoint}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: experimentMonitor.proposalId }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail || response.statusText)
      setExperimentMonitor((prev: ExperimentMonitorState) => ({
        ...prev,
        active: true,
        phase: 'queued',
        proposalStatus: '',
        anomaly: '',
      }))
      addLog('Experiment', `attempt ${String(payload.next_attempt || '?')} 已排队，旧日志和结果不会覆盖`, 'tool')
    } catch (error: any) {
      addLog('Experiment', `重试失败：${error.message || error}`, 'error')
    } finally {
      setAdjustmentBusy(false)
    }
  }

  const handleReset = () => {
    workflowStopRequestedRef.current = false
    setWorkflowUiHydratedProject(projectPath)
    setConfig(createDefaultWorkflowConfig())
    setIsRunning(false)
    setIsResuming(false)
    setActiveRunId(null)
    setPausedRunIdSafe(null)
    setResumableState(null)
    setExperimentMonitor(EMPTY_EXPERIMENT_MONITOR)
    setAdjustmentDialogOpen(false)
    setApprovalDialogOpen(false)
    setAdjustmentDraft({ summary: '', rationale: '', batchSize: '', command: '' })
    setFocusedNode(null)
    setNodeSchema(null)
    setNodeParams({})
    nodeParamsFocusedNodeRef.current = null
    setShowProjectForm(false)
    setPendingRunIds(null)
    pendingRunIdsRef.current = null
    closeWorkflowWs()
    setNodes(DEFAULT_NODES)
    setLogs([])
    try {
      if (projectPath) localStorage.removeItem(workflowUiStorageKey(projectPath))
    } catch {
      // Reset must still work when browser storage is unavailable.
    }
  }
  return { handleRunSingleNode, addLog, cleanAgentOutput, flushAgentOutput, queueAgentOutput, handleRun, handleStop, handleResume, handleExtendCheckpoint, handleAcknowledgeRevisionCheckpoint, experimentEndpoint, handleExperimentStop, openExperimentArtifact, handleCreateAdjustment, handleResolveAdjustment, handleRetryExperiment, handleReset }
}
