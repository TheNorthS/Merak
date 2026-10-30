import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useWorkspaceStore } from '../../stores/workspace'

export function ChatCloseButton() {
  const closeChat = useWorkspaceStore(state => state.setChatOpen)
  return (
    <Button type="button" variant="ghost" size="icon-sm"
      onClick={() => closeChat(false)} aria-label="关闭对话面板"
      title="关闭对话面板（保留会话）" className="shrink-0 text-muted-foreground hover:text-foreground">
      <X size={15} />
    </Button>
  )
}
