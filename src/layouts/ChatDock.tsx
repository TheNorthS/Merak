import { useEffect, useRef } from 'react'
import { Panel, PanelResizeHandle, type ImperativePanelHandle } from 'react-resizable-panels'
import { ChatPanel } from '../components/chat/ChatPanel'
import { useWorkspaceStore } from '../stores/workspace'

export function ChatDock() {
  const open = useWorkspaceStore(state => state.chatOpen)
  const panel = useRef<ImperativePanelHandle>(null)
  useEffect(() => {
    if (open) panel.current?.expand()
    else panel.current?.collapse()
  }, [open])
  return (
    <>
      <PanelResizeHandle disabled={!open}
        className={open ? 'merak-chat-resize-handle group flex w-2 cursor-col-resize items-center justify-center bg-border/40 transition-colors hover:bg-accent' : 'hidden'}
        title="拖动调整 Chat 宽度">
        <span className="h-10 w-0.5 rounded-full bg-muted-foreground/35 transition-colors group-hover:bg-foreground/70" />
      </PanelResizeHandle>
      <Panel ref={panel} id="chat-panel" order={3} defaultSize={open ? 34 : 0}
        minSize={24} maxSize={62} collapsible collapsedSize={0}>
        <div hidden={!open} className="h-full min-w-0 overflow-hidden border-l border-y border-border bg-card shadow-[-8px_0_24px_rgba(0,0,0,0.12)]">
          <ChatPanel />
        </div>
      </Panel>
    </>
  )
}
