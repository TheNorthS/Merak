import { useState, useRef, useEffect, useCallback } from 'react'
import { Maximize2, Minimize2, RotateCcw } from 'lucide-react'

const DRAWIO_ORIGIN = 'https://embed.diagrams.net'

interface DrawioEditorProps {
  initialXml?: string
  /** 导出文件保存目录（Electron 环境下自动保存到磁盘） */
  outputDir?: string
  onChange?: (xml: string) => void
  /** 导出完成回调：Electron 下 data 为保存路径，浏览器下为 base64 data URL */
  onExport?: (format: 'svg' | 'pdf' | 'png', data: string) => void
}

/**
 * Draw.io 内嵌编辑器
 * 通过 iframe 加载 diagrams.net，使用 postMessage API 通信
 */
export function DrawioEditor({ initialXml, outputDir, onChange, onExport }: DrawioEditorProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const [loaded, setLoaded] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  useEffect(() => {
    if (!isFullscreen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isFullscreen])

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (
        event.origin !== DRAWIO_ORIGIN ||
        event.source !== iframeRef.current?.contentWindow
      ) return
      if (!event.data || typeof event.data !== 'string') return

      try {
        const msg = JSON.parse(event.data)

        switch (msg.event) {
          case 'init':
            // 编辑器初始化完成
            setLoaded(true)
            if (initialXml) {
              // 加载初始 XML
              postToDrawio({ action: 'load', xml: initialXml })
            }
            break

          case 'save':
            onChange?.(msg.xml)
            break

          case 'export': {
            const merakIDE = (window as any).merakIDE
            if (outputDir && merakIDE?.drawio?.saveExport) {
              // Electron 环境：直接保存到磁盘
              const ext = msg.format === 'pdf' ? 'pdf' : msg.format === 'svg' ? 'svg' : 'png'
              const filename = `drawio_${Date.now()}.${ext}`
              const outPath = `${outputDir.replace(/\\/g, '/')}/${filename}`
              merakIDE.drawio.saveExport(msg.data, msg.format, outPath).then((res: any) => {
                onExport?.(msg.format, res.success ? res.path : msg.data)
              })
            } else {
              onExport?.(msg.format, msg.data)
            }
            break
          }

          case 'autosave':
            onChange?.(msg.xml)
            break
        }
      } catch {
        // 非 JSON 消息忽略
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [initialXml, outputDir, onChange, onExport])

  const postToDrawio = useCallback((msg: Record<string, unknown>) => {
    if (iframeRef.current?.contentWindow) {
      iframeRef.current.contentWindow.postMessage(JSON.stringify(msg), DRAWIO_ORIGIN)
    }
  }, [])

  const handleExport = (format: 'svg' | 'pdf' | 'png') => {
    postToDrawio({ action: 'export', format })
  }

  const handleReset = () => {
    postToDrawio({ action: 'load', xml: '' })
  }

  // Draw.io embed URL with configuration
  const drawioUrl = new URL('https://embed.diagrams.net/')
  drawioUrl.searchParams.set('embed', '1')
  drawioUrl.searchParams.set('proto', 'json')
  drawioUrl.searchParams.set('spin', '1')
  drawioUrl.searchParams.set('ui', 'dark')
  drawioUrl.searchParams.set('noSaveBtn', '0')
  drawioUrl.searchParams.set('noExitBtn', '1')
  drawioUrl.searchParams.set('saveAndExit', '0')

  return (
    <div
      ref={rootRef}
      className={
        'titlebar-no-drag flex min-h-0 flex-col bg-background ' +
        (isFullscreen ? 'fixed inset-0 z-[200] h-screen w-screen' : 'h-full')
      }
    >
      {/* 工具栏 */}
      <div className="h-9 px-3 flex items-center justify-between bg-surface-1 border-b border-border-subtle shrink-0">
        <span className="text-xs font-medium text-gray-300">Draw.io Editor</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setIsFullscreen(current => !current)}
            className="p-1.5 rounded-sm text-gray-400 hover:bg-surface-3 hover:text-gray-100"
            title={isFullscreen ? '退出全屏 (Esc)' : '全屏编辑'}
            aria-label={isFullscreen ? '退出全屏' : '全屏编辑'}
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button onClick={handleReset} className="p-1.5 rounded-sm hover:bg-surface-3 text-gray-500" title="Reset">
            <RotateCcw size={12} />
          </button>
          <button onClick={() => handleExport('svg')} className="px-2 py-1 text-2xs text-gray-400 hover:text-merak-400 rounded hover:bg-surface-3">
            SVG
          </button>
          <button onClick={() => handleExport('pdf')} className="px-2 py-1 text-2xs text-gray-400 hover:text-merak-400 rounded hover:bg-surface-3">
            PDF
          </button>
          <button onClick={() => handleExport('png')} className="px-2 py-1 text-2xs text-gray-400 hover:text-merak-400 rounded hover:bg-surface-3">
            PNG
          </button>
        </div>
      </div>

      {/* Draw.io iframe */}
      <div className="relative min-h-0 flex-1">
        {!loaded && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-0 z-10">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-merak-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
              <p className="text-xs text-gray-500">Loading Draw.io editor...</p>
            </div>
          </div>
        )}
        <iframe
          ref={iframeRef}
          src={drawioUrl.toString()}
          className="h-full w-full border-0"
          sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        />
      </div>
    </div>
  )
}


/**
 * Draw.io 只读预览（用于展示 Agent 生成的图）
 */
export function DrawioPreview({ xml }: { xml: string }) {
  const containerRef = useRef<HTMLDivElement>(null)

  if (!xml) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-gray-500">
        No diagram to display
      </div>
    )
  }

  // 将 XML 转为 data URL 在 iframe 中渲染
  const viewerUrl = `https://viewer.diagrams.net/?highlight=0000ff&nav=1#R${encodeURIComponent(xml)}`

  return (
    <div ref={containerRef} className="h-full">
      <iframe
        src={viewerUrl}
        className="h-full w-full border-0"
        sandbox="allow-scripts allow-same-origin"
      />
    </div>
  )
}
