import { useEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import {
  ExternalLink,
  Fullscreen,
  Image as ImageIcon,
  Maximize2,
  Minimize2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { API_BASE } from '../../config'
import { openArtifact } from '../../services/openArtifact'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface ImagePreviewProps {
  imagePath: string
}

type Pan = { x: number; y: number }
type DragState = { pointerId: number; startX: number; startY: number; originX: number; originY: number }

const clampZoom = (value: number) => Math.min(6, Math.max(0.25, value))

export function ImagePreview({ imagePath }: ImagePreviewProps) {
  const [zoom, setZoom] = useState(1)
  const [fit, setFit] = useState(true)
  const [failed, setFailed] = useState(false)
  const [pan, setPan] = useState<Pan>({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const imageUrl = useMemo(
    () => API_BASE + '/api/files/read-binary?path=' + encodeURIComponent(imagePath),
    [imagePath],
  )
  const fileName = imagePath.split(/[/\\]/).pop() || 'Figure'

  useEffect(() => {
    setZoom(1)
    setFit(true)
    setFailed(false)
    setPan({ x: 0, y: 0 })
    dragRef.current = null
    setIsPanning(false)
  }, [imagePath])

  useEffect(() => {
    if (!isFullscreen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isFullscreen])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const handleWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return
      event.preventDefault()
      event.stopPropagation()
      setFit(false)
      setZoom(current => clampZoom(current * Math.exp(-event.deltaY * 0.002)))
    }
    viewport.addEventListener('wheel', handleWheel, { passive: false, capture: true })
    return () => viewport.removeEventListener('wheel', handleWheel, { capture: true })
  }, [imagePath])

  const changeZoom = (next: number) => {
    setFit(false)
    setZoom(clampZoom(next))
  }

  const fitToWindow = () => {
    setFit(true)
    setPan({ x: 0, y: 0 })
  }

  const actualSize = () => {
    setFit(false)
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  const toggleFullscreen = () => {
    setIsFullscreen(current => !current)
  }

  const startPan = (event: PointerEvent<HTMLDivElement>) => {
    if (fit || event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: pan.x,
      originY: pan.y,
    }
    setIsPanning(true)
  }

  const movePan = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    setPan({
      x: drag.originX + event.clientX - drag.startX,
      y: drag.originY + event.clientY - drag.startY,
    })
  }

  const finishPan = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    dragRef.current = null
    setIsPanning(false)
  }

  return (
    <TooltipProvider delayDuration={250}>
      <div
        ref={rootRef}
        className={
          'titlebar-no-drag flex min-h-0 flex-col bg-background text-foreground ' +
          (isFullscreen ? 'fixed inset-0 z-[200] h-screen w-screen' : 'h-full')
        }
      >
        <div className="flex h-9 shrink-0 items-center gap-2 overflow-x-auto border-b border-border bg-card px-3">
          <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <ImageIcon size={13} className="shrink-0" />
            <span className="truncate">{fileName}</span>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            <PreviewButton label="缩小" onClick={() => changeZoom(zoom - 0.25)}>
              <ZoomOut size={14} />
            </PreviewButton>
            <span className="w-12 text-center text-2xs tabular-nums text-muted-foreground">
              {fit ? '适应' : Math.round(zoom * 100) + '%'}
            </span>
            <PreviewButton label="放大" onClick={() => changeZoom(zoom + 0.25)}>
              <ZoomIn size={14} />
            </PreviewButton>
            <PreviewButton label="原始尺寸" onClick={actualSize}>
              <RotateCcw size={14} />
            </PreviewButton>
            <PreviewButton label="适应窗口" onClick={fitToWindow}>
              <Maximize2 size={14} />
            </PreviewButton>
            <PreviewButton label={isFullscreen ? '退出全屏' : '全屏预览'} onClick={toggleFullscreen}>
              {isFullscreen ? <Minimize2 size={14} /> : <Fullscreen size={14} />}
            </PreviewButton>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" asChild>
                  <a href={imageUrl} onClick={event => { event.preventDefault(); openArtifact(imagePath, imageUrl) }} aria-label="在新窗口打开图片">
                    <ExternalLink size={14} />
                  </a>
                </Button>
              </TooltipTrigger>
              <TooltipContent>在新窗口打开</TooltipContent>
            </Tooltip>
          </div>
        </div>

        <div
          ref={viewportRef}
          className={
            'relative min-h-0 flex-1 overflow-hidden bg-muted/20 ' +
            (fit ? 'cursor-default' : isPanning ? 'cursor-grabbing' : 'cursor-grab')
          }
          style={{ touchAction: 'none' }}
          onPointerDown={startPan}
          onPointerMove={movePan}
          onPointerUp={finishPan}
          onPointerCancel={finishPan}
          onDoubleClick={() => fit ? actualSize() : fitToWindow()}

        >
          {failed ? (
            <div className="flex h-full items-center justify-center text-sm text-destructive">
              无法加载图片。
            </div>
          ) : fit ? (
            <div className="flex h-full min-h-[160px] items-center justify-center p-4">
              <img
                src={imageUrl}
                alt={fileName}
                draggable={false}
                onError={() => setFailed(true)}
                className="max-h-full max-w-full select-none object-contain"
              />
            </div>
          ) : (
            <img
              src={imageUrl}
              alt={fileName}
              draggable={false}
              onError={() => setFailed(true)}
              className="pointer-events-none absolute left-1/2 top-1/2 max-w-none select-none will-change-transform"
              style={{
                transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                transformOrigin: 'center center',
              }}
            />
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}

function PreviewButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void | Promise<void>
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" onClick={onClick} aria-label={label}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
