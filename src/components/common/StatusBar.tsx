import { useState, useEffect } from 'react'
import { Server } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { BackendState, BackendStatus } from '../../types/global'

const initialBackendState: BackendState = {
  status: 'stopped',
  port: 8011,
  pid: null,
  error: null,
  restartCount: 0,
}

export function StatusBar() {
  const [backendState, setBackendState] = useState<BackendState>(initialBackendState)

  useEffect(() => {
    if (!window.merakIDE?.backend) return
    let active = true
    let sawEvent = false
    const cleanup = window.merakIDE.backend.onStatusChange((state) => {
      if (!active) return
      sawEvent = true
      setBackendState(state)
    })
    window.merakIDE.backend.getStatus().then((state) => {
      if (active && !sawEvent) setBackendState(state)
    })
    return () => {
      active = false
      cleanup()
    }
  }, [])

  return (
    <div className="h-6 bg-card border-t border-border flex items-center justify-between px-3 text-2xs text-muted-foreground shrink-0 select-none">
      {/* 左侧 */}
      <div className="flex items-center gap-1.5">
        <BackendIndicator state={backendState} />
      </div>

      {/* 右侧 */}
      <div className="flex items-center gap-1.5">
        <Badge variant="default" className="h-4 text-2xs font-medium">Merak v0.1.2</Badge>
      </div>
    </div>
  )
}

function BackendIndicator({ state }: { state: BackendState }) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const config: Record<BackendStatus, { variant: 'success' | 'warning' | 'destructive' | 'secondary'; label: string }> = {
    stopped: { variant: 'secondary', label: 'Backend Off' },
    starting: { variant: 'warning', label: 'Starting...' },
    ready: { variant: 'success', label: 'Backend OK' },
    error: { variant: 'destructive', label: 'Backend Error' },
    restarting: { variant: 'warning', label: 'Restarting...' },
  }
  const { variant, label } = config[state.status]
  const detail = state.error
    ? state.error
    : `Backend status: ${label} (port ${state.port})`

  const openDetails = async () => {
    setDetailsOpen(true)
    try {
      setLogs((await window.merakIDE?.backend?.getLogs?.())?.slice(-120) ?? [])
    } catch (error) {
      setLogs([`无法读取后端日志：${error instanceof Error ? error.message : String(error)}`])
    }
  }

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button" className="flex items-center" onClick={openDetails}>
            <Badge variant={variant} className="h-4 text-2xs gap-1">
              <Server size={10} />
              {label}
            </Badge>
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-sm">{detail}；点击查看启动日志</TooltipContent>
      </Tooltip>
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>后端状态详情</DialogTitle>
            <DialogDescription>{detail}</DialogDescription>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-muted/40 p-3 text-[11px] leading-5 whitespace-pre-wrap break-all">
            {logs.length ? logs.join('\n') : '当前会话尚无后端日志。'}
          </pre>
        </DialogContent>
      </Dialog>
    </>
  )
}
