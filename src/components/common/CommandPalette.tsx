import { Command } from 'cmdk'
import { cn } from '@/lib/utils'
import { useWorkspaceStore } from '../../stores/workspace'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
}

const commands = [
  { id: 'open-folder', label: 'Open Folder...', category: 'File', shortcut: 'Ctrl+O' },
  { id: 'new-file', label: 'New File', category: 'File', shortcut: 'Ctrl+N' },
  { id: 'save-file', label: 'Save File', category: 'File', shortcut: 'Ctrl+S' },
  { id: 'merak-idea-discovery', label: 'Merak: Idea Discovery', category: 'Merak', shortcut: '' },
  { id: 'merak-experiment-bridge', label: 'Merak: Experiment Bridge', category: 'Merak', shortcut: '' },
  { id: 'merak-auto-review', label: 'Merak: Auto Review Loop', category: 'Merak', shortcut: '' },
  { id: 'merak-paper-writing', label: 'Merak: Paper Writing', category: 'Merak', shortcut: '' },
  { id: 'merak-research-pipeline', label: 'Merak: Full Research Pipeline', category: 'Merak', shortcut: '' },
  { id: 'theme-toggle', label: 'Toggle Dark/Light Theme', category: 'Preferences', shortcut: '' },
]

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const { setProjectPath } = useWorkspaceStore()

  if (!open) return null

  const handleSelect = async (commandId: string) => {
    onClose()
    switch (commandId) {
      case 'open-folder': {
        const path = await window.merakIDE?.fs.openFolder()
        if (path) setProjectPath(path)
        break
      }
      case 'theme-toggle':
        useWorkspaceStore.getState().toggleTheme()
        break
      default:
        console.log('Command:', commandId)
    }
  }

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/50 z-[9998]" onClick={onClose} />

      {/* Command palette */}
      <div className="fixed top-[20%] left-1/2 -translate-x-1/2 w-[560px] z-[9999]">
        <Command
          className={cn(
            'bg-surface-1 border border-border rounded-xl shadow-2xl overflow-hidden',
          )}
          loop
        >
          <Command.Input
            placeholder="Type a command or search..."
            className={cn(
              'w-full px-4 py-3 bg-transparent text-sm text-gray-200',
              'placeholder-gray-500 border-b border-border-subtle outline-none',
            )}
            autoFocus
          />
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="px-4 py-8 text-center text-sm text-gray-500">
              No results found.
            </Command.Empty>

            {['File', 'Merak', 'Preferences'].map((category) => {
              const categoryCommands = commands.filter((c) => c.category === category)
              if (categoryCommands.length === 0) return null
              return (
                <Command.Group key={category} heading={category} className="mb-1">
                  <div className="px-2 py-1 text-2xs font-semibold text-gray-500 uppercase tracking-wider">
                    {category}
                  </div>
                  {categoryCommands.map((cmd) => (
                    <Command.Item
                      key={cmd.id}
                      value={cmd.label}
                      onSelect={() => handleSelect(cmd.id)}
                      className={cn(
                        'px-3 py-2 rounded-lg text-sm text-gray-300 cursor-pointer',
                        'flex items-center justify-between',
                        'data-[selected=true]:bg-surface-3 data-[selected=true]:text-white',
                        'transition-colors',
                      )}
                    >
                      <span>{cmd.label}</span>
                      {cmd.shortcut && (
                        <kbd className="text-2xs text-gray-500 font-mono bg-surface-2 px-1.5 py-0.5 rounded">
                          {cmd.shortcut}
                        </kbd>
                      )}
                    </Command.Item>
                  ))}
                </Command.Group>
              )
            })}
          </Command.List>
        </Command>
      </div>
    </>
  )
}
