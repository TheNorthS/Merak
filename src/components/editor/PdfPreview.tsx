import { useState, type ReactNode } from 'react'
import {
  ExternalLink,
  FileText,
  Maximize2,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useArtifactUrl } from '../../services/useArtifactUrl'
import { openArtifact } from '../../services/openArtifact'

export function PdfPreview({ pdfPath }: { pdfPath: string }) {
  const [zoom, setZoom] = useState<number | null>(null)
  const pdfUrl = useArtifactUrl(pdfPath)
  const pdfSrc = pdfUrl + '#zoom=' + (zoom === null ? 'page-width' : String(zoom))
  const fileName = pdfPath.split(/[/\\]/).pop() || 'PDF'

  const changeZoom = (next: number) => {
    setZoom(Math.min(300, Math.max(25, next)))
  }

  return (
    <TooltipProvider delayDuration={250}>
      <div className="flex h-full min-h-0 flex-col bg-background">
        <div className="flex h-9 shrink-0 items-center gap-2 overflow-x-auto border-b border-border bg-card px-3">
          <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <FileText size={13} className="shrink-0" />
            <span className="truncate">{fileName}</span>
          </span>
          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            <PdfButton label="Zoom out" onClick={() => changeZoom((zoom ?? 100) - 25)}>
              <ZoomOut size={14} />
            </PdfButton>
            <span className="w-12 text-center text-2xs tabular-nums text-muted-foreground">
              {zoom === null ? 'Fit' : String(zoom) + '%'}
            </span>
            <PdfButton label="Zoom in" onClick={() => changeZoom((zoom ?? 100) + 25)}>
              <ZoomIn size={14} />
            </PdfButton>
            <PdfButton label="Actual size" onClick={() => setZoom(100)}>
              <RotateCcw size={14} />
            </PdfButton>
            <PdfButton label="Fit page width" onClick={() => setZoom(null)}>
              <Maximize2 size={14} />
            </PdfButton>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" disabled={!pdfUrl} aria-label="Open PDF"
                  onClick={() => openArtifact(pdfPath, pdfUrl)}>
                    <ExternalLink size={14} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Open PDF</TooltipContent>
            </Tooltip>
          </div>
        </div>
        <div className="min-h-0 flex-1">
          {pdfUrl && <iframe
            key={pdfSrc}
            src={pdfSrc}
            className="h-full w-full border-0"
            title={'PDF preview: ' + fileName}
          />}
        </div>
      </div>
    </TooltipProvider>
  )
}

function PdfButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
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
