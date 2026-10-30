import type { RefObject } from 'react'
import {
  CircleAlert, CircleCheck, FileSearch, Loader2, PenLine,
  RefreshCw, Send, Shield, Square,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'

import type {
  ExperimentMonitorState,
  LogEntry,
  PaperStageProgress,
} from './workflowViewModels'


interface WorkflowLogPanelProps {
  logs: LogEntry[]
  logsEndRef: RefObject<HTMLDivElement>
  paperStages: PaperStageProgress[]
  paperProgressVisible: boolean
  experiment: ExperimentMonitorState
  busy: boolean
  onStop: () => void
  onOpenDiagnosis: () => void
  onProposeAdjustment: () => void
  onReviewApproval: () => void
  onRetry: () => void
}

const LEVEL_COLORS: Record<string, string> = {
  info: 'text-muted-foreground',
  warn: 'text-yellow-400',
  error: 'text-red-400',
  agent: 'text-foreground',
  tool: 'text-cyan-400',
}

function PaperProgress({ stages }: { stages: PaperStageProgress[] }) {
  const reviewed = stages.filter(stage => ['passed', 'reused'].includes(stage.status)).length
  const active = stages.find(stage => stage.status === 'running')
    || stages.find(stage => stage.status === 'revision_required')
  const percent = stages.length > 0 ? Math.round((reviewed / stages.length) * 100) : 0
  return (
    <section className="shrink-0 border-b border-border bg-muted/20" aria-label="论文分章写作进度">
      <div className="space-y-2 px-3 py-2.5">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
              <PenLine className="h-3.5 w-3.5 shrink-0" /><span>论文分章写作</span>
            </div>
            <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
              {active
                ? `${active.label} · ${active.agentStatus || (active.status === 'revision_required' ? '等待局部返修' : '进行中')}`
                : reviewed === stages.length ? '全部章节已独立验收并完成组装' : '等待论文节点执行'}
            </p>
          </div>
          <Badge variant="outline" className="shrink-0 text-[10px]">{reviewed}/{stages.length}</Badge>
        </div>
        <div className="h-1.5 overflow-hidden rounded-sm bg-muted" aria-label={`论文完成度 ${percent}%`}>
          <div className="h-full bg-emerald-500 transition-[width] duration-300" style={{ width: `${percent}%` }} />
        </div>
      </div>
      <div className="max-h-52 overflow-y-auto border-t border-border/70 px-2 py-1.5">
        {stages.map((stage, index) => <PaperStageRow key={stage.id} stage={stage} index={index} />)}
      </div>
    </section>
  )
}

function PaperStageRow({ stage, index }: { stage: PaperStageProgress; index: number }) {
  const statusLabel = stage.status === 'passed' ? '已通过'
    : stage.status === 'reused' ? '已复用'
      : stage.status === 'running' ? `第 ${stage.attempt || 1} 次`
        : stage.status === 'revision_required' ? '需返修' : '待开始'
  return (
    <div className={cn(
      'grid min-w-0 grid-cols-[18px_minmax(0,1fr)_auto] items-start gap-1.5 rounded-sm px-1.5 py-1 text-[10px]',
      stage.status === 'running' && 'bg-accent text-accent-foreground',
      stage.status === 'revision_required' && 'bg-amber-500/10',
    )}>
      <span className="pt-0.5 text-muted-foreground">
        {stage.status === 'running' ? <Loader2 className="h-3 w-3 animate-spin" />
          : stage.status === 'revision_required' ? <CircleAlert className="h-3 w-3 text-amber-400" />
            : ['passed', 'reused'].includes(stage.status) ? <CircleCheck className="h-3 w-3 text-emerald-500" />
              : <span className="inline-flex h-3 w-3 items-center justify-center font-mono text-[9px]">{index + 1}</span>}
      </span>
      <div className="min-w-0">
        <div className="truncate text-foreground">{stage.label}</div>
        {stage.status === 'revision_required' && stage.issues[0] && (
          <div className="mt-0.5 line-clamp-2 break-words text-amber-300" title={stage.issues.join('\n')}>{stage.issues[0]}</div>
        )}
      </div>
      <span className={cn('shrink-0 pt-0.5', stage.status === 'revision_required' ? 'text-amber-300' : 'text-muted-foreground')}>{statusLabel}</span>
    </div>
  )
}

function ExperimentMonitor({
  experiment, busy, onStop, onOpenDiagnosis, onProposeAdjustment,
  onReviewApproval, onRetry,
}: Pick<WorkflowLogPanelProps, 'experiment' | 'busy' | 'onStop' | 'onOpenDiagnosis' | 'onProposeAdjustment' | 'onReviewApproval' | 'onRetry'>) {
  return (
    <div className="border-b border-border bg-muted/30 px-3 py-2 text-[10px] text-muted-foreground space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', experiment.active ? 'bg-emerald-500 animate-pulse' : experiment.phase === 'completed' ? 'bg-emerald-500' : 'bg-amber-500')} />
          <span className="truncate">{experiment.backend || 'experiment'} · {experiment.phase || 'pending'}</span>
        </span>
        {experiment.gpus.length > 0 && <span className="shrink-0">GPU {String(experiment.gpus[0]?.utilization_percent ?? '?')}% · {String(experiment.gpus[0]?.memory_used_mb ?? '?')}/{String(experiment.gpus[0]?.memory_total_mb ?? '?')} MB</span>}
      </div>
      {Object.keys(experiment.metrics).length > 0 && <div className="truncate font-mono text-foreground/80">{Object.entries(experiment.metrics).slice(0, 5).map(([key, value]) => `${key}=${String(value)}`).join(' · ')}</div>}
      {experiment.anomaly && <div className="text-red-400 break-words">{experiment.anomaly}</div>}
      {experiment.proposalSummary && <div className="break-words text-amber-300">提案：{experiment.proposalSummary}</div>}
      {experiment.proposalStatus === 'pending' && experiment.proposalRationale && <div className="break-words text-foreground/75">依据：{experiment.proposalRationale}</div>}
      {experiment.proposalStatus === 'pending' && Object.keys(experiment.proposalChanges).length > 0 && (
        <div className="break-words font-mono text-foreground/75">{Object.entries(experiment.proposalChanges).filter(([, value]) => value !== null && value !== '').map(([key, value]) => `${key}=${String(value).slice(0, 240)}`).join(' · ') || '无运行参数变更；仅记录已审批的源码/基础设施调整'}</div>
      )}
      {(experiment.active || experiment.diagnosisPath || experiment.phase === 'awaiting_approval' || experiment.phase === 'ready_to_retry') && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1.5">
          {experiment.active && !['stopping', 'queued'].includes(experiment.phase) && <Button size="sm" variant="destructive" className="h-7 text-[11px]" onClick={onStop}><Square className="h-3.5 w-3.5" /> 安全停止</Button>}
          {experiment.diagnosisPath && <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={onOpenDiagnosis}><FileSearch className="h-3.5 w-3.5" /> 诊断</Button>}
          {!experiment.active && !experiment.proposalId && experiment.phase !== 'completed' && <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={onProposeAdjustment}><Send className="h-3.5 w-3.5" /> 提出调整</Button>}
          {experiment.proposalStatus === 'pending' && <Button size="sm" className="h-7 text-[11px]" onClick={onReviewApproval} disabled={busy}><Shield className="h-3.5 w-3.5" /> 审查调整提案</Button>}
          {experiment.proposalStatus === 'approved' && <Button size="sm" className="h-7 text-[11px]" onClick={onRetry} disabled={busy}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}新 attempt</Button>}
        </div>
      )}
    </div>
  )
}

export function WorkflowLogPanel(props: WorkflowLogPanelProps) {
  return (
    <div className="h-full flex flex-col bg-background">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Live Output</h3>
        <Badge variant="secondary" className="text-2xs">{props.logs.length} entries</Badge>
      </div>
      {props.paperProgressVisible && <PaperProgress stages={props.paperStages} />}
      {(props.experiment.active || props.experiment.phase) && <ExperimentMonitor {...props} />}
      <ScrollArea className="flex-1">
        <div className="p-3 font-mono text-xs space-y-0.5">
          {props.logs.length === 0 && <p className="text-muted-foreground text-center py-8">Logs will appear here when the pipeline runs...</p>}
          {props.logs.map((entry, index) => (
            <div key={`${entry.time}-${index}`} className="flex gap-2 min-w-0">
              <span className="text-muted-foreground shrink-0">{entry.time}</span>
              <span className={cn('shrink-0 w-14', LEVEL_COLORS[entry.level] || 'text-muted-foreground')}>[{entry.source}]</span>
              <span className={cn('min-w-0 flex-1 whitespace-pre-wrap break-words [overflow-wrap:anywhere]', LEVEL_COLORS[entry.level] || 'text-foreground')}>{entry.message}</span>
            </div>
          ))}
          <div ref={props.logsEndRef} />
        </div>
      </ScrollArea>
    </div>
  )
}
