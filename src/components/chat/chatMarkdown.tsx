import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn } from '@/lib/utils'

export function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={i} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*'))
      return <em key={i}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`'))
      return <code key={i} className="px-1 py-0.5 rounded bg-muted text-xs font-mono text-foreground break-all [overflow-wrap:anywhere]">{part.slice(1, -1)}</code>
    return part
  })
}

export function codeLineClass(line: string, language: string) {
  const lang = language.toLowerCase()
  if (!lang.includes('diff') && !lang.includes('patch')) return ''
  if (line.startsWith('+') && !line.startsWith('+++')) return 'text-green-500'
  if (line.startsWith('-') && !line.startsWith('---')) return 'text-red-400'
  if (line.startsWith('@@')) return 'text-blue-400'
  return ''
}

export function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false)
  const lang = language || 'text'
  const lines = code.split('\n')

  const handleCopy = async () => {
    try {
      await navigator.clipboard?.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="my-2 w-full min-w-0 max-w-full overflow-hidden rounded-md border border-border bg-muted/70">
      <div className="flex w-full min-w-0 items-center justify-between gap-2 border-b border-border/70 px-2 py-1">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="rounded bg-background px-1.5 py-0.5 text-2xs font-mono text-muted-foreground">{lang}</span>
          <span className="truncate text-2xs text-muted-foreground">{lines.length} lines</span>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex h-5 shrink-0 items-center gap-1 rounded px-1.5 text-2xs text-muted-foreground hover:bg-background hover:text-foreground"
          title="复制代码"
        >
          {copied ? <Check size={10} /> : <Copy size={10} />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <div className="max-h-96 w-full min-w-0 max-w-full overflow-y-auto overflow-x-hidden bg-background/40">
        <pre className="w-full min-w-0 overflow-hidden whitespace-pre-wrap break-words p-2 text-[11px] leading-5 text-foreground [overflow-wrap:anywhere]">
          <code className="block w-full min-w-0 font-mono">
            {lines.map((line, index) => (
              <span key={index} className={cn('grid w-full min-w-0 grid-cols-[2.25rem_minmax(0,1fr)] gap-3', codeLineClass(line, lang))}>
                <span className="select-none text-right text-muted-foreground/60">{index + 1}</span>
                <span className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{line || ' '}</span>
              </span>
            ))}
          </code>
        </pre>
      </div>
    </div>
  )
}

export function normalizeMarkdownInput(text: string) {
  return text.replace(/\r\n/g, '\n').replace(/\\`\\`\\`/g, '```')
}

export function MarkdownText({ text, compact = false }: { text: string; compact?: boolean }) {
  const lines = normalizeMarkdownInput(text).split('\n')
  const elements: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const fenceMatch = line.match(/^\s*```\s*([A-Za-z0-9_+\-#.]+)?\s*$/)

    if (fenceMatch) {
      const codeLines: string[] = []
      const lang = fenceMatch[1] || ''
      i++
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        codeLines.push(lines[i])
        i++
      }
      elements.push(<CodeBlock key={`code-${i}`} language={lang} code={codeLines.join('\n')} />)
      if (i < lines.length) i++
      continue
    }

    if (line.startsWith('### ')) {
      elements.push(<h3 key={i} className="mt-2 mb-1 text-xs font-semibold text-foreground">{renderInline(line.slice(4))}</h3>)
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={i} className="mt-3 mb-1 text-sm font-semibold text-foreground">{renderInline(line.slice(3))}</h2>)
    } else if (line.startsWith('# ')) {
      elements.push(<h1 key={i} className="mt-3 mb-1 text-sm font-bold text-foreground">{renderInline(line.slice(2))}</h1>)
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(
        <div key={i} className="flex min-w-0 gap-1.5 my-0.5">
          <span className="text-muted-foreground mt-px shrink-0">·</span>
          <span className="min-w-0 break-words [overflow-wrap:anywhere]">{renderInline(line.slice(2))}</span>
        </div>
      )
    } else if (line.match(/^\d+\. /)) {
      const m = line.match(/^(\d+)\. (.*)/)!
      elements.push(
        <div key={i} className="flex min-w-0 gap-1.5 my-0.5">
          <span className="text-muted-foreground shrink-0 w-4 text-right">{m[1]}.</span>
          <span className="min-w-0 break-words [overflow-wrap:anywhere]">{renderInline(m[2])}</span>
        </div>
      )
    } else if (line.startsWith('> ')) {
      elements.push(
        <blockquote key={i} className="border-l-2 border-border pl-2 text-muted-foreground italic my-1">
          {renderInline(line.slice(2))}
        </blockquote>
      )
    } else if (line === '' || line === '\n') {
      elements.push(<div key={i} className="h-2" />)
    } else {
      elements.push(<p key={i} className="min-w-0 break-words leading-relaxed [overflow-wrap:anywhere]">{renderInline(line)}</p>)
    }

    i++
  }

  return <div className={cn('min-w-0 max-w-full break-words text-foreground space-y-px [overflow-wrap:anywhere]', compact ? 'text-xs' : 'text-sm')}>{elements}</div>
}
