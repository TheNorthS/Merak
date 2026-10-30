import { saveForCompilation } from '../../services/fileSave'
import { DeferredCodeEditor as Editor, DeferredMarkdownEditor as MarkdownEditor } from './DeferredEditors'
import { useWorkspaceStore, type OpenFile } from '../../stores/workspace'
import { X, Loader2, Play, CheckCircle, XCircle, Maximize2, RotateCcw, ZoomIn, ZoomOut, MoreHorizontal, ChevronLeft, ChevronRight, Layers } from 'lucide-react'
import { API_BASE } from '../../config'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { renderMermaidSvg } from '@/lib/mermaid-renderer'
import { useState, useEffect, useRef } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { PdfPreview } from './PdfPreview'
import { DrawioEditor } from './DrawioEditor'
import { ImagePreview } from './ImagePreview'
import { configureMerakMonaco } from '@/lib/monaco-config'
import { EditorWelcomeScreen as WelcomeScreen } from './EditorWelcomeScreen'

// Clipboard cache polled via Electron IPC. Used for both Ctrl+V and right-click Paste.
let _clipboardCache = ''

function useEditorSettings() {
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem('merak-ide:editorFontSize') || '14'))
  const [theme, setTheme] = useState(() => localStorage.getItem('merak-ide:theme') || 'dark')

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail.key === 'editorFontSize') setFontSize(Number(detail.value))
      if (detail.key === 'theme') setTheme(detail.value)
    }
    window.addEventListener('merak-ide:settings-changed', handler)
    return () => window.removeEventListener('merak-ide:settings-changed', handler)
  }, [])

  return { fontSize, editorTheme: theme === 'light' ? 'merak-light' : 'merak-dark' }
}


function EditorTabs() {
  const {
    openFiles,
    activeFileIndex,
    setActiveFile,
    closeFile,
    closeAllFiles,
    closeOtherFiles,
    closeFilesToLeft,
    closeFilesToRight,
  } = useWorkspaceStore()
  const scrollRef = useRef<HTMLDivElement>(null)
  const activeFile = activeFileIndex >= 0 ? openFiles[activeFileIndex] : null

  useEffect(() => {
    const container = scrollRef.current
    const activeTab = container?.querySelector<HTMLElement>('[data-active-tab="true"]')
    if (!container || !activeTab) return
    const left = activeTab.offsetLeft
    const right = left + activeTab.offsetWidth
    if (left < container.scrollLeft) {
      container.scrollLeft = left
    } else if (right > container.scrollLeft + container.clientWidth) {
      container.scrollLeft = right - container.clientWidth
    }
  }, [activeFileIndex, openFiles.length])

  const confirmClose = (files: OpenFile[]) => {
    const dirty = files.filter(file => file.isDirty)
    return dirty.length === 0 || window.confirm(
      `${dirty.length} 个标签页有未保存修改。仍然关闭吗？`,
    )
  }

  const closeOne = (file: OpenFile) => {
    if (confirmClose([file])) closeFile(file.path)
  }

  const closeAll = () => {
    if (confirmClose(openFiles)) closeAllFiles()
  }

  const closeOthers = () => {
    if (!activeFile) return
    const closing = openFiles.filter((_, index) => index !== activeFileIndex)
    if (confirmClose(closing)) closeOtherFiles(activeFile.path)
  }

  const closeLeft = () => {
    if (!activeFile || activeFileIndex <= 0) return
    if (confirmClose(openFiles.slice(0, activeFileIndex))) closeFilesToLeft(activeFile.path)
  }

  const closeRight = () => {
    if (!activeFile || activeFileIndex >= openFiles.length - 1) return
    if (confirmClose(openFiles.slice(activeFileIndex + 1))) closeFilesToRight(activeFile.path)
  }

  return (
    <div className="flex h-9 min-w-0 shrink-0 border-b border-border bg-card">
      <div className="flex shrink-0 items-center border-r border-border px-0.5">
        <Button
          variant="ghost"
          size="icon-sm"
          className="h-7 w-7 text-muted-foreground"
          onClick={() => scrollRef.current?.scrollBy({ left: -320, behavior: 'smooth' })}
          disabled={openFiles.length < 2}
          title="向左滚动标签页"
          aria-label="向左滚动标签页"
        >
          <ChevronLeft size={14} />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          className="h-7 w-7 text-muted-foreground"
          onClick={() => scrollRef.current?.scrollBy({ left: 320, behavior: 'smooth' })}
          disabled={openFiles.length < 2}
          title="向右滚动标签页"
          aria-label="向右滚动标签页"
        >
          <ChevronRight size={14} />
        </Button>
      </div>
      <div
        ref={scrollRef}
        className="min-w-0 flex-1 overflow-x-auto overflow-y-hidden [scrollbar-color:hsl(var(--border))_transparent] [scrollbar-width:thin]"
        onWheel={event => {
          if (!scrollRef.current || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
          scrollRef.current.scrollLeft += event.deltaY
          event.preventDefault()
        }}
      >
        <div className="flex h-full min-w-max items-stretch">
          {openFiles.map((file, index) => {
            const active = index === activeFileIndex
            return (
              <div
                key={file.path}
                data-active-tab={active}
                role="tab"
                aria-selected={active}
                title={file.path}
                onClick={() => setActiveFile(index)}
                onAuxClick={event => {
                  if (event.button === 1) {
                    event.preventDefault()
                    closeOne(file)
                  }
                }}
                className={cn(
                  'group flex h-full w-[148px] min-w-[104px] max-w-[180px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-border border-t-2 px-2.5 text-xs transition-colors',
                  active
                    ? 'border-t-primary bg-background text-foreground'
                    : 'border-t-transparent bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <span className="min-w-0 flex-1 truncate">{file.name}</span>
                {file.isDirty && (
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" title="未保存" />
                )}
                <button
                  type="button"
                  onClick={event => {
                    event.stopPropagation()
                    closeOne(file)
                  }}
                  className={cn(
                    'shrink-0 rounded p-0.5 transition-opacity hover:bg-accent',
                    active ? 'opacity-70 hover:opacity-100' : 'opacity-0 group-hover:opacity-70',
                  )}
                  aria-label={`关闭 ${file.name}`}
                  title="关闭"
                >
                  <X size={12} />
                </button>
              </div>
            )
          })}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-0.5 border-l border-border bg-card px-1">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="relative h-7 w-7 text-muted-foreground"
              disabled={openFiles.length === 0}
              title="全部标签页"
              aria-label="全部标签页"
            >
              <Layers size={14} />
              {openFiles.length > 0 && (
                <span className="absolute -right-0.5 -top-0.5 min-w-3.5 rounded-full bg-primary px-0.5 text-center text-[8px] leading-3.5 text-primary-foreground">
                  {openFiles.length > 99 ? '99+' : openFiles.length}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="max-h-72 w-72 overflow-y-auto">
            {openFiles.map((file, index) => (
              <DropdownMenuItem
                key={file.path}
                onSelect={() => setActiveFile(index)}
                className="min-w-0"
                title={file.path}
              >
                <CheckCircle className={cn('h-3.5 w-3.5 shrink-0', index === activeFileIndex ? 'text-primary opacity-100' : 'opacity-0')} />
                <span className="min-w-0 flex-1 truncate">{file.name}</span>
                {file.isDirty && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" title="未保存" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          variant="ghost"
          size="icon-sm"
          className="h-7 w-7 text-muted-foreground"
          onClick={closeAll}
          disabled={openFiles.length === 0}
          title="关闭全部标签页"
          aria-label="关闭全部标签页"
        >
          <XCircle size={14} />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="h-7 w-7 text-muted-foreground"
              title="标签页操作"
              aria-label="标签页操作"
            >
              <MoreHorizontal size={15} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem onSelect={() => activeFile && closeOne(activeFile)} disabled={!activeFile}>
              <X size={13} />
              关闭当前
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={closeOthers} disabled={openFiles.length <= 1}>
              <Layers size={13} />
              关闭其他
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={closeLeft} disabled={activeFileIndex <= 0}>
              <ChevronLeft size={13} />
              关闭左侧
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={closeRight} disabled={activeFileIndex < 0 || activeFileIndex >= openFiles.length - 1}>
              <ChevronRight size={13} />
              关闭右侧
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={closeAll} disabled={openFiles.length === 0} className="text-destructive focus:text-destructive">
              <XCircle size={13} />
              关闭全部
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
export function CodeEditor() {
  const { openFiles, activeFileIndex, updateFileContent } = useWorkspaceStore()
  const { fontSize, editorTheme } = useEditorSettings()

  // Poll Electron IPC clipboard every 400ms so _clipboardCache is always fresh
  useEffect(() => {
    const merakClipboard = (window as any).merakIDE?.clipboard
    if (!merakClipboard) return
    const refresh = () => merakClipboard.read().then((t: string) => { _clipboardCache = t }).catch(() => {})
    refresh()
    const interval = setInterval(refresh, 400)
    window.addEventListener('focus', refresh)
    return () => { clearInterval(interval); window.removeEventListener('focus', refresh) }
  }, [])
  const [pdfPreviewPath, setPdfPreviewPath] = useState<string | null>(null)
  const [pdfForFile, setPdfForFile] = useState<string | null>(null) // 记录是哪个 tex 编译的
  const [latexLog, setLatexLog] = useState<string | null>(null)

  const activeFile = activeFileIndex >= 0 ? openFiles[activeFileIndex] : null
  const isLatex = activeFile?.language === 'latex'
  const activeExtension = activeFile?.name.split('.').pop()?.toLowerCase() || ''
  const isMarkdown = activeFile?.language === 'markdown'
    || ['md', 'markdown', 'mdown', 'mkd'].includes(activeExtension)
  const isMermaid = activeExtension === 'mmd' || activeExtension === 'mermaid'
  const isDrawio = activeExtension === 'drawio' || activeExtension === 'dio'
  const isPdf = activeFile?.language === 'pdf' || activeExtension === 'pdf'
  const isImage = activeFile?.language === 'image'
    || ['png', 'jpg', 'jpeg', 'svg', 'webp', 'gif'].includes(activeExtension)

  // PDF 预览只在对应的 .tex 文件打开时显示
  const showPdfPreview = isLatex && pdfPreviewPath !== null && pdfForFile === activeFile?.path

  if (!activeFile) {
    return <WelcomeScreen />
  }

  // Binary research artifacts open directly in a dedicated preview instead of Monaco.
  if (isPdf || isImage) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <EditorTabs />
        <div className="min-h-0 flex-1">
          {isPdf
            ? <PdfPreview pdfPath={activeFile.path} />
            : <ImagePreview imagePath={activeFile.path} />}
        </div>
      </div>
    )
  }
  // .drawio 文件使用专用编辑器
  if (isDrawio) {
    return (
      <div className="h-full flex flex-col">
        <EditorTabs />
        {/* Draw.io 编辑器 */}
        <div className="flex-1">
          <DrawioEditor
            initialXml={activeFile.content}
            outputDir={activeFile.path.replace(/[/\\][^/\\]+$/, '')}
            onChange={(xml) => updateFileContent(activeFile.path, xml)}
          />
        </div>
      </div>
    )
  }
  if (isMarkdown) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <EditorTabs />
        <div className="min-h-0 flex-1">
          <MarkdownEditor
            filePath={activeFile.path}
            content={activeFile.content}
            isDirty={activeFile.isDirty}
            fontSize={fontSize}
            editorTheme={editorTheme}
            onChange={value => updateFileContent(activeFile.path, value)}
            readClipboard={() => _clipboardCache}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <EditorTabs />

      {/* LaTeX 工具栏（仅 .tex 文件显示） */}
      {isLatex && (
        <LatexToolbar filePath={activeFile.path} onCompiled={(pdfPath) => { setPdfPreviewPath(pdfPath); setPdfForFile(activeFile.path) }} onLog={setLatexLog} />
      )}

      {/* 代码编辑器 + 可选 PDF 预览分栏 */}
      <PanelGroup direction="horizontal" className="flex-1" id="editor-preview">
        {/* Monaco 编辑器 */}
        <Panel id="code" order={1} defaultSize={showPdfPreview ? 55 : 100} minSize={30}>
          <div className="h-full monaco-container">
        <Editor
          language={activeFile.language}
          value={activeFile.content}
          onChange={(value) => {
            if (value !== undefined) {
              updateFileContent(activeFile.path, value)
            }
          }}
          theme={editorTheme}
          beforeMount={configureMerakMonaco}
          onMount={(editor, monaco) => {
            // Ctrl+V: override keybinding directly — bypasses execCommand entirely
            editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyV, () => {
              const text = _clipboardCache
              if (text) editor.trigger('keyboard', 'paste', { text })
            })

            // Right-click "Paste": Monaco's context menu lives inside a Shadow DOM
            // (useShadowDOM:true by default). e.target is retargeted to the shadow host,
            // and closest() cannot cross shadow boundaries — so we use composedPath()
            // which returns the real element path through shadow roots.
            // Also: Monaco's MOUSE_DOWN calls preventDefault() suppressing 'click', so
            // we listen on 'mouseup' instead.
            const pasteClickHandler = (e: MouseEvent) => {
              const path = e.composedPath() as HTMLElement[]
              if (!path.some(el => el.classList?.contains('monaco-menu'))) return
              const labelEl = path.find(el => el.classList?.contains('action-label')) as HTMLElement | null
              if (!labelEl) return
              const label = labelEl.getAttribute('aria-label') ?? labelEl.textContent?.trim()
              if (label !== 'Paste') return
              const text = _clipboardCache
              if (!text) return
              setTimeout(() => {
                editor.focus()
                editor.trigger('keyboard', 'paste', { text })
              }, 0)
            }
            document.addEventListener('mouseup', pasteClickHandler, true)
            editor.onDidDispose(() => document.removeEventListener('mouseup', pasteClickHandler, true))

            const injectChat = (text: string) => {
              useWorkspaceStore.getState().setChatOpen(true)
              window.dispatchEvent(new CustomEvent('merak-ide:chat-inject', { detail: { text } }))
            }

            editor.addAction({
              id: 'merak-explain',
              label: 'Merak: 解释这段代码',
              contextMenuGroupId: 'merak',
              contextMenuOrder: 1,
              run: () => {
                const sel = editor.getSelection()
                const text = sel ? editor.getModel()?.getValueInRange(sel) : ''
                if (text?.trim()) {
                  injectChat(`请解释以下代码：\n\`\`\`\n${text.trim()}\n\`\`\``)
                } else {
                  const file = useWorkspaceStore.getState().openFiles[useWorkspaceStore.getState().activeFileIndex]
                  injectChat(`请解释文件 ${file?.name} 的整体逻辑`)
                }
              },
            })

            editor.addAction({
              id: 'merak-fix',
              label: 'Merak: 修复选中代码的 Bug',
              contextMenuGroupId: 'merak',
              contextMenuOrder: 2,
              run: () => {
                const sel = editor.getSelection()
                const text = sel ? editor.getModel()?.getValueInRange(sel) : ''
                const file = useWorkspaceStore.getState().openFiles[useWorkspaceStore.getState().activeFileIndex]
                if (text?.trim()) {
                  injectChat(`请修复以下代码中的 Bug，直接给出修改后的完整代码：\n\`\`\`\n${text.trim()}\n\`\`\``)
                } else {
                  injectChat(`请检查并修复文件 \`${file?.path}\` 中的 Bug`)
                }
              },
            })

            editor.addAction({
              id: 'merak-smart-edit',
              label: 'Merak: 智能修改（描述需求）',
              contextMenuGroupId: 'merak',
              contextMenuOrder: 3,
              run: () => {
                const sel = editor.getSelection()
                const text = sel ? editor.getModel()?.getValueInRange(sel) : ''
                const file = useWorkspaceStore.getState().openFiles[useWorkspaceStore.getState().activeFileIndex]
                const prefix = text?.trim()
                  ? `请对以下代码按我的描述进行修改：\n\`\`\`\n${text.trim()}\n\`\`\`\n\n需求：`
                  : `请对文件 \`${file?.path}\` 进行如下修改：\n\n需求：`
                injectChat(prefix)
              },
            })

            editor.addAction({
              id: 'merak-audit',
              label: 'Merak: 审计此文件',
              contextMenuGroupId: 'merak',
              contextMenuOrder: 4,
              run: () => {
                const file = useWorkspaceStore.getState().openFiles[useWorkspaceStore.getState().activeFileIndex]
                injectChat(`请对文件 \`${file?.path}\` 进行代码审计，检查潜在 bug、安全问题和可改进之处`)
              },
            })
          }}
          options={{
            fontSize,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            fontLigatures: true,
            lineHeight: 22,
            minimap: { enabled: true, scale: 1 },
            smoothScrolling: true,
            cursorBlinking: 'smooth',
            cursorSmoothCaretAnimation: 'on',
            padding: { top: 8 },
            renderLineHighlight: 'all',
            bracketPairColorization: { enabled: true },
            guides: { bracketPairs: true, indentation: true },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            automaticLayout: true,
            useShadowDOM: false,
          }}
        />
            </div>
          </Panel>

          {/* PDF 预览分栏（编译后显示） */}
          {showPdfPreview && (
            <>
              <PanelResizeHandle className="w-px bg-border-subtle hover:bg-accent transition-colors" />
              <Panel id="pdf-preview" order={2} defaultSize={45} minSize={20}>
                <PdfPreview pdfPath={pdfPreviewPath} />
              </Panel>
            </>
          )}

          {/* Mermaid 实时预览 */}
          {isMermaid && (
            <>
              <PanelResizeHandle className="w-px bg-border-subtle hover:bg-accent transition-colors" />
              <Panel id="mermaid-preview" order={2} defaultSize={45} minSize={20}>
                <MermaidPreview code={activeFile.content} />
              </Panel>
            </>
          )}
        </PanelGroup>

      {/* LaTeX 编译日志（下方面板） */}
      {isLatex && latexLog && (
        <div className="shrink-0 border-t border-border max-h-40 overflow-y-auto bg-background">
          <div className="flex items-center justify-between px-3 py-1 bg-card">
            <span className="text-2xs text-muted-foreground">Compile Output</span>
            <button onClick={() => setLatexLog(null)} className="text-2xs text-muted-foreground hover:text-foreground">✕ Close</button>
          </div>
          <pre className="px-3 py-2 text-2xs text-muted-foreground font-mono whitespace-pre-wrap">{latexLog}</pre>
        </div>
      )}
    </div>
  )
}


/** Mermaid 实时预览 */
function MermaidPreview({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(1)
  const [fit, setFit] = useState(true)

  useEffect(() => {
    let cancelled = false
    if (!containerRef.current) return
    if (!code.trim()) {
      containerRef.current.innerHTML = ''
      return
    }

    containerRef.current.innerHTML = '<p class="p-4 text-xs text-slate-500">Rendering Mermaid...</p>'
    renderMermaidSvg(code).then(svg => {
      if (cancelled || !containerRef.current) return
      containerRef.current.innerHTML = svg
      const svgElement = containerRef.current.querySelector('svg')
      if (svgElement) {
        svgElement.removeAttribute('width')
        svgElement.removeAttribute('height')
        svgElement.style.width = '100%'
        svgElement.style.height = 'auto'
        svgElement.style.maxWidth = 'none'
        svgElement.style.background = '#ffffff'
      }
    }).catch(() => {
      if (!cancelled && containerRef.current) {
        containerRef.current.innerHTML = '<p class="p-4 text-xs text-red-600">Mermaid syntax error</p>'
      }
    })

    return () => {
      cancelled = true
    }
  }, [code])

  const changeZoom = (next: number) => {
    setFit(false)
    setZoom(Math.min(4, Math.max(0.25, next)))
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex h-9 shrink-0 items-center justify-end gap-0.5 border-b border-border bg-card px-2">
        <Button variant="ghost" size="icon-sm" onClick={() => changeZoom(zoom - 0.25)} title="Zoom out">
          <ZoomOut size={14} />
        </Button>
        <span className="w-12 text-center text-2xs tabular-nums text-muted-foreground">
          {fit ? 'Fit' : Math.round(zoom * 100) + '%'}
        </span>
        <Button variant="ghost" size="icon-sm" onClick={() => changeZoom(zoom + 0.25)} title="Zoom in">
          <ZoomIn size={14} />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => { setFit(false); setZoom(1) }} title="Actual size">
          <RotateCcw size={14} />
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={() => setFit(true)} title="Fit to window">
          <Maximize2 size={14} />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <div
          className={fit ? 'mx-auto flex min-h-full w-full items-center justify-center' : 'mx-auto min-h-full'}
          style={fit ? undefined : { width: zoom * 100 + '%' }}
        >
          <div ref={containerRef} className="w-full" />
        </div>
      </div>
    </div>
  )
}
/** LaTeX 编译工具栏 */
function LatexToolbar({ filePath, onCompiled, onLog }: { filePath: string; onCompiled: (pdfPath: string) => void; onLog: (log: string | null) => void }) {
  const [compiling, setCompiling] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null)

  const handleCompile = async () => {
    setCompiling(true)
    setResult(null)
    onLog(null)

    try {
      await saveForCompilation(filePath)
      const sep = filePath.includes('/') ? '/' : '\\'
      const lastSep = filePath.lastIndexOf(sep)
      const dir = filePath.substring(0, lastSep)
      const texFile = filePath.substring(lastSep + 1)

      const res = await fetch(`${API_BASE}/api/files/latex-compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_dir: dir, main_tex: texFile }),
      })

      if (!res.ok) {
        const text = await res.text()
        setResult({ ok: false, msg: `Server error: ${res.status}` })
        onLog(text)
        setCompiling(false)
        return
      }

      const data = await res.json()
      if (data.success) {
        setResult({ ok: true, msg: `${data.pages} pages (${data.compiler})` })
        if (data.pdf) onCompiled(data.pdf)
        if (data.output) onLog(data.output)
      } else {
        setResult({ ok: false, msg: `Compilation failed` })
        onLog(data.output || data.error || 'Unknown error')
      }
    } catch (err: any) {
      const msg = err?.message || err?.toString() || 'Network error — is backend running on port 8011?'
      console.error('[LaTeX] Compile fetch error:', err)
      setResult({ ok: false, msg })
      onLog(`Fetch error: ${msg}\n\nMake sure backend is running:\npython -m uvicorn server.main:app --port 8011`)
    }
    setCompiling(false)
  }

  return (
    <div className="flex items-center gap-2 px-3 h-9 bg-card border-b border-border shrink-0">
      <Button
        onClick={handleCompile}
        disabled={compiling}
        size="xs"
        className="gap-1"
      >
        {compiling ? <><Loader2 size={12} className="animate-spin" /> Compiling...</> : <><Play size={12} /> Compile PDF</>}
      </Button>
      {result && (
        <span className={`text-xs flex items-center gap-1 ${result.ok ? 'text-green-500' : 'text-destructive'}`}>
          {result.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {result.msg}
        </span>
      )}
      <span className="ml-auto text-xs text-muted-foreground">LaTeX → PDF</span>
    </div>
  )
}
