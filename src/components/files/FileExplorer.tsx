import React, { useState, useEffect, useRef } from 'react'
import { ChevronRight, ChevronDown, FilePlus, FolderPlus, RefreshCw, Folder, FolderOpen, FileText, Pencil, Copy, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'

interface FileEntry {
  name: string
  path: string
  isDirectory: boolean
  size: number
  modified: number
}

interface ContextMenu {
  x: number
  y: number
  entry: FileEntry | null
  parentDir: string
}

export function FileExplorer() {
  const { projectPath, setProjectPath } = useWorkspaceStore()
  const [files, setFiles] = useState<FileEntry[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [children, setChildren] = useState<Record<string, FileEntry[]>>({})
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState<{ type: 'file' | 'folder'; parentDir: string } | null>(null)
  const [createName, setCreateName] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  // 通过后端 API 加载目录（不依赖 Electron IPC）
  const loadDir = async (dir: string): Promise<FileEntry[]> => {
    try {
      // 优先用 Electron IPC
      if (window.merakIDE?.fs?.readDir) {
        return await window.merakIDE.fs.readDir(dir) || []
      }
      // fallback: HTTP API
      const res = await fetch(`${API_BASE}/api/files/list?path=${encodeURIComponent(dir)}`)
      if (!res.ok) return []
      const data = await res.json()
      return data.map((e: any) => ({ name: e.name, path: e.path, isDirectory: e.is_directory, size: e.size, modified: e.modified }))
    } catch {
      return []
    }
  }

  // 文件操作 — 优先 IPC，fallback HTTP
  const fsCreate = async (path: string, isDir: boolean): Promise<boolean> => {
    try {
      if (window.merakIDE?.fs) {
        return isDir ? await window.merakIDE.fs.createDir(path) : await window.merakIDE.fs.createFile(path)
      }
      const res = await fetch(`${API_BASE}/api/files/create`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, is_directory: isDir }),
      })
      return res.ok
    } catch { return false }
  }

  const fsDelete = async (path: string): Promise<boolean> => {
    try {
      if (window.merakIDE?.fs?.delete) {
        return await window.merakIDE.fs.delete(path)
      }
      const res = await fetch(`${API_BASE}/api/files/delete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      })
      return res.ok
    } catch { return false }
  }

  const fsRename = async (oldPath: string, newPath: string): Promise<boolean> => {
    try {
      if (window.merakIDE?.fs?.rename) {
        return await window.merakIDE.fs.rename(oldPath, newPath)
      }
      const res = await fetch(`${API_BASE}/api/files/rename`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
      })
      return res.ok
    } catch { return false }
  }

  useEffect(() => {
    if (projectPath) loadDir(projectPath).then(setFiles)
  }, [projectPath])

  // 监听文件变更事件（工作流生成文件时立即刷新）
  useEffect(() => {
    const handler = () => refresh()
    window.addEventListener('merak-ide:files-changed', handler)
    return () => window.removeEventListener('merak-ide:files-changed', handler)
  }, [projectPath])

  // 点击空白处关闭右键菜单（用 mousedown，避免和菜单项 click 冲突）
  useEffect(() => {
    const close = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.closest('[data-context-menu]')) return
      setContextMenu(null)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [])

  const refresh = async () => {
    if (!projectPath) return
    setFiles(await loadDir(projectPath))
    // 刷新已展开的子目录
    const updated: Record<string, FileEntry[]> = {}
    for (const dir of expanded) {
      updated[dir] = await loadDir(dir)
    }
    setChildren(prev => ({ ...prev, ...updated }))
  }

  const toggleExpand = async (entry: FileEntry) => {
    const next = new Set(expanded)
    if (next.has(entry.path)) {
      next.delete(entry.path)
    } else {
      next.add(entry.path)
      const sub = await loadDir(entry.path)
      setChildren(prev => ({ ...prev, [entry.path]: sub }))
    }
    setExpanded(next)
  }

  const openFile = async (entry: FileEntry) => {
    try {
      const ext = entry.name.split('.').pop()?.toLowerCase() || ''
      const isBinaryPreview = ['pdf', 'png', 'jpg', 'jpeg', 'svg', 'webp', 'gif'].includes(ext)
      let content = ''

      if (!isBinaryPreview) {
        if (window.merakIDE?.fs?.readFile) {
          content = await window.merakIDE.fs.readFile(entry.path) || ''
        } else {
          const res = await fetch(API_BASE + '/api/files/read?path=' + encodeURIComponent(entry.path))
          if (!res.ok) return
          const data = await res.json()
          content = data.content || ''
        }
      }

      const langMap: Record<string, string> = {
        py: 'python', ts: 'typescript', tsx: 'typescriptreact', js: 'javascript',
        json: 'json', excalidraw: 'json', md: 'markdown', tex: 'latex', yaml: 'yaml', yml: 'yaml',
        css: 'css', html: 'html', bib: 'bibtex', sh: 'shell', toml: 'toml',
        pdf: 'pdf', png: 'image', jpg: 'image', jpeg: 'image', svg: 'image',
        webp: 'image', gif: 'image', pptx: 'pptx',
      }
      useWorkspaceStore.getState().openFile({
        path: entry.path,
        name: entry.name,
        language: langMap[ext] || 'plaintext',
        content,
      })
    } catch (err) {
      console.error('[FileExplorer] openFile failed:', err)
    }
  }
  // ==================== 文件操作 ====================

  const handleNewFile = async (parentDir: string) => {
    console.log('[FileExplorer] handleNewFile in:', parentDir)
    const next = new Set(expanded)
    next.add(parentDir)
    setExpanded(next)
    if (parentDir !== projectPath) {
      const sub = await loadDir(parentDir)
      setChildren(prev => ({ ...prev, [parentDir]: sub }))
    }
    setCreating({ type: 'file', parentDir })
    setCreateName('')
  }

  const handleNewFolder = async (parentDir: string) => {
    console.log('[FileExplorer] handleNewFolder in:', parentDir)
    const next = new Set(expanded)
    next.add(parentDir)
    setExpanded(next)
    if (parentDir !== projectPath) {
      const sub = await loadDir(parentDir)
      setChildren(prev => ({ ...prev, [parentDir]: sub }))
    }
    setCreating({ type: 'folder', parentDir })
    setCreateName('')
  }

  const handleCreateCommit = async () => {
    if (!creating || !createName.trim()) {
      setCreating(null)
      setCreateName('')
      return
    }
    const name = createName.trim()
    const parentDir = creating.parentDir
    const type = creating.type
    const sep = parentDir.includes('/') ? '/' : '\\'
    const fullPath = parentDir + sep + name

    console.log(`[FileExplorer] Creating ${type}: ${fullPath}`)

    setCreating(null)
    setCreateName('')

    try {
      const ok = await fsCreate(fullPath, type === 'folder')
      console.log(`[FileExplorer] Create result: ${ok}`)

      if (parentDir === projectPath) {
        setFiles(await loadDir(projectPath!))
      } else {
        const sub = await loadDir(parentDir)
        setChildren(prev => ({ ...prev, [parentDir]: sub }))
        setExpanded(prev => new Set([...prev, parentDir]))
      }
    } catch (err) {
      console.error('[FileExplorer] Create failed:', err)
    }
  }

  const handleDelete = async (entry: FileEntry) => {
    try {
      const ok = await fsDelete(entry.path)
      console.log(`[FileExplorer] Delete result: ${ok}`)

      if (ok) {
        useWorkspaceStore.getState().closeFile(entry.path)

        const sep = entry.path.includes('/') ? '/' : '\\'
        const parentDir = entry.path.substring(0, entry.path.lastIndexOf(sep))
        if (parentDir === projectPath) {
          setFiles(await loadDir(projectPath!))
        } else {
          const sub = await loadDir(parentDir)
          setChildren(prev => ({ ...prev, [parentDir]: sub }))
        }
      } else {
        console.error('[FileExplorer] Delete returned false — permission issue?')
      }
    } catch (err) {
      console.error('[FileExplorer] Delete failed:', err)
    }
  }

  const handleRenameStart = (entry: FileEntry) => {
    setRenaming(entry.path)
    setRenameValue(entry.name)
  }

  const handleRenameCancel = () => setRenaming(null)

  const handleRenameCommit = async (entry: FileEntry) => {
    if (!renameValue.trim() || renameValue === entry.name) {
      setRenaming(null)
      return
    }
    const parentDir = entry.path.substring(0, entry.path.length - entry.name.length)
    const newPath = parentDir + renameValue
    await fsRename(entry.path, newPath)
    setRenaming(null)
    refresh()
  }

  const handleContextMenu = (e: React.MouseEvent, entry: FileEntry | null, parentDir: string) => {
    e.preventDefault()
    e.stopPropagation()
    console.log('[FileExplorer] contextMenu on:', entry?.name || 'background', 'parentDir:', parentDir)
    setContextMenu({ x: e.clientX, y: e.clientY, entry, parentDir })
  }

  // 过滤搜索
  const filterFiles = (entries: FileEntry[]) => {
    if (!search.trim()) return entries
    const q = search.toLowerCase()
    return entries.filter(e => e.name.toLowerCase().includes(q))
  }

  // ==================== 无项目状态 ====================

  const [showNewForm, setShowNewForm] = useState(false)
  const [newProjPath, setNewProjPath] = useState('')
  const [newProjName, setNewProjName] = useState('')
  const [projectCreationError, setProjectCreationError] = useState('')

  if (!projectPath) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-4">
        <Folder size={32} className="text-muted-foreground mb-3" />
        <p className="text-xs text-muted-foreground mb-3 text-center">打开项目文件夹开始使用</p>

        {showNewForm ? (
          <div className="w-full space-y-2 p-3 border border-border rounded-lg bg-card">
            <div>
              <label className="text-2xs text-muted-foreground block mb-1">项目路径</label>
              <div className="flex gap-1">
                <Input value={newProjPath} onChange={e => setNewProjPath(e.target.value)} placeholder="选择路径" className="flex-1 h-7 text-xs" />
                <Button size="xs" variant="outline" onClick={async () => { const p = await window.merakIDE?.fs.openFolder(); if (p) setNewProjPath(p) }}>选择</Button>
              </div>
            </div>
            <div>
              <label className="text-2xs text-muted-foreground block mb-1">项目名称</label>
              <Input value={newProjName} onChange={e => setNewProjName(e.target.value)} placeholder="项目名称（必填）" className="h-7 text-xs" />
            </div>
            {projectCreationError && (
              <p className="text-2xs leading-4 text-destructive">{projectCreationError}</p>
            )}
            <div className="flex gap-1">
              <Button size="xs" disabled={!newProjPath || !newProjName.trim()} onClick={async () => {
                const sep = newProjPath.includes('\\') ? '\\' : '/'
                const fullPath = newProjPath + sep + newProjName.trim()
                setProjectCreationError('')
                const res = await fetch(`${API_BASE}/api/projects/scaffold`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ path: fullPath, name: newProjName.trim(), venue: 'ICLR', mode: 'create' }),
                })
                const payload = await res.json().catch(() => ({}))
                if (!res.ok) {
                  setProjectCreationError(payload.detail || res.statusText || '创建项目失败')
                  return
                }
                setProjectPath(fullPath)
                setNewProjPath('')
                setNewProjName('')
                setProjectCreationError('')
                setShowNewForm(false)
              }}>创建</Button>
              <Button size="xs" variant="ghost" onClick={() => {
                setShowNewForm(false)
                setNewProjPath('')
                setNewProjName('')
                setProjectCreationError('')
              }}>取消</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <Button
              variant="default"
              size="sm"
              onClick={async () => {
                const path = await window.merakIDE?.fs.openFolder()
                if (path) setProjectPath(path)
              }}
            >
              打开文件夹
            </Button>
            <Button variant="outline" size="sm" onClick={() => {
              setProjectCreationError('')
              setShowNewForm(true)
            }}>
              + 新建研究项目
            </Button>
          </div>
        )}
      </div>
    )
  }

  // ==================== 渲染 ====================

  return (
    <div ref={containerRef} className="h-full flex flex-col" onContextMenu={e => handleContextMenu(e, null, projectPath)}>
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Files</span>
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon-sm" onClick={() => handleNewFile(projectPath)} title="New File">
            <FilePlus size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => handleNewFolder(projectPath)} title="New Folder">
            <FolderPlus size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={refresh} title="Refresh">
            <RefreshCw size={14} />
          </Button>
        </div>
      </div>

      {/* 搜索框 */}
      <div className="px-3 py-1.5 border-b border-border">
        <Input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter files..."
          className="h-7 px-2 py-1 bg-muted text-2xs text-foreground placeholder-gray-600"
        />
      </div>

      {/* 内联新建输入框（根目录层级） */}
      {creating && creating.parentDir === projectPath && (
        <div className="px-3 py-1.5 border-b border-border flex items-center gap-1">
          {creating.type === 'file' ? <FileText size={12} className="text-muted-foreground shrink-0" /> : <Folder size={12} className="text-muted-foreground shrink-0" />}
          <Input
            autoFocus
            value={createName}
            onChange={e => setCreateName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCreateCommit(); if (e.key === 'Escape') { setCreating(null); setCreateName('') } }}
            onBlur={() => { if (createName.trim()) handleCreateCommit(); else { setCreating(null); setCreateName('') } }}
            placeholder={creating.type === 'file' ? 'filename.ext' : 'folder-name'}
            className="flex-1 h-6 px-2 py-0.5 bg-background border-ring text-xs text-foreground"
          />
        </div>
      )}

      {/* 文件树 */}
      <ScrollArea className="flex-1">
        <div
          className="py-1 min-h-full"
          onDragOver={e => e.preventDefault()}
          onDrop={async e => {
            // 只处理拖到空白区域（非 TreeNode 内部的 drop 已在 TreeNode 处理）
            if ((e.target as HTMLElement).closest('[data-tree-node]')) return
            const src = e.dataTransfer.getData('text/plain')
            if (!src) return
            const srcName = src.split(/[\\/]/).pop()!
            const sep = projectPath!.includes('\\') ? '\\' : '/'
            const destPath = projectPath! + sep + srcName
            if (src !== destPath) {
              const res = await fetch(`${API_BASE}/api/files/rename`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ old_path: src, new_path: destPath }),
              })
              if (res.ok) refresh()
            }
          }}
        >
          {filterFiles(files).map(entry => (
            <TreeNode
              key={entry.path}
              entry={entry}
              depth={0}
              expanded={expanded}
              children={children}
              onToggle={toggleExpand}
              onOpen={openFile}
              onContextMenu={handleContextMenu}
              renaming={renaming}
              renameValue={renameValue}
              setRenameValue={setRenameValue}
              onRenameCommit={handleRenameCommit}
              onRenameCancel={handleRenameCancel}
              filterFiles={filterFiles}
              creating={creating}
              createName={createName}
              setCreateName={setCreateName}
              onCreateCommit={handleCreateCommit}
              onCreateCancel={() => setCreating(null)}
              onDropRefresh={refresh}
            />
          ))}
          {/* 拖拽目标：根目录空白区 */}
          <div className="h-16" />
        </div>
      </ScrollArea>

      {/* 右键菜单 */}
      {contextMenu && (
        <ContextMenuPopup
          menu={contextMenu}
          onNewFile={() => { handleNewFile(contextMenu.entry?.isDirectory ? contextMenu.entry.path : contextMenu.parentDir); setContextMenu(null) }}
          onNewFolder={() => { handleNewFolder(contextMenu.entry?.isDirectory ? contextMenu.entry.path : contextMenu.parentDir); setContextMenu(null) }}
          onRename={() => { if (contextMenu.entry) { handleRenameStart(contextMenu.entry); setContextMenu(null) } }}
          onDelete={() => { if (contextMenu.entry) handleDelete(contextMenu.entry).then(() => setContextMenu(null)) }}
          onCopyPath={() => { if (contextMenu.entry) { navigator.clipboard.writeText(contextMenu.entry.path); setContextMenu(null) } }}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  )
}

// ==================== 树节点 ====================

function TreeNode({ entry, depth, expanded, children, onToggle, onOpen, onContextMenu, renaming, renameValue, setRenameValue, onRenameCommit, onRenameCancel, filterFiles, creating, createName, setCreateName, onCreateCommit, onCreateCancel, onDropRefresh }: {
  entry: FileEntry; depth: number; expanded: Set<string>; children: Record<string, FileEntry[]>
  onToggle: (e: FileEntry) => void; onOpen: (e: FileEntry) => void
  onContextMenu: (e: React.MouseEvent, entry: FileEntry, parentDir: string) => void
  renaming: string | null; renameValue: string; setRenameValue: (v: string) => void
  onRenameCommit: (e: FileEntry) => void; onRenameCancel: () => void
  filterFiles: (entries: FileEntry[]) => FileEntry[]
  creating: { type: 'file' | 'folder'; parentDir: string } | null
  createName: string; setCreateName: (v: string) => void
  onCreateCommit: () => void; onCreateCancel: () => void
  onDropRefresh: () => void
}) {
  const isOpen = expanded.has(entry.path)
  const isRenaming = renaming === entry.path
  const parentDir = entry.path.substring(0, entry.path.lastIndexOf(entry.name))
  const showCreateHere = creating && creating.parentDir === entry.path

  return (
    <>
      <div
        data-tree-node
        className={cn(
          'flex items-center gap-1 px-2 py-0.5 cursor-pointer hover:bg-muted text-xs',
          'select-none',
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => entry.isDirectory ? onToggle(entry) : onOpen(entry)}
        onContextMenu={e => onContextMenu(e, entry, parentDir)}
        draggable
        onDragStart={e => e.dataTransfer.setData('text/plain', entry.path)}
        onDragOver={e => { if (entry.isDirectory) e.preventDefault() }}
        onDrop={async e => {
          if (!entry.isDirectory) return
          const src = e.dataTransfer.getData('text/plain')
          if (src && src !== entry.path) {
            const srcName = src.split(/[\\/]/).pop()!
            const destPath = entry.path + (entry.path.includes('/') ? '/' : '\\') + srcName
            const res = await fetch(`${API_BASE}/api/files/rename`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ old_path: src, new_path: destPath }),
            })
            if (res.ok) onDropRefresh()
          }
        }}
      >
        {entry.isDirectory ? (
          <>
            {isOpen ? <ChevronDown size={12} className="text-muted-foreground shrink-0" /> : <ChevronRight size={12} className="text-muted-foreground shrink-0" />}
            {isOpen ? <FolderOpen size={14} className="text-muted-foreground shrink-0" /> : <Folder size={14} className="text-muted-foreground shrink-0" />}
          </>
        ) : (
          <>
            <span className="w-3 shrink-0" />
            <FileIcon name={entry.name} />
          </>
        )}
        {isRenaming ? (
          <Input
            autoFocus
            value={renameValue}
            onChange={e => setRenameValue(e.target.value)}
            onBlur={() => onRenameCommit(entry)}
            onKeyDown={e => { if (e.key === 'Enter') onRenameCommit(entry); if (e.key === 'Escape') onRenameCancel() }}
            className="flex-1 h-5 px-1 bg-background border-ring text-xs text-foreground"
            onClick={e => e.stopPropagation()}
          />
        ) : (
          <span className="text-foreground truncate">{entry.name}</span>
        )}
      </div>
      {/* 新建输入框（显示在目标文件夹内部） */}
      {entry.isDirectory && showCreateHere && (
        <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: `${(depth + 1) * 12 + 8}px` }}>
          {creating!.type === 'file' ? <FileText size={12} className="text-muted-foreground shrink-0" /> : <Folder size={12} className="text-muted-foreground shrink-0" />}
          <Input
            autoFocus
            value={createName}
            onChange={e => setCreateName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onCreateCommit(); if (e.key === 'Escape') onCreateCancel() }}
            onBlur={() => { if (createName.trim()) onCreateCommit(); else onCreateCancel() }}
            placeholder={creating!.type === 'file' ? 'filename.ext' : 'folder-name'}
            className="flex-1 h-5 px-1 bg-background border-ring text-xs text-foreground"
          />
        </div>
      )}
      {entry.isDirectory && isOpen && children[entry.path]?.length > 0 && (
        filterFiles(children[entry.path]).map(child => (
          <TreeNode
            key={child.path}
            entry={child}
            depth={depth + 1}
            expanded={expanded}
            children={children}
            onToggle={onToggle}
            onOpen={onOpen}
            onContextMenu={onContextMenu}
            renaming={renaming}
            renameValue={renameValue}
            setRenameValue={setRenameValue}
            onRenameCommit={onRenameCommit}
            onRenameCancel={onRenameCancel}
            filterFiles={filterFiles}
            creating={creating}
            createName={createName}
            setCreateName={setCreateName}
            onCreateCommit={onCreateCommit}
            onCreateCancel={onCreateCancel}
            onDropRefresh={onDropRefresh}
          />
        ))
      )}
    </>
  )
}

// ==================== 右键菜单 ====================

function ContextMenuPopup({ menu, onNewFile, onNewFolder, onRename, onDelete, onCopyPath, onClose }: {
  menu: ContextMenu
  onNewFile: () => void; onNewFolder: () => void; onRename: () => void
  onDelete: () => void; onCopyPath: () => void; onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: menu.x, y: menu.y })
  const [confirmDelete, setConfirmDelete] = useState(false)

  // 防止菜单超出视口边界
  useEffect(() => {
    if (!ref.current) return
    const { width, height } = ref.current.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    setPos({
      x: menu.x + width > vw - 8 ? Math.max(8, menu.x - width) : menu.x,
      y: menu.y + height > vh - 8 ? Math.max(8, menu.y - height) : menu.y,
    })
  }, [menu.x, menu.y])

  // ESC 关闭菜单
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const isDir = menu.entry?.isDirectory === true
  const hasEntry = menu.entry !== null

  return (
    <div
      ref={ref}
      data-context-menu
      className="fixed z-[9999] bg-popover border border-border rounded-md shadow-xl py-1 min-w-[172px]"
      style={{ left: pos.x, top: pos.y }}
      onClick={e => e.stopPropagation()}
    >
      {/* 文件夹或空白处右键 — 显示新建 */}
      {(isDir || !hasEntry) && (
        <>
          <MenuItem icon={<FilePlus size={13} />} label="新建文件" onClick={onNewFile} />
          <MenuItem icon={<FolderPlus size={13} />} label="新建文件夹" onClick={onNewFolder} />
        </>
      )}

      {/* 有具体条目时显示编辑操作 */}
      {hasEntry && (
        <>
          {isDir && <Separator className="mx-2 my-1" />}
          <MenuItem icon={<Pencil size={13} />} label="重命名" onClick={onRename} hint="F2" />
          <MenuItem icon={<Copy size={13} />} label="复制路径" onClick={onCopyPath} />
          <Separator className="mx-2 my-1" />
          {confirmDelete ? (
            <div className="px-3 py-2 flex items-center justify-between gap-2">
              <span className="text-2xs text-destructive truncate max-w-[100px]">删除 "{menu.entry!.name}"?</span>
              <div className="flex gap-1.5 shrink-0">
                <button
                  onClick={onDelete}
                  className="text-2xs font-medium text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded hover:bg-red-500/10"
                >
                  确认
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="text-2xs text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded hover:bg-muted"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <MenuItem icon={<Trash2 size={13} />} label="删除" onClick={() => setConfirmDelete(true)} danger />
          )}
        </>
      )}
    </div>
  )
}

function MenuItem({ icon, label, onClick, danger, hint }: {
  icon?: React.ReactNode; label: string; onClick: () => void; danger?: boolean; hint?: string
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-accent transition-colors',
        danger ? 'text-destructive hover:bg-destructive/10 hover:text-destructive' : 'text-foreground',
      )}
    >
      {icon && <span className="text-muted-foreground shrink-0">{icon}</span>}
      <span className="flex-1">{label}</span>
      {hint && <span className="text-2xs text-muted-foreground/60 shrink-0">{hint}</span>}
    </button>
  )
}

// ==================== 文件图标 ====================

function FileIcon({ name: _ }: { name: string }) {
  return <FileText size={14} className="text-muted-foreground shrink-0" />
}
