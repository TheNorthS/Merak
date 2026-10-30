import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { Sidebar } from '../components/common/Sidebar'
import { FileExplorer } from '../components/files/FileExplorer'
import { CodeEditor } from '../components/editor/CodeEditor'
import { StatusBar } from '../components/common/StatusBar'
import { ChatDock } from './ChatDock'
import { useWorkspaceStore } from '../stores/workspace'
import { ConventionDirPanel } from './panels/directoryPanel'
import { LatexPanel, PptPanel } from './panels/publicationPanels'
import { SettingsPanel } from './panels/SettingsPanel'

export function IDELayout() {
  const { activeSidebarPanel, chatOpen } = useWorkspaceStore()

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Sidebar icon navigation */}
      <Sidebar />

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <PanelGroup direction="horizontal" className="flex-1" id="main-layout">
          {/* Left panel (Files/LaTeX/PPT/Settings) */}
          {activeSidebarPanel && activeSidebarPanel !== 'chat' && (
            <>
              <Panel id="sidebar-panel" order={1} defaultSize={22} minSize={16} maxSize={40}>
                <div className="h-full bg-card border-r border-border overflow-hidden">
                  <SidebarPanel panel={activeSidebarPanel} />
                </div>
              </Panel>
              <PanelResizeHandle className="w-px bg-border-subtle hover:bg-accent transition-colors" />
            </>
          )}

          {/* Editor panel */}
          <Panel id="editor-panel" order={2} defaultSize={chatOpen ? 58 : 78} minSize={25}>
            <CodeEditor />
          </Panel>

          {/* Right Chat panel */}
          <ChatDock />
        </PanelGroup>

        {/* Status bar */}
        <StatusBar />
      </div>
    </div>
  )
}

function SidebarPanel({ panel }: { panel: string }) {
  switch (panel) {
    case 'files':
      return <FileExplorer />
    case 'literature':
      return <ConventionDirPanel dir="literature" title="Literature" extensions={['.md', '.bib', '.pdf']} />
    case 'ideas':
      return <ConventionDirPanel dir="ideas" title="Ideas" extensions={['.md']} />
    case 'experiments':
      return <ConventionDirPanel dir="experiments" title="Experiments" extensions={['.py', '.yaml', '.json', '.sh', '.log']} />
    case 'paper':
      return <LatexPanel />
    case 'figures':
      return <ConventionDirPanel dir="figures" title="Figures" extensions={['.pdf', '.png', '.jpg', '.jpeg', '.svg', '.py', '.tex', '.mmd', '.mermaid', '.drawio', '.dio', '.excalidraw']} />
    case 'slides':
      return <PptPanel />
    case 'settings':
      return <SettingsPanel />
    default:
      return <FileExplorer />
  }
}
