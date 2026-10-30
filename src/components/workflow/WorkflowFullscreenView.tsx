import { Zap, CheckCircle, XCircle, Clock, Loader2, FileText, Folder, AlertTriangle, FileSearch, Send, Ban, CircleCheck, CircleAlert, Shield } from 'lucide-react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { writePersistedWorkflowUiState } from './workflowPersistence'
import { DELIVERY_ATTESTATION_LABELS, formatGateNumber } from './workflowViewModels'
import { CHECKPOINT_GUIDANCE } from './workflowRevisionUi'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import type { WorkflowController } from './useWorkflowController'
import { WorkflowWorkspace } from './WorkflowWorkspace'

export function WorkflowFullscreenView({ model }: { model: WorkflowController }) {
  const workflowFullscreen = useWorkspaceStore(state => state.workflowFullscreen)
  const {
    projectPath,
    setProjectPath,
    nodes,
    isRunning,
    pausedRunId,
    checkpointNode,
    checkpointFeedback,
    setCheckpointFeedback,
    checkpointActionError,
    checkpointSecondsLeft,
    isExtendingCheckpoint,
    checkpointFeedbackRef,
    isAcknowledgingCheckpoint,
    resumableState,
    setResumableState,
    workflowCompletion,
    setWorkflowCompletion,
    isResuming,
    experimentMonitor,
    adjustmentDialogOpen,
    setAdjustmentDialogOpen,
    approvalDialogOpen,
    setApprovalDialogOpen,
    adjustmentBusy,
    adjustmentDraft,
    setAdjustmentDraft,
    focusedNode,
    nodeParams,
    showProjectForm,
    setShowProjectForm,
    pendingRunIds,
    setPendingRunIds,
    pendingRunIdsRef,
    projectCreationError,
    setProjectCreationError,
    setPausedRunIdSafe,
    config,
    handleRun,
    handleResume,
    handleExtendCheckpoint,
    handleAcknowledgeRevisionCheckpoint,
    openExperimentArtifact,
    handleCreateAdjustment,
    handleResolveAdjustment,
  } = model
  // WorkflowFullscreen stays mounted so running/recovery state survives when
  // returning to the IDE. Radix dialogs, however, render into document.body;
  // explicitly close their portals while this mounted tree is hidden or its
  // project has been closed, otherwise their overlay can intercept the IDE.
  const workflowDialogsVisible = Boolean(workflowFullscreen && projectPath)
  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col">
      {/* 创建项目表单弹窗 */}
      {showProjectForm && (
        <div className="fixed inset-0 z-[100] bg-black/50 flex items-center justify-center">
          <div className="bg-card border border-border rounded-lg p-6 w-96 space-y-4">
            <h3 className="text-sm font-semibold text-foreground">请先创建研究项目</h3>
            <p className="text-xs text-muted-foreground">运行工作流需要一个项目目录来存放生成的文件。</p>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">项目路径</label>
              <div className="flex gap-2">
                <input id="wf-proj-path" placeholder="选择路径" className="flex-1 h-8 px-2 rounded border border-border bg-background text-sm text-foreground" />
                <Button size="sm" variant="outline" onClick={async () => {
                  const p = await window.merakIDE?.fs.openFolder()
                  if (p) (document.getElementById('wf-proj-path') as HTMLInputElement).value = p
                }}>选择</Button>
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">项目名称</label>
              <input id="wf-proj-name" placeholder="项目名称（必填）" className="w-full h-8 px-2 rounded border border-border bg-background text-sm text-foreground" />
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={async () => {
                const pathEl = document.getElementById('wf-proj-path') as HTMLInputElement
                const nameEl = document.getElementById('wf-proj-name') as HTMLInputElement
                const basePath = pathEl.value
                const name = nameEl.value.trim()
                if (!basePath || !name) return
                const sep = basePath.includes('\\') ? '\\' : '/'
                const fullPath = basePath + sep + name
                setProjectCreationError('')
                const response = await fetch(`${API_BASE}/api/projects/scaffold`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ path: fullPath, name, venue: config.venue, mode: 'create' }),
                })
                const payload = await response.json().catch(() => ({}))
                if (!response.ok) {
                  setProjectCreationError(payload.detail || response.statusText || '创建项目失败')
                  return
                }
                // The workflow may have been configured before a project was
                // created. Move that draft into the new project namespace
                // before setProjectPath triggers the project-switch reset.
                writePersistedWorkflowUiState(fullPath, {
                  version: 1,
                  config,
                  selectedNodeIds: nodes.filter(node => node.selected).map(node => node.id),
                  nodeParams,
                  focusedNode,
                })
                useWorkspaceStore.getState().setProjectPath(fullPath)
                setShowProjectForm(false)
                // 直接传 fullPath 跳过检查，不再弹第二次
                if (pendingRunIds) {
                  handleRun(pendingRunIds, fullPath)
                  setPendingRunIds(null)
                }
              }}>创建并运行</Button>
              <Button size="sm" variant="ghost" onClick={() => {
                setShowProjectForm(false)
                setPendingRunIds(null)
                pendingRunIdsRef.current = null
                setProjectCreationError('')
              }}>取消</Button>
            </div>
            {projectCreationError && (
              <p className="text-xs leading-5 text-destructive">{projectCreationError}</p>
            )}
          </div>
        </div>
      )}

      {!projectPath && !showProjectForm && (
        <div className="titlebar-no-drag relative z-[60] flex shrink-0 items-center justify-between gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2">
          <div className="min-w-0">
            <p className="text-xs font-medium text-amber-200">当前未打开研究项目</p>
            <p className="truncate text-[10px] text-muted-foreground">
              通用工作流配置仍可编辑；选择项目文件、执行节点和运行流水线需要先打开或创建项目。
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="shrink-0 text-xs"
            onClick={async () => {
              const path = await window.merakIDE?.fs.openFolder()
              if (path) setProjectPath(path)
            }}
          >
            <Folder size={13} /> 打开项目
          </Button>
        </div>
      )}

      {workflowCompletion && (
        <div className={cn(
          'titlebar-no-drag relative z-[65] flex shrink-0 items-start justify-between gap-3 border-b px-4 py-2',
          workflowCompletion.submission_ready
            ? 'border-emerald-500/30 bg-emerald-500/10'
            : 'border-amber-500/30 bg-amber-500/10',
        )}>
          <div className="min-w-0">
            <p className={cn(
              'flex items-center gap-1.5 text-xs font-medium',
              workflowCompletion.submission_ready ? 'text-emerald-300' : 'text-amber-300',
            )}>
              {workflowCompletion.submission_ready
                ? <CircleCheck className="h-3.5 w-3.5 shrink-0" />
                : <CircleAlert className="h-3.5 w-3.5 shrink-0" />}
              {workflowCompletion.submission_ready
                ? workflowCompletion.submission_advisories.length > 0
                  ? '投稿候选稿已就绪，有作者复核提醒'
                  : '投稿候选稿已就绪'
                : '流程已完成，尚不可投稿'}
            </p>
            <p className="mt-0.5 line-clamp-2 text-[10px] text-muted-foreground">
              {workflowCompletion.submission_ready
                ? workflowCompletion.submission_advisories.slice(0, 2).join('；')
                  || `证据模式：${workflowCompletion.evidence_mode}；最终 PDF：${workflowCompletion.paper_pdf || 'paper/main.pdf'}`
                : workflowCompletion.submission_blockers.slice(0, 3).join('；') || workflowCompletion.label}
            </p>
            {Object.keys(workflowCompletion.attestations).length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {Object.entries(workflowCompletion.attestations)
                  .filter(([, attestation]) => attestation.applicable)
                  .map(([key, attestation]) => (
                  <Badge
                    key={key}
                    variant="outline"
                    className={cn(
                      'h-5 gap-1 px-1.5 text-[9px] font-normal',
                      attestation.valid
                        ? 'border-emerald-500/30 text-emerald-300'
                        : 'border-amber-500/30 text-amber-300',
                    )}
                    title={attestation.valid
                      ? `${DELIVERY_ATTESTATION_LABELS[key] || key}证明有效`
                      : `${DELIVERY_ATTESTATION_LABELS[key] || key}有 ${attestation.issue_count} 项问题`}
                  >
                    {attestation.valid
                      ? <CircleCheck className="h-2.5 w-2.5" />
                      : <CircleAlert className="h-2.5 w-2.5" />}
                    {DELIVERY_ATTESTATION_LABELS[key] || key}
                  </Badge>
                  ))}
              </div>
            )}
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 shrink-0"
            title="关闭交付状态"
            onClick={() => setWorkflowCompletion(null)}
          >
            <XCircle className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {/* Session Recovery Banner */}
      {resumableState && (!isRunning || isResuming) && (
        <div className="titlebar-no-drag relative z-[70] px-4 py-2 bg-yellow-500/10 border-b border-yellow-500/30 flex items-center justify-between">
          <span className="text-xs text-yellow-300 flex items-center gap-1.5">
            <Zap size={13} className="shrink-0" />
            {resumableState.auto_rebuild_required
              ? `投稿证明已变化，后台将从节点 "${resumableState.current_node}" 自动重建。`
              : checkpointNode?.persisted && checkpointNode.id === resumableState.current_node
              ? `节点 "${resumableState.current_node}" 等待科研质量处理，问题已保留。`
              : `上次运行在节点 "${resumableState.current_node}" 处中断。`}
          </span>
          <div className="flex gap-2">
            <Button
              variant="default"
              size="sm"
              onClick={() => {
                if (checkpointNode?.persisted && checkpointNode.id === resumableState.current_node) {
                  setPausedRunIdSafe(resumableState.run_id)
                  return
                }
                handleResume(resumableState)
              }}
              disabled={isResuming}
              className="titlebar-no-drag relative z-[71] bg-yellow-600 text-white text-2xs hover:bg-yellow-700 disabled:pointer-events-auto disabled:cursor-wait"
            >
              {isResuming ? <Loader2 size={12} className="animate-spin" /> : null}
              {isResuming
                ? '恢复中...'
                : resumableState.auto_rebuild_required
                  ? '立即重建'
                : checkpointNode?.persisted && checkpointNode.id === resumableState.current_node
                  ? '查看并处理'
                  : '恢复执行'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setResumableState(null)}
              disabled={isResuming}
              className="titlebar-no-drag relative z-[71] text-muted-foreground text-2xs disabled:pointer-events-auto disabled:cursor-wait"
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}

      <Dialog open={Boolean(workflowDialogsVisible && pausedRunId && checkpointNode && !isResuming)}>
        <DialogContent
          hideClose
          className="titlebar-no-drag max-h-[calc(100dvh-1rem)] max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-h-[calc(100dvh-2rem)]"
          onEscapeKeyDown={event => event.preventDefault()}
          onPointerDownOutside={event => event.preventDefault()}
        >
          <DialogHeader className="min-w-0 border-b border-border bg-muted/30 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                {checkpointNode?.kind === 'research_revision' ? '研究者决策' : '节点前人工检查点'}
              </DialogTitle>
              <Badge variant="outline" className="h-6 gap-1.5 font-mono text-[11px] font-normal">
                <Clock className="h-3.5 w-3.5" />
                {checkpointNode?.persisted
                  ? '等待恢复'
                  : checkpointSecondsLeft > 0
                  ? `${String(Math.floor(checkpointSecondsLeft / 60)).padStart(2, '0')}:${String(checkpointSecondsLeft % 60).padStart(2, '0')}`
                  : '正在自动继续'}
              </Badge>
            </div>
            <DialogDescription>
              {checkpointNode?.kind === 'research_revision'
                ? checkpointNode.persisted
                  ? '当前节点已达到修订上限。下面只展示需要你判断的科研问题和可执行选择，原始校验信息已收纳到技术详情。'
                  : '当前产物尚未达到独立科研质量门。反馈会约束下一次修订。'
                : '即将执行“' + (checkpointNode?.name || '下一节点') + '”。反馈会作为当前节点的强约束；不操作时工作流会按原计划自动继续。'}
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
            {checkpointNode?.kind === 'research_revision' && checkpointNode.decisionBrief && (
              <>
                <section className="space-y-2 rounded border border-amber-500/30 bg-amber-500/5 p-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="outline">科研验收未完成</Badge>
                    <Badge variant="outline">已修订 {checkpointNode.revisionRound} 轮</Badge>
                    {checkpointNode.stopReason && (
                      <Badge variant="outline">{checkpointNode.stopReason}</Badge>
                    )}
                    {Object.entries(checkpointNode.componentStatuses).map(([key, status]) => (
                      <Badge
                        key={key}
                        variant="outline"
                        className={cn(
                          status.passed
                            ? 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400'
                            : 'border-destructive/40 text-destructive',
                        )}
                      >
                        {status.label}：{status.passed ? '已通过' : '未通过'}
                        {status.score != null && status.threshold != null
                          ? `（${formatGateNumber(status.score)} ${status.passed ? '≥' : '<'} ${formatGateNumber(status.threshold)}）`
                          : ''}
                      </Badge>
                    ))}
                    {Object.keys(checkpointNode.componentStatuses).length === 0
                      && checkpointNode.score != null && checkpointNode.threshold != null && (
                      <Badge variant="outline">
                        内容质量：{checkpointNode.score >= checkpointNode.threshold ? '已通过' : '未通过'}
                        （{formatGateNumber(checkpointNode.score)} {checkpointNode.score >= checkpointNode.threshold ? '≥' : '<'} {formatGateNumber(checkpointNode.threshold)}）
                      </Badge>
                    )}
                  </div>
                  <h3 className="text-sm font-semibold text-foreground">
                    {checkpointNode.decisionBrief.headline}
                  </h3>
                  <p className="text-xs leading-5 text-muted-foreground">
                    {checkpointNode.decisionBrief.whatHappened}
                  </p>
                </section>

                <div className="grid gap-3 sm:grid-cols-2">
                  <section className="space-y-2 rounded border border-border/70 bg-background/50 p-3">
                    <h4 className="flex items-center gap-2 text-xs font-medium text-foreground">
                      <Shield className="h-3.5 w-3.5 text-amber-500" />
                      为什么不能直接继续
                    </h4>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {checkpointNode.decisionBrief.researchImpact}
                    </p>
                  </section>
                  <section className="space-y-2 rounded border border-border/70 bg-background/50 p-3">
                    <h4 className="flex items-center gap-2 text-xs font-medium text-foreground">
                      <CircleCheck className="h-3.5 w-3.5 text-emerald-500" />
                      系统已经做过
                    </h4>
                    <ul className="space-y-1 text-[11px] leading-4 text-muted-foreground">
                      {checkpointNode.decisionBrief.systemActions.map((item, index) => (
                        <li key={index} className="flex gap-2">
                          <span className="shrink-0 text-emerald-500">✓</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                </div>

                <section className="space-y-2">
                  <h4 className="text-xs font-medium text-foreground">需要处理的核心问题</h4>
                  <ol className="space-y-2">
                    {checkpointNode.decisionBrief.plainIssues.map((issue, index) => (
                      <li key={index} className="flex gap-3 rounded border border-border/60 bg-muted/20 p-2.5">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-[11px] font-medium text-amber-500">
                          {index + 1}
                        </span>
                        <span className="text-xs leading-5 text-foreground">{issue}</span>
                      </li>
                    ))}
                  </ol>
                </section>

                <section className="space-y-2 rounded border border-primary/25 bg-primary/5 p-3">
                  <h4 className="text-xs font-medium text-foreground">建议下一步</h4>
                  <ol className="space-y-1.5 text-xs leading-5 text-muted-foreground">
                    {checkpointNode.decisionBrief.recommendedActions.map((action, index) => (
                      <li key={index} className="flex gap-2">
                        <span className="shrink-0 font-medium text-foreground">{index + 1}.</span>
                        <span>{action}</span>
                      </li>
                    ))}
                  </ol>
                  <p className="border-t border-border/60 pt-2 text-xs font-medium leading-5 text-foreground">
                    {checkpointNode.decisionBrief.decisionQuestion}
                  </p>
                </section>

                <div className="flex gap-2 rounded border border-emerald-500/25 bg-emerald-500/5 p-2.5">
                  <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                  <p className="text-[11px] leading-4 text-muted-foreground">
                    {checkpointNode.decisionBrief.protectedState}
                  </p>
                </div>

                <details className="rounded border border-border/60 bg-muted/10">
                  <summary className="cursor-pointer select-none px-3 py-2 text-[11px] font-medium text-muted-foreground">
                    技术详情（供开发者排查）
                  </summary>
                  <div className="space-y-2 border-t border-border/60 px-3 py-2">
                    {checkpointNode.decisionBrief.technicalDetails.length > 0 && (
                      <ul className="list-disc space-y-1 pl-4 font-mono text-[10px] leading-4 text-muted-foreground">
                        {checkpointNode.decisionBrief.technicalDetails.map((issue, index) => (
                          <li key={index} className="break-words">{issue}</li>
                        ))}
                      </ul>
                    )}
                    {checkpointNode.reportPath && (
                      <p className="break-all font-mono text-[10px] text-muted-foreground">
                        报告：{checkpointNode.reportPath}
                      </p>
                    )}
                  </div>
                </details>
              </>
            )}
            {checkpointNode?.kind === 'research_revision' && !checkpointNode.decisionBrief && (
              <section className="space-y-2 rounded border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant="outline">确定性质量门触发</Badge>
                  <Badge variant="outline">第 {checkpointNode.revisionRound} 轮</Badge>
                  <Badge variant="outline">周期 {checkpointNode.revisionCycle}</Badge>
                  {Object.entries(checkpointNode.componentStatuses).map(([key, status]) => (
                    <Badge key={key} variant="outline">
                      {status.label}：{status.passed ? '已通过' : '未通过'}
                      {status.score != null && status.threshold != null
                        ? `（${formatGateNumber(status.score)} ${status.passed ? '≥' : '<'} ${formatGateNumber(status.threshold)}）`
                        : ''}
                    </Badge>
                  ))}
                  {Object.keys(checkpointNode.componentStatuses).length === 0
                    && checkpointNode.score != null && checkpointNode.threshold != null && (
                    <Badge variant="outline">
                      内容质量：{checkpointNode.score >= checkpointNode.threshold ? '已通过' : '未通过'}
                      （{formatGateNumber(checkpointNode.score)} {checkpointNode.score >= checkpointNode.threshold ? '≥' : '<'} {formatGateNumber(checkpointNode.threshold)}）
                    </Badge>
                  )}
                </div>
                {checkpointNode.summary && (
                  <p className="text-xs leading-5 text-foreground">{checkpointNode.summary}</p>
                )}
                {checkpointNode.issues.length > 0 && (
                  <ul className="max-h-32 list-disc space-y-1 overflow-y-auto pl-4 text-[11px] leading-4 text-muted-foreground">
                    {checkpointNode.issues.slice(0, 8).map((issue, index) => (
                      <li key={index}>{issue}</li>
                    ))}
                  </ul>
                )}
                {checkpointNode.reportPath && (
                  <p className="break-all font-mono text-[10px] text-muted-foreground">
                    {checkpointNode.reportPath}
                  </p>
                )}
              </section>
            )}
            {checkpointNode?.kind !== 'research_revision' && CHECKPOINT_GUIDANCE[checkpointNode?.id || ''] && (
              <section className="space-y-1.5 rounded border border-primary/25 bg-primary/5 p-3">
                <h3 className="text-xs font-medium text-foreground">
                  {CHECKPOINT_GUIDANCE[checkpointNode?.id || ''].title}
                </h3>
                <p className="text-xs leading-5 text-muted-foreground">
                  {CHECKPOINT_GUIDANCE[checkpointNode?.id || ''].detail}
                </p>
              </section>
            )}
            {checkpointActionError && (
              <div className="flex gap-2 rounded border border-destructive/35 bg-destructive/5 p-3" role="alert">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <div className="space-y-1">
                  <p className="text-xs font-medium text-foreground">本次操作未执行</p>
                  <p className="text-xs leading-5 text-muted-foreground">{checkpointActionError}</p>
                </div>
              </div>
            )}
            <Label htmlFor="checkpoint-feedback" className="text-xs">
              {checkpointNode?.kind === 'research_revision' ? '给智能体的明确修订意见' : '调整意见'}
            </Label>
            <Textarea
              id="checkpoint-feedback"
              autoFocus={checkpointNode?.kind !== 'research_revision'}
              value={checkpointFeedback}
              onChange={event => {
                checkpointFeedbackRef.current = event.target.value
                setCheckpointFeedback(event.target.value)
              }}
              placeholder={checkpointNode?.kind === 'research_revision'
                ? '例如：实际实现位于 experiments/src/variants.py，契约应引用 VARIANT_REGISTRY；保留核心假设，不要通过删除验收项绕过问题。'
                : '例如：保留核心科研假设；优先验证 Idea 2；不要修改 Method 章节的整体叙事。'}
              className="min-h-[110px] max-h-[32dvh] resize-y bg-background text-sm leading-6"
            />
            <p className="text-[11px] leading-4 text-muted-foreground">
              {checkpointNode?.persisted
                ? '该问题已持久化且只主动提示一次。收起不会放行后续节点；修改产物后可重新验收，提交意见会授权一次人工引导修订。'
                : '尚未提交的文字不会在倒计时结束时自动发送。需要更多时间可延长 5 分钟。'}
            </p>
          </div>
          <DialogFooter className="shrink-0 flex-wrap border-t border-border bg-muted/20 px-5 py-3">
            {!checkpointNode?.persisted && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleExtendCheckpoint}
                disabled={isExtendingCheckpoint || checkpointSecondsLeft <= 0}
              >
                {isExtendingCheckpoint ? <Loader2 className="animate-spin" /> : <Clock />}
                延长 5 分钟
              </Button>
            )}
            <div className="flex-1" />
            {checkpointNode?.persisted ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleAcknowledgeRevisionCheckpoint}
                  disabled={isAcknowledgingCheckpoint}
                >
                  {isAcknowledgingCheckpoint && <Loader2 className="animate-spin" />}
                  稍后处理
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleResume(resumableState, '')}
                  disabled={isResuming}
                >
                  产物已修改，重新验收
                </Button>
              </>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleResume(null, '')}
              >
                直接继续
              </Button>
            )}
            <Button
              size="sm"
              onClick={() => handleResume(
                checkpointNode?.persisted ? resumableState : null,
                checkpointFeedback,
              )}
              disabled={!checkpointFeedback.trim()}
            >
              提交意见并继续
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={workflowDialogsVisible && adjustmentDialogOpen}
        onOpenChange={setAdjustmentDialogOpen}
      >
        <DialogContent className="titlebar-no-drag max-h-[calc(100dvh-1rem)] max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-h-[calc(100dvh-2rem)]">
          <DialogHeader className="border-b border-border bg-muted/30 px-5 py-4">
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              实验调整提案
            </DialogTitle>
            <DialogDescription>
              提案只记录建议，不会立即修改运行配置。批准后仍需单独创建新 attempt，失败 attempt 保持只读。
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="adjustment-summary">调整摘要</Label>
              <Input
                id="adjustment-summary"
                value={adjustmentDraft.summary}
                onChange={event => setAdjustmentDraft(prev => ({ ...prev, summary: event.target.value }))}
                placeholder="例如：修复空 mask 后重新运行，保持其余科学配置不变"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="adjustment-rationale">证据与理由</Label>
              <Textarea
                id="adjustment-rationale"
                value={adjustmentDraft.rationale}
                onChange={event => setAdjustmentDraft(prev => ({ ...prev, rationale: event.target.value }))}
                placeholder="引用 diagnosis 中的异常、已检查的根因，以及为什么该调整不会偏离研究假设。"
                className="min-h-[120px] resize-y"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="adjustment-batch">新 batch size（可选）</Label>
                <Input
                  id="adjustment-batch"
                  type="number"
                  min={1}
                  value={adjustmentDraft.batchSize}
                  onChange={event => setAdjustmentDraft(prev => ({ ...prev, batchSize: event.target.value }))}
                  placeholder="仅在命令模板包含 {batch_size} 时填写"
                />
              </div>
              <div className="space-y-1.5">
                <Label>源码变更</Label>
                <p className="min-h-9 rounded-md border border-border bg-muted/30 px-3 py-2 text-[11px] leading-4 text-muted-foreground">
                  源码应先在 Chat 中以 diff 审批并落盘，再在此记录调整依据。
                </p>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="adjustment-command">替换运行命令（可选）</Label>
              <Textarea
                id="adjustment-command"
                value={adjustmentDraft.command}
                onChange={event => setAdjustmentDraft(prev => ({ ...prev, command: event.target.value }))}
                placeholder="仅在确实需要改变运行参数时填写完整命令"
                className="min-h-[84px] resize-y font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter className="shrink-0 flex-wrap border-t border-border bg-muted/20 px-5 py-3">
            <Button variant="ghost" size="sm" onClick={() => setAdjustmentDialogOpen(false)} disabled={adjustmentBusy}>
              取消
            </Button>
            <Button
              size="sm"
              onClick={handleCreateAdjustment}
              disabled={adjustmentBusy || !adjustmentDraft.summary.trim() || !adjustmentDraft.rationale.trim()}
            >
              {adjustmentBusy ? <Loader2 className="animate-spin" /> : <Send />}
              保存待审批提案
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={workflowDialogsVisible && approvalDialogOpen && experimentMonitor.proposalStatus === 'pending'}
        onOpenChange={setApprovalDialogOpen}
      >
        <DialogContent className="titlebar-no-drag max-h-[calc(100dvh-1rem)] max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-h-[calc(100dvh-2rem)]">
          <DialogHeader className="border-b border-border bg-muted/30 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <DialogTitle className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-amber-500" />
                实验调整审批
              </DialogTitle>
              <Badge variant="outline">
                {experimentMonitor.proposalTrigger === 'runtime_health_monitor' ? '运行监控触发' : '研究者提出'}
              </Badge>
            </div>
            <DialogDescription>
              这里审批的是“是否用明确变更创建一个新的不可变实验 attempt”，不是审批原始日志。
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 py-4 text-sm">
            <section className="space-y-1.5">
              <Label>发现了什么问题</Label>
              <p className="leading-6 text-foreground">{experimentMonitor.proposalSummary || '实验运行需要调整。'}</p>
            </section>
            <section className="space-y-1.5">
              <Label>判断依据</Label>
              <p className="leading-6 text-muted-foreground">
                {experimentMonitor.proposalRationale || '请查看诊断产物确认根因。'}
              </p>
            </section>
            <section className="space-y-2 border-y border-border py-3">
              <Label>批准后会发生什么</Label>
              <ul className="space-y-1.5 text-sm text-foreground">
                {(experimentMonitor.proposalActions.length
                  ? experimentMonitor.proposalActions
                  : ['保存该调整，并允许用户显式创建一个新 attempt；不会覆盖失败运行。']
                ).map((action, index) => (
                  <li key={index} className="flex gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                    <span className="leading-5">{action}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="space-y-1.5">
              <Label>对科研 Idea 的影响</Label>
              <p className="leading-6 text-muted-foreground">
                {experimentMonitor.proposalImpact || '需要确认变更不会修改模型机制、数据划分、训练目标或比较预算。'}
              </p>
            </section>
            {experimentMonitor.proposalRisks.length > 0 && (
              <section className="space-y-2">
                <Label>需要权衡的风险</Label>
                <ul className="space-y-1 text-xs leading-5 text-muted-foreground">
                  {experimentMonitor.proposalRisks.map((risk, index) => <li key={index}>• {risk}</li>)}
                </ul>
              </section>
            )}
            <p className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 font-medium leading-5 text-foreground">
              {experimentMonitor.proposalQuestion || '该变更能否在不改变科研主张的前提下解决已诊断问题？'}
            </p>
          </div>
          <DialogFooter className="shrink-0 flex-wrap border-t border-border bg-muted/20 px-5 py-3">
            {experimentMonitor.diagnosisPath && (
              <Button variant="outline" size="sm" onClick={() => openExperimentArtifact(experimentMonitor.diagnosisPath)}>
                <FileSearch className="h-3.5 w-3.5" /> 查看诊断
              </Button>
            )}
            {experimentMonitor.proposalPath && (
              <Button variant="ghost" size="sm" onClick={() => openExperimentArtifact(experimentMonitor.proposalPath)}>
                <FileText className="h-3.5 w-3.5" /> 提案原文
              </Button>
            )}
            <div className="flex-1" />
            <Button variant="outline" size="sm" onClick={() => handleResolveAdjustment(false)} disabled={adjustmentBusy}>
              <Ban className="h-3.5 w-3.5" /> 拒绝
            </Button>
            <Button size="sm" onClick={() => handleResolveAdjustment(true)} disabled={adjustmentBusy}>
              {adjustmentBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}
              批准该变更
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <WorkflowWorkspace model={model} />
    </div>
  )
}
