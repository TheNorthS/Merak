import { Sparkles, FileText, Terminal as TermIcon, Search, ChevronRight, Image, X, RotateCcw, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { type ChangeProposal, type ChatMessage, type ChatMode } from './chatTypes'
import { CHAT_MODES, getChatModeConfig } from './chatModes'
import { CodeBlock, MarkdownText } from './chatMarkdown'
import { formatArtifactPath, getComposerSuggestions } from './chatArtifacts'

export function ModeSelector({ mode, onModeChange }: { mode: ChatMode; onModeChange: (mode: ChatMode) => void }) {
  return (
    <div className="h-8 px-2 border-b border-border shrink-0 flex items-center gap-1 overflow-x-auto">
      {CHAT_MODES.map(item => {
        const Icon = item.icon
        const active = item.id === mode
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onModeChange(item.id)}
            title={item.title}
            className={cn(
              'h-6 px-2 inline-flex items-center gap-1 rounded text-2xs shrink-0 transition-colors',
              active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            <Icon size={10} />
            <span>{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}

export function EmptyState({
  activeFile,
  projectPath,
  mode,
  onSend,
}: {
  activeFile?: string | null
  projectPath?: string | null
  mode: ChatMode
  onSend: (msg: string, mode?: ChatMode) => void
}) {
  const fileName = activeFile?.split(/[\\/]/).pop()
  const modeLabel = getChatModeConfig(mode).label
  const prompts = getComposerSuggestions(mode, activeFile, projectPath)

  return (
    <div className="mx-auto max-w-[520px] py-10 text-center">
      <Sparkles size={28} className="mx-auto text-muted-foreground mb-3 opacity-50" />
      <p className="text-xs font-medium text-foreground mb-0.5">Research Copilot</p>
      <p className="text-2xs text-muted-foreground mb-4">
        {fileName ? `${modeLabel} · ${formatArtifactPath(activeFile, projectPath)}` : `${modeLabel} · 论文、实验、图表、slides`}
      </p>
      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {prompts.map(item => (
          <Button
            key={item.label}
            variant="outline"
            size="xs"
            onClick={() => onSend(item.prompt, item.mode)}
            className="w-full justify-start border-border bg-transparent text-left text-2xs text-muted-foreground hover:text-foreground"
          >
            {item.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

export function MessageBubble({ message, projectPath, onRetry, onResolveChange }: { message: ChatMessage; projectPath?: string | null; onRetry: () => void; onResolveChange: (proposal: ChangeProposal, approved: boolean) => void }) {
  if (message.role === 'user') {
    return (
      <div className="flex min-w-0 max-w-full justify-end overflow-hidden">
        <div className="min-w-0 max-w-[88%] overflow-hidden px-3.5 py-2.5 rounded-lg bg-muted border border-border text-foreground leading-relaxed break-words">
          <MarkdownText text={message.content} compact />
        </div>
      </div>
    )
  }

  const isError = message.content.startsWith('错误：') || message.content.startsWith('响应超时')
  const hasActivity = Boolean(
    (message.steps?.length ?? 0) ||
    (message.toolCalls?.length ?? 0) ||
    (message.toolResults?.length ?? 0)
  )
  const hasProposals = Boolean(message.changeProposals?.length)

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden space-y-2 rounded-lg border border-border/40 bg-card/30 px-3.5 py-3">
      <ToolActivity message={message} />
      <ChangeProposals proposals={message.changeProposals || []} projectPath={projectPath} onResolveChange={onResolveChange} />

      {(hasActivity || hasProposals) && message.content && (
        <div className="flex items-center gap-2 pt-1 text-2xs text-muted-foreground">
          <span className="h-px flex-1 bg-border/70" />
          <span className="shrink-0">正式回答</span>
          <span className="h-px flex-1 bg-border/70" />
        </div>
      )}

      {message.content && (
        <div className={cn('min-w-0 max-w-full', isError ? 'rounded-md border border-destructive/30 bg-destructive/5 p-2' : '')}>
          <MarkdownText text={message.content} />
          {isError && (
            <div className="mt-2 flex items-center gap-1">
              <Button variant="outline" size="xs" onClick={onRetry} className="h-6 text-2xs">
                <RotateCcw size={10} />
                重试上一条
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ToolActivity({ message }: { message: ChatMessage }) {
  const steps = message.steps || []
  const calls = message.toolCalls || []
  const results = message.toolResults || []
  if (steps.length === 0 && calls.length === 0 && results.length === 0) return null

  const failed = results.filter(r => !r.success).length
  const ok = results.filter(r => r.success).length

  return (
    <details className="group w-full min-w-0 max-w-full overflow-hidden rounded-md border border-border/70 bg-muted/25 text-2xs" open>
      <summary className="flex min-w-0 cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 text-muted-foreground hover:text-foreground">
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          <ChevronRight size={10} className="shrink-0 transition-transform group-open:rotate-90" />
          <span className="truncate">Agent Activity</span>
          {steps.length > 0 && <span className="font-mono">{steps.length} steps</span>}
          {calls.length > 0 && <span className="font-mono">{calls.length} calls</span>}
          {results.length > 0 && <span className="font-mono">{ok} ok</span>}
          {failed > 0 && <span className="font-mono text-red-400">{failed} failed</span>}
        </span>
      </summary>
      <div className="min-w-0 max-w-full space-y-1.5 overflow-hidden border-t border-border/50 px-2.5 py-2">
        {steps.map((step, i) => (
          <div key={`step-${i}`} className="min-w-0 rounded px-1 py-0.5 text-muted-foreground">
            <span className="font-medium text-foreground/80">{step.title}</span>
            {step.detail && <span className="ml-1 break-words text-muted-foreground/80 [overflow-wrap:anywhere]">{step.detail}</span>}
          </div>
        ))}
        {calls.map((tc, i) => (
          <div key={`call-${i}`} className="flex min-w-0 max-w-full items-center gap-1.5 overflow-hidden rounded px-1 py-0.5 text-muted-foreground">
            <ToolIcon name={tc.name} />
            <span className="min-w-0 max-w-[45%] truncate font-mono text-foreground/80">{tc.name}</span>
            <span className="min-w-0 truncate text-muted-foreground/70">{JSON.stringify(tc.args).slice(0, 80)}</span>
          </div>
        ))}
        {results.map((tr, i) => (
          <div key={`result-${i}`} className={cn(
            'min-w-0 max-w-full overflow-hidden rounded px-1 py-0.5',
            tr.success ? 'text-green-500' : 'text-red-400'
          )}>
            <div className="truncate font-mono">{tr.success ? '✓' : '✗'} {tr.name}</div>
            {tr.output && (
              <div className="mt-1 max-h-40 max-w-full overflow-y-auto overflow-x-hidden text-foreground">
                <MarkdownText text={tr.output.slice(0, 500)} compact />
              </div>
            )}
          </div>
        ))}
      </div>
    </details>
  )
}

export function ChangeProposals({ proposals, projectPath, onResolveChange }: { proposals: ChangeProposal[]; projectPath?: string | null; onResolveChange: (proposal: ChangeProposal, approved: boolean) => void }) {
  if (proposals.length === 0) return null

  const pending = proposals.filter(p => p.status === 'pending').length

  return (
    <section className="w-full min-w-0 max-w-full overflow-hidden rounded-md border border-border bg-background/70 text-2xs">
      <div className="flex min-w-0 items-center justify-between gap-2 border-b border-border/70 px-2.5 py-1.5">
        <div className="min-w-0">
          <div className="truncate font-medium text-foreground">待审批变更</div>
          <div className="text-muted-foreground">{proposals.length} proposal{proposals.length > 1 ? 's' : ''}{pending > 0 ? ` · ${pending} pending` : ''}</div>
        </div>
      </div>
      <div className="min-w-0 max-w-full space-y-2 overflow-hidden p-2">
        {proposals.map(proposal => (
          <div key={proposal.id} className="min-w-0 max-w-full overflow-hidden rounded-md border border-border bg-card p-2">
            <div className="mb-1.5 flex min-w-0 flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-2xs font-medium text-foreground" title={proposal.path}>{proposal.action} · {formatArtifactPath(proposal.path, projectPath)}</div>
                <div className="text-2xs text-muted-foreground">{proposal.id} · {proposal.status}</div>
                {proposal.status === 'expired' && (
                  <div className="mt-1 text-2xs text-amber-500">该提案所属后端会话已失效，请重新生成变更提案。</div>
                )}
              </div>
              {proposal.status === 'pending' && (
                <div className="flex min-w-0 flex-wrap items-center justify-end gap-1">
                  <Button size="xs" variant="outline" className="h-6 px-1.5 text-2xs" onClick={() => onResolveChange(proposal, false)}>
                    <X size={10} />
                    拒绝
                  </Button>
                  <Button size="xs" className="h-6 px-1.5 text-2xs" onClick={() => onResolveChange(proposal, true)}>
                    <Check size={10} />
                    批准
                  </Button>
                </div>
              )}
            </div>
            <CodeBlock language="diff" code={proposal.diff || 'No diff available'} />
          </div>
        ))}
      </div>
    </section>
  )
}

export function ToolIcon({ name }: { name: string }) {
  if (name.startsWith('Read') || name.startsWith('Write') || name.startsWith('Edit') || name.startsWith('Glob') || name.startsWith('Grep'))
    return <FileText size={10} className="text-blue-400" />
  if (name === 'Bash' || name.startsWith('ssh'))
    return <TermIcon size={10} className="text-green-400" />
  if (name.includes('search') || name.includes('Search'))
    return <Search size={10} className="text-yellow-400" />
  if (name.includes('image') || name.includes('Image') || name.includes('figure') || name.includes('Figure'))
    return <Image size={10} className="text-purple-400" />
  return <Sparkles size={10} className="text-muted-foreground" />
}
