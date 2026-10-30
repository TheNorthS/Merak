import Editor, { type Monaco, type OnMount } from '@monaco-editor/react'
import type { editor as MonacoEditorNamespace } from 'monaco-editor'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeSlug from 'rehype-slug'
import 'katex/dist/katex.min.css'
import {
  Bold,
  CheckSquare,
  Code2,
  Columns2,
  Eye,
  Heading2,
  Italic,
  Link,
  List,
  ListOrdered,
  PencilLine,
  Quote,
  Table2,
} from 'lucide-react'
import {
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { configureMerakMonaco } from '@/lib/monaco-config'
import { renderMermaidSvg } from '@/lib/mermaid-renderer'

type MarkdownViewMode = 'edit' | 'split' | 'preview'

interface MarkdownEditorProps {
  filePath: string
  content: string
  isDirty: boolean
  fontSize: number
  editorTheme: string
  onChange: (content: string) => void
  readClipboard: () => string
}

const VIEW_MODE_KEY = 'merak-ide:markdownViewMode'

const readViewMode = (): MarkdownViewMode => {
  try {
    const value = localStorage.getItem(VIEW_MODE_KEY)
    if (value === 'edit' || value === 'split' || value === 'preview') return value
  } catch {
    // Storage is optional in browser-only previews.
  }
  return 'split'
}

const externalUrlPattern = /^(?:https?:|mailto:|data:|blob:)/i

function localArtifactPath(filePath: string, rawTarget: string) {
  const cleanTarget = rawTarget.split('#', 1)[0].split('?', 1)[0]
  let decoded = cleanTarget
  try {
    decoded = decodeURIComponent(cleanTarget)
  } catch {
    // Keep the source text if it is not valid percent-encoding.
  }
  if (/^[a-zA-Z]:[\\/]/.test(decoded) || decoded.startsWith('/') || decoded.startsWith('\\\\')) {
    return decoded
  }
  const slashIndex = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'))
  const directory = slashIndex >= 0 ? filePath.slice(0, slashIndex) : ''
  const separator = filePath.includes('\\') ? '\\' : '/'
  return directory ? directory + separator + decoded.replace(/^\.?[\\/]/, '') : decoded
}

function binaryArtifactUrl(filePath: string, target: string) {
  return API_BASE + '/api/files/read-binary?path=' + encodeURIComponent(localArtifactPath(filePath, target))
}

function languageForPath(path: string) {
  const extension = path.split('.').pop()?.toLowerCase() || ''
  const languages: Record<string, string> = {
    md: 'markdown',
    markdown: 'markdown',
    py: 'python',
    tex: 'latex',
    bib: 'bibtex',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    csv: 'plaintext',
    tsv: 'plaintext',
    txt: 'plaintext',
    mmd: 'mermaid',
    mermaid: 'mermaid',
  }
  return languages[extension] || 'plaintext'
}

function countDocumentWords(content: string) {
  const cjkCount = content.match(/[\u3400-\u9fff]/g)?.length || 0
  const tokenCount = content.match(/[a-zA-Z0-9]+(?:['’-][a-zA-Z0-9]+)*/g)?.length || 0
  return cjkCount + tokenCount
}

export function MarkdownEditor({
  filePath,
  content,
  isDirty,
  fontSize,
  editorTheme,
  onChange,
  readClipboard,
}: MarkdownEditorProps) {
  const [mode, setMode] = useState<MarkdownViewMode>(readViewMode)
  const editorRef = useRef<MonacoEditorNamespace.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<Monaco | null>(null)
  const words = useMemo(() => countDocumentWords(content), [content])
  const lines = useMemo(() => Math.max(1, content.split(/\r?\n/).length), [content])

  const selectMode = (nextMode: MarkdownViewMode) => {
    setMode(nextMode)
    try {
      localStorage.setItem(VIEW_MODE_KEY, nextMode)
    } catch {
      // The selected mode still applies for this session.
    }
  }

  useEffect(() => {
    if (mode === 'preview') return
    const frame = requestAnimationFrame(() => editorRef.current?.layout())
    return () => cancelAnimationFrame(frame)
  }, [mode])

  const wrapSelection = (prefix: string, suffix: string, placeholder: string) => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    const model = editor?.getModel()
    const selection = editor?.getSelection()
    if (!editor || !monaco || !model || !selection) return

    const selected = model.getValueInRange(selection)
    const body = selected || placeholder
    editor.executeEdits('markdown-toolbar', [{
      range: selection,
      text: prefix + body + suffix,
      forceMoveMarkers: true,
    }])
    if (!selected) {
      const startOffset = model.getOffsetAt(selection.getStartPosition()) + prefix.length
      const endOffset = startOffset + placeholder.length
      const start = model.getPositionAt(startOffset)
      const end = model.getPositionAt(endOffset)
      editor.setSelection(new monaco.Selection(
        start.lineNumber,
        start.column,
        end.lineNumber,
        end.column,
      ))
    }
    editor.focus()
  }

  const prefixSelectedLines = (prefix: string | ((line: string, index: number) => string)) => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    const model = editor?.getModel()
    const selection = editor?.getSelection()
    if (!editor || !monaco || !model || !selection) return

    const range = new monaco.Range(
      selection.startLineNumber,
      1,
      selection.endLineNumber,
      model.getLineMaxColumn(selection.endLineNumber),
    )
    const selected = model.getValueInRange(range)
    const replacement = selected
      .split(/\r?\n/)
      .map((line, index) => (typeof prefix === 'function' ? prefix(line, index) : prefix) + line)
      .join(model.getEOL())
    editor.executeEdits('markdown-toolbar', [{
      range,
      text: replacement,
      forceMoveMarkers: true,
    }])
    editor.focus()
  }

  const setHeadingLevel = (level: number) => {
    const editor = editorRef.current
    const monaco = monacoRef.current
    const model = editor?.getModel()
    const selection = editor?.getSelection()
    if (!editor || !monaco || !model || !selection) return

    const range = new monaco.Range(
      selection.startLineNumber,
      1,
      selection.endLineNumber,
      model.getLineMaxColumn(selection.endLineNumber),
    )
    const selected = model.getValueInRange(range)
    const replacement = selected
      .split(/\r?\n/)
      .map(line => {
        const body = line.replace(/^\s{0,3}#{1,6}(?:\s+|$)/, '')
        if (level === 0) return body
        return '#'.repeat(level) + ' ' + (body || '标题')
      })
      .join(model.getEOL())
    editor.executeEdits('markdown-toolbar', [{
      range,
      text: replacement,
      forceMoveMarkers: true,
    }])
    editor.focus()
  }

  const insertBlock = (block: string) => {
    const editor = editorRef.current
    const model = editor?.getModel()
    const selection = editor?.getSelection()
    if (!editor || !model || !selection) return
    const startOffset = model.getOffsetAt(selection.getStartPosition())
    const prefix = startOffset > 0 && model.getValue().charAt(startOffset - 1) !== '\n' ? model.getEOL() : ''
    editor.executeEdits('markdown-toolbar', [{
      range: selection,
      text: prefix + block,
      forceMoveMarkers: true,
    }])
    editor.focus()
  }

  const onEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor
    monacoRef.current = monaco
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyV, () => {
      const text = readClipboard()
      if (text) editor.trigger('keyboard', 'paste', { text })
    })
  }

  const sourceEditor = (
    <MarkdownSourceEditor
      filePath={filePath}
      content={content}
      fontSize={fontSize}
      editorTheme={editorTheme}
      onChange={onChange}
      onMount={onEditorMount}
    />
  )
  const preview = <MarkdownPreview filePath={filePath} content={content} />

  return (
    <TooltipProvider delayDuration={250}>
      <div className="flex h-full min-h-0 flex-col bg-background">
        <div className="flex h-9 shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-card px-2">
          <div className="flex shrink-0 items-center gap-0.5 rounded border border-border bg-muted/30 p-0.5">
            <MarkdownToolButton label="编辑" active={mode === 'edit'} onClick={() => selectMode('edit')}>
              <PencilLine size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="分栏" active={mode === 'split'} onClick={() => selectMode('split')}>
              <Columns2 size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="预览" active={mode === 'preview'} onClick={() => selectMode('preview')}>
              <Eye size={14} />
            </MarkdownToolButton>
          </div>

          <div className="mx-1 h-4 w-px shrink-0 bg-border" />

          <div className="flex shrink-0 items-center gap-0.5" aria-label="Markdown 格式">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  disabled={mode === 'preview'}
                  aria-label="标题层级"
                  title="标题层级"
                  className="h-7 w-7 rounded-sm"
                >
                  <Heading2 size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-36">
                {[1, 2, 3, 4, 5, 6].map(level => (
                  <DropdownMenuItem key={level} onSelect={() => setHeadingLevel(level)}>
                    <span className="w-6 font-mono text-xs">H{level}</span>
                    <span>标题 {level}</span>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => setHeadingLevel(0)}>
                  <span className="w-6 font-mono text-xs">P</span>
                  <span>正文</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <MarkdownToolButton label="粗体" disabled={mode === 'preview'} onClick={() => wrapSelection('**', '**', '粗体文本')}>
              <Bold size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="斜体" disabled={mode === 'preview'} onClick={() => wrapSelection('*', '*', '斜体文本')}>
              <Italic size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton
              label="行内代码"
              disabled={mode === 'preview'}
              onClick={() => wrapSelection(String.fromCharCode(96), String.fromCharCode(96), 'code')}
            >
              <Code2 size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="链接" disabled={mode === 'preview'} onClick={() => wrapSelection('[', '](https://)', '链接文本')}>
              <Link size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="无序列表" disabled={mode === 'preview'} onClick={() => prefixSelectedLines('- ')}>
              <List size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton
              label="有序列表"
              disabled={mode === 'preview'}
              onClick={() => prefixSelectedLines((_line, index) => (index + 1) + '. ')}
            >
              <ListOrdered size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="任务项" disabled={mode === 'preview'} onClick={() => prefixSelectedLines('- [ ] ')}>
              <CheckSquare size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton label="引用" disabled={mode === 'preview'} onClick={() => prefixSelectedLines('> ')}>
              <Quote size={14} />
            </MarkdownToolButton>
            <MarkdownToolButton
              label="表格"
              disabled={mode === 'preview'}
              onClick={() => insertBlock('| 列 1 | 列 2 |\n| --- | --- |\n| 内容 | 内容 |\n')}
            >
              <Table2 size={14} />
            </MarkdownToolButton>
          </div>

          <div className="ml-auto flex shrink-0 items-center gap-2 px-1 text-[10px] tabular-nums text-muted-foreground">
            <span>{words.toLocaleString()} 字词</span>
            <span>{lines.toLocaleString()} 行</span>
            {isDirty && <span className="h-1.5 w-1.5 rounded-full bg-primary" title="未保存" />}
          </div>
        </div>

        <div className="min-h-0 flex-1">
          {mode === 'edit' && sourceEditor}
          {mode === 'preview' && preview}
          {mode === 'split' && (
            <PanelGroup direction="horizontal" className="h-full" id="markdown-editor-preview">
              <Panel id="markdown-source" order={1} defaultSize={52} minSize={25}>
                {sourceEditor}
              </Panel>
              <PanelResizeHandle className="w-px bg-border hover:bg-accent" />
              <Panel id="markdown-preview" order={2} defaultSize={48} minSize={25}>
                {preview}
              </Panel>
            </PanelGroup>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}

function MarkdownSourceEditor({
  filePath,
  content,
  fontSize,
  editorTheme,
  onChange,
  onMount,
}: {
  filePath: string
  content: string
  fontSize: number
  editorTheme: string
  onChange: (content: string) => void
  onMount: OnMount
}) {
  return (
    <div className="h-full min-h-0 monaco-container">
      <Editor
        path={filePath}
        language="markdown"
        value={content}
        theme={editorTheme}
        beforeMount={configureMerakMonaco}
        onMount={onMount}
        onChange={value => {
          if (value !== undefined) onChange(value)
        }}
        options={{
          fontSize,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          fontLigatures: true,
          lineHeight: 22,
          minimap: { enabled: false },
          smoothScrolling: true,
          cursorBlinking: 'smooth',
          cursorSmoothCaretAnimation: 'on',
          padding: { top: 12, bottom: 12 },
          renderLineHighlight: 'line',
          scrollBeyondLastLine: false,
          wordWrap: 'on',
          wrappingIndent: 'same',
          automaticLayout: true,
          useShadowDOM: false,
          stickyScroll: { enabled: true },
          quickSuggestions: false,
        }}
      />
    </div>
  )
}

function MarkdownPreview({ filePath, content }: { filePath: string; content: string }) {
  const openFile = useWorkspaceStore(state => state.openFile)

  const openLocalDocument = async (
    event: MouseEvent<HTMLAnchorElement>,
    href: string,
  ) => {
    if (!href || href.startsWith('#') || externalUrlPattern.test(href)) return
    const path = localArtifactPath(filePath, href)
    const extension = path.split('.').pop()?.toLowerCase() || ''
    if (!['md', 'markdown', 'txt', 'json', 'yaml', 'yml', 'tex', 'bib', 'py', 'csv', 'tsv'].includes(extension)) {
      return
    }
    event.preventDefault()
    try {
      const response = await fetch(API_BASE + '/api/files/read?path=' + encodeURIComponent(path))
      if (!response.ok) return
      const payload = await response.json()
      openFile({
        path,
        name: path.split(/[/\\]/).pop() || path,
        language: languageForPath(path),
        content: String(payload.content || ''),
      })
    } catch {
      const localContent = await window.merakIDE?.fs.readFile(path).catch(() => '')
      if (localContent !== undefined) {
        openFile({
          path,
          name: path.split(/[/\\]/).pop() || path,
          language: languageForPath(path),
          content: localContent,
        })
      }
    }
  }

  if (!content.trim()) {
    return (
      <div className="flex h-full items-center justify-center bg-background text-xs text-muted-foreground">
        此文档为空
      </div>
    )
  }

  return (
    <div className="h-full min-h-0 overflow-auto bg-background">
      <article className="merak-markdown-preview mx-auto min-h-full max-w-[960px] px-6 py-7 lg:px-10">
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex, rehypeSlug]}
          components={{
            a({ node: _node, href = '', children, ...props }) {
              const isExternal = externalUrlPattern.test(href)
              const isAnchor = href.startsWith('#')
              const renderedHref = !isExternal && !isAnchor
                ? binaryArtifactUrl(filePath, href)
                : href
              return (
                <a
                  {...props}
                  href={renderedHref}
                  target={isAnchor ? undefined : '_blank'}
                  rel={isAnchor ? undefined : 'noreferrer'}
                  onClick={event => void openLocalDocument(event, href)}
                >
                  {children}
                </a>
              )
            },
            img({ node: _node, src = '', alt = '', ...props }) {
              const renderedSrc = externalUrlPattern.test(src)
                ? src
                : binaryArtifactUrl(filePath, src)
              return <img {...props} src={renderedSrc} alt={alt} loading="lazy" />
            },
            pre({ node: _node, children, ...props }) {
              const child = Array.isArray(children) ? children[0] : children
              if (
                isValidElement<{ className?: string; children?: ReactNode }>(child)
                && child.props.className?.split(/\s+/).includes('language-mermaid')
              ) {
                return <MarkdownMermaid code={String(child.props.children || '').replace(/\n$/, '')} />
              }
              return <pre {...props}>{children}</pre>
            },
            code({ node: _node, className, children, ...props }) {
              return <code {...props} className={className}>{children}</code>
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </article>
    </div>
  )
}

function MarkdownMermaid({ code }: { code: string }) {
  const [svg, setSvg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setSvg('')
    setError('')
    renderMermaidSvg(code)
      .then(result => {
        if (!cancelled) setSvg(result)
      })
      .catch(() => {
        if (!cancelled) setError('Mermaid 图表语法有误')
      })
    return () => {
      cancelled = true
    }
  }, [code])

  if (error) {
    return <div className="my-4 rounded border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{error}</div>
  }
  if (!svg) {
    return <div className="my-4 h-24 animate-pulse rounded border border-border bg-muted/30" />
  }
  return (
    <div
      className="my-5 overflow-auto rounded border border-border bg-white p-4"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}

function MarkdownToolButton({
  label,
  active = false,
  disabled = false,
  onClick,
  children,
}: {
  label: string
  active?: boolean
  disabled?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          disabled={disabled}
          aria-label={label}
          aria-pressed={active}
          onClick={onClick}
          className={cn('h-7 w-7 rounded-sm', active && 'bg-accent text-foreground')}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
