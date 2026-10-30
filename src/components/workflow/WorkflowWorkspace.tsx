import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { ArrowLeft, Square, Zap, RotateCcw, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ConfigPanel } from './ConfigPanel'
import { WorkflowLogPanel as LogPanel } from './WorkflowLogPanel'
import { NodeGraphPanel } from './WorkflowNodeGraphPanel'
import type { WorkflowController } from './useWorkflowController'

export function WorkflowWorkspace({ model }: { model: WorkflowController }) {
  const { setWorkflowFullscreen, pausedRunId, resumableState, checkpointNode, setPausedRunIdSafe, handleResume, isResuming, isRunning, handleStop, handleRun, config, handleReset, updateWorkflowConfig, integrationStatus, nodes, setNodes, projectPath, focusedNode, setFocusedNode, nodeSchema, nodeParams, setNodeParams, handleRunSingleNode, specialistNodes, logs, logsEndRef, paperStages, paperProgressVisible, experimentMonitor, adjustmentBusy, handleExperimentStop, openExperimentArtifact, setAdjustmentDraft, setAdjustmentDialogOpen, setApprovalDialogOpen, handleRetryExperiment } = model
  return <>
      {/* 顶栏 — 可拖拽移动窗口 */}
      <div className="h-10 px-4 flex items-center justify-between border-b border-border bg-card shrink-0 titlebar-drag">
        <div className="flex items-center gap-3 titlebar-no-drag">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setWorkflowFullscreen(false)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft size={14} />
            返回 IDE
          </Button>
          <span className="text-xs font-medium text-foreground">Merak 研究工作流</span>
        </div>
        <div className="flex items-center gap-2 titlebar-no-drag">
          {/* 运行控制 */}
          {pausedRunId && !resumableState && (
            <Button
              variant="default"
              size="sm"
              onClick={() => handleResume()}
              disabled={isResuming}
              className="titlebar-no-drag relative z-[71] bg-green-600 text-white text-xs hover:bg-green-700 animate-pulse disabled:pointer-events-auto disabled:cursor-wait"
            >
              {isResuming ? <Loader2 size={12} className="animate-spin" /> : '▶'}
              {isResuming ? '恢复中...' : '继续'}
            </Button>
          )}
          {isRunning ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleStop}
              className="flex items-center gap-1 text-xs"
            >
              <Square size={10} /> 停止
            </Button>
          ) : resumableState ? (
            <>
              <span className="text-xs text-amber-500">已中断 · 等待恢复</span>
              <Button size="sm" disabled={isResuming} className="text-xs" onClick={() => {
                if (checkpointNode?.persisted && checkpointNode.id === resumableState.current_node) setPausedRunIdSafe(resumableState.run_id)
                else void handleResume(resumableState)
              }}>
                {isResuming ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                {isResuming ? '恢复中...' : '恢复执行'}
              </Button>
            </>
          ) : (
            <Button
              variant="default"
              size="sm"
              onClick={() => handleRun()}
              disabled={
                !config.researchDirection.trim()
                || (config.researchMode === 'paper_code_innovation' && (!config.refPaper.trim() || !config.baseRepo.trim()))
              }
              className="flex items-center gap-1 text-xs disabled:opacity-40"
            >
              <Zap size={10} /> 运行流水线
            </Button>
          )}
          <Button variant="ghost" size="icon-sm" onClick={handleReset} className="text-muted-foreground" title="重置">
            <RotateCcw size={14} />
          </Button>

          {/* 窗口控制 */}
          <div className="ml-2 flex items-center gap-0.5">
            <Button variant="ghost" size="icon-sm" onClick={() => window.merakIDE?.window.minimize()} className="text-muted-foreground hover:text-foreground" title="最小化">
              <span className="text-xs">—</span>
            </Button>
            <Button variant="ghost" size="icon-sm" onClick={() => window.merakIDE?.window.maximize()} className="text-muted-foreground hover:text-foreground" title="最大化">
              <Square size={12} />
            </Button>
          </div>
        </div>
      </div>

      {/* Keep all three work surfaces readable when the IDE window is narrow. */}
      <div className="flex-1 min-h-0 overflow-x-auto">
        <PanelGroup direction="horizontal" className="h-full min-w-[1160px]">
        {/* 左栏：配置面板 */}
        <Panel id="wf-config" order={1} defaultSize={25} minSize={18} maxSize={35}>
          <ConfigPanel
            config={config}
            onUpdate={updateWorkflowConfig}
            integrationStatus={integrationStatus}
            experimentNodeSelected={nodes.some(node => node.id === 'exp-run' && node.selected)}
            compileNodeSelected={nodes.some(node => node.id === 'compile' && node.selected)}
          />
        </Panel>
        <PanelResizeHandle className="w-px bg-border-subtle hover:bg-accent transition-colors" />

        {/* 中栏：节点图 */}
        <Panel id="wf-nodes" order={2} defaultSize={35} minSize={25}>
          <NodeGraphPanel nodes={nodes} setNodes={setNodes} isRunning={isRunning} hasProject={Boolean(projectPath)} focusedNode={focusedNode} setFocusedNode={setFocusedNode} nodeSchema={nodeSchema} nodeParams={nodeParams} setNodeParams={setNodeParams} handleRunSingleNode={handleRunSingleNode} specialistNodes={specialistNodes} />
        </Panel>
        <PanelResizeHandle className="w-px bg-border-subtle hover:bg-accent transition-colors" />

        {/* 右栏：实时日志 */}
        <Panel id="wf-logs" order={3} defaultSize={40} minSize={20}>
          <LogPanel
            logs={logs}
            logsEndRef={logsEndRef}
            paperStages={paperStages}
            paperProgressVisible={paperProgressVisible}
            experiment={experimentMonitor}
            busy={adjustmentBusy}
            onStop={handleExperimentStop}
            onOpenDiagnosis={() => openExperimentArtifact(experimentMonitor.diagnosisPath)}
            onProposeAdjustment={() => {
              setAdjustmentDraft({
                summary: '',
                rationale: experimentMonitor.anomaly || '',
                batchSize: '',
                command: '',
              })
              setAdjustmentDialogOpen(true)
            }}
            onReviewApproval={() => setApprovalDialogOpen(true)}
            onRetry={handleRetryExperiment}
          />
        </Panel>
        </PanelGroup>
      </div>

  </>
}
