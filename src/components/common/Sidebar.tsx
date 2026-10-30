import { Files, MessageSquare, Workflow, FileText, Presentation, Settings, BookOpen, Lightbulb, FlaskConical, Image } from 'lucide-react'
import { useWorkspaceStore } from '../../stores/workspace'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'

const sidebarItems = [
  { id: 'files', icon: Files, label: '文件' },
  { id: 'literature', icon: BookOpen, label: '文献' },
  { id: 'ideas', icon: Lightbulb, label: '想法' },
  { id: 'experiments', icon: FlaskConical, label: '实验' },
  { id: 'paper', icon: FileText, label: '论文' },
  { id: 'figures', icon: Image, label: '图表' },
  { id: 'slides', icon: Presentation, label: '演示' },
  { id: 'chat', icon: MessageSquare, label: '对话' },
  { id: 'workflow', icon: Workflow, label: '工作流' },
]

export function Sidebar() {
  const { activeSidebarPanel, setActiveSidebarPanel, setWorkflowFullscreen, chatOpen, setChatOpen } = useWorkspaceStore()

  const handleClick = (id: string) => {
    if (id === 'workflow') {
      setWorkflowFullscreen(true)
      return
    }
    if (id === 'chat') {
      setChatOpen(!chatOpen)
      return
    }
    setActiveSidebarPanel(id)
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div className="w-12 bg-background border-r border-border flex flex-col items-center py-2 shrink-0">
        <div className="flex flex-col items-center gap-1">
          {sidebarItems.map((item) => (
            <Tooltip key={item.id}>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => handleClick(item.id)}
                  className={cn(
                    'w-10 h-10 transition-all duration-150',
                    (item.id === 'chat' ? chatOpen : activeSidebarPanel === item.id)
                      ? 'bg-accent text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )}
                  aria-label={item.label}
                >
                  <item.icon size={20} strokeWidth={1.6} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {item.label}
              </TooltipContent>
            </Tooltip>
          ))}
        </div>

        <div className="mt-auto">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setActiveSidebarPanel('settings')}
                className={cn(
                  'w-10 h-10 transition-all duration-150',
                  activeSidebarPanel === 'settings'
                    ? 'bg-accent text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                )}
                aria-label="Settings"
              >
                <Settings size={20} strokeWidth={1.6} />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              Settings
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </TooltipProvider>
  )
}
