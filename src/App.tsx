import { useState, useEffect } from 'react'
import { BrandIcon } from './components/common/BrandIcon'
import { Folder, Sun, Moon } from 'lucide-react'
import { IDELayout } from './layouts/IDELayout'
import { saveFile } from './services/fileSave'
import { FileSaveNotice } from './components/common/FileSaveNotice'
import { CommandPalette } from './components/common/CommandPalette'
import { WorkflowFullscreen } from './components/workflow/WorkflowFullscreen'
import { useWorkspaceStore } from './stores/workspace'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { applyStoredTheme, applyTheme } from './bootstrap/theme'

export default function App() {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const { workflowFullscreen } = useWorkspaceStore()

  useEffect(() => {
    void useWorkspaceStore.getState().hydrateProjectPath()
  }, [])

  useEffect(() => {
    applyStoredTheme()
    const handler = (e: Event) => {
      const { key, value } = (e as CustomEvent).detail
      if (key === 'theme') applyTheme(value)
    }
    window.addEventListener('merak-ide:settings-changed', handler)
    return () => window.removeEventListener('merak-ide:settings-changed', handler)
  }, [])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey

      // Ctrl+Shift+P: 命令面板
      if (ctrl && e.shiftKey && e.key === 'P') {
        e.preventDefault()
        setCommandPaletteOpen(true)
      }
      if (ctrl && e.key === 'b') {
        e.preventDefault()
        const store = useWorkspaceStore.getState()
        store.setActiveSidebarPanel(store.activeSidebarPanel ? null : 'files')
      }
      if (ctrl && e.key === 's') {
        e.preventDefault()
        const { openFiles, activeFileIndex } = useWorkspaceStore.getState()
        const file = openFiles[activeFileIndex]
        if (file?.isDirty) {
          void saveFile(file.path).catch(error => {
            window.dispatchEvent(new CustomEvent('merak-ide:save-warning', {
              detail: error instanceof Error ? error.message : '保存失败，修改仍未保存。',
            }))
          })
        }
      }
      // Escape: 关闭命令面板
      if (e.key === 'Escape') {
        setCommandPaletteOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <TooltipProvider>
      <div className="h-screen w-screen flex flex-col bg-background text-foreground overflow-hidden">
        {/* 标题栏 */}
        <TitleBar />
        <FileSaveNotice />
        {/* 主布局 */}
        <IDELayout />
        <div className={workflowFullscreen ? '' : 'hidden'}>
          <WorkflowFullscreen />
        </div>
        {/* 命令面板 */}
        <CommandPalette open={commandPaletteOpen} onClose={() => setCommandPaletteOpen(false)} />
      </div>
    </TooltipProvider>
  )
}

function TitleBar() {
  const [theme, setTheme] = useState(() => localStorage.getItem('merak-ide:theme') || 'dark')
  const projectPath = useWorkspaceStore(s => s.projectPath)
  const setProjectPath = useWorkspaceStore(s => s.setProjectPath)

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    localStorage.setItem('merak-ide:theme', next)
    window.dispatchEvent(new CustomEvent('merak-ide:settings-changed', { detail: { key: 'theme', value: next } }))
  }

  const switchProject = async () => {
    const path = await window.merakIDE?.fs.openFolder()
    if (path) setProjectPath(path)
  }

  const closeProject = () => {
    setProjectPath(null)
  }

  const projectName = projectPath ? projectPath.split(/[\\/]/).pop() : '未打开项目'

  return (
    <div className="titlebar-drag h-9 flex items-center justify-between px-4 bg-card border-b border-border select-none shrink-0">
      <div className="flex items-center gap-2 titlebar-no-drag">
        <BrandIcon className="block w-5 h-5" />
        <span className="text-xs font-semibold text-foreground tracking-wide">Merak</span>
        <span className="text-muted-foreground text-xs">—</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={switchProject}
              className="text-xs text-muted-foreground hover:text-foreground truncate max-w-[200px] px-1.5"
            >
              <Folder size={14} className="shrink-0" /> {projectName}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {projectPath || '点击打开项目'}
          </TooltipContent>
        </Tooltip>
        {projectPath && (
          <Button variant="ghost" size="icon-sm" onClick={closeProject} className="text-muted-foreground hover:text-foreground" title="关闭项目">
            <span className="text-xs">✕</span>
          </Button>
        )}
      </div>
      <div className="flex items-center gap-2 titlebar-no-drag">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={toggleTheme}
              aria-label="Toggle theme"
            >
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {theme === 'dark' ? 'Switch to Light' : 'Switch to Dark'}
          </TooltipContent>
        </Tooltip>
      </div>
      <div className="flex items-center gap-0.5 titlebar-no-drag">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => window.merakIDE?.window.minimize()}
          aria-label="Minimize"
        >
          <MinusIcon />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => window.merakIDE?.window.maximize()}
          aria-label="Maximize"
        >
          <SquareIcon />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => window.merakIDE?.window.close()}
          className="hover:bg-red-500/20 hover:text-red-400"
          aria-label="Close"
        >
          <XIcon />
        </Button>
      </div>
    </div>
  )
}

function MinusIcon() {
  return <svg width="10" height="1" viewBox="0 0 10 1" fill="currentColor"><rect width="10" height="1" /></svg>
}

function SquareIcon() {
  return <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.2"><rect x="0.6" y="0.6" width="8.8" height="8.8" /></svg>
}

function XIcon() {
  return <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.4"><line x1="1" y1="1" x2="9" y2="9" /><line x1="9" y1="1" x2="1" y2="9" /></svg>
}
