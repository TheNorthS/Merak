import React, { useState, useEffect, useRef } from 'react'
import { Folder, FolderOpen, FileText, FilePlus, FolderPlus, Pencil, Copy, Trash2 } from 'lucide-react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'

export type DirEntry = { name: string; path: string; is_directory: boolean }

export type ConvCtxMenu = { x: number; y: number; entry: DirEntry | null; parentDir: string }

export function ConventionDirPanel({ dir, title, extensions }: { dir: string; title: string; extensions: string[] }) {
  const projectPath = useWorkspaceStore(s => s.projectPath)
  const [rootEntries, setRootEntries] = useState<DirEntry[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [subEntries, setSubEntries] = useState<Record<string, DirEntry[]>>({})
  const expandedRef = useRef<Set<string>>(expanded)
  expandedRef.current = expanded

  const [ctxMenu, setCtxMenu] = useState<ConvCtxMenu | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [creating, setCreating] = useState<{ type: 'file' | 'folder'; parentDir: string } | null>(null)
  const [createName, setCreateName] = useState('')

  const sep = projectPath?.includes('\\') ? '\\' : '/'
  const rootDir = projectPath ? projectPath + sep + dir : ''

  const fetchDir = (dirPath: string): Promise<DirEntry[]> =>
    fetch(`${API_BASE}/api/files/list?path=${encodeURIComponent(dirPath)}`)
      .then(r => r.ok ? r.json() : []).catch(() => [])

  const filterEntries = (entries: DirEntry[]) =>
    entries.filter(e => e.is_directory || extensions.length === 0 || extensions.some(ext => e.name.endsWith(ext)))

  const loadFiles = async () => {
    if (!projectPath) return
    const entries = await fetchDir(rootDir)
    setRootEntries(filterEntries(entries))
    const updates: Record<string, DirEntry[]> = {}
    for (const d of Array.from(expandedRef.current)) {
      updates[d] = filterEntries(await fetchDir(d))
    }
    if (Object.keys(updates).length > 0) setSubEntries(prev => ({ ...prev, ...updates }))
  }

  useEffect(() => {
    loadFiles()
    const timer = setInterval(loadFiles, 5000)
    const handler = () => loadFiles()
    window.addEventListener('merak-ide:files-changed', handler)
    return () => { clearInterval(timer); window.removeEventListener('merak-ide:files-changed', handler) }
  }, [projectPath, dir])

  // 关闭右键菜单
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('[data-conv-ctx]')) setCtxMenu(null)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [])

  const toggleDir = async (dirPath: string) => {
    const next = new Set(expandedRef.current)
    if (next.has(dirPath)) { next.delete(dirPath) }
    else {
      next.add(dirPath)
      setSubEntries(prev => ({ ...prev, [dirPath]: filterEntries([]) }))
      const entries = await fetchDir(dirPath)
      setSubEntries(prev => ({ ...prev, [dirPath]: filterEntries(entries) }))
    }
    setExpanded(next)
  }

  const openFile = async (filePath: string) => {
    try {
      const name = filePath.split(/[/\\]/).pop() || ''
      const ext = name.split('.').pop()?.toLowerCase() || ''
      const isBinaryPreview = ['pdf', 'png', 'jpg', 'jpeg', 'svg', 'webp', 'gif'].includes(ext)
      let content = ''
      if (!isBinaryPreview) {
        const res = await fetch(API_BASE + '/api/files/read?path=' + encodeURIComponent(filePath))
        if (!res.ok) return
        const data = await res.json()
        content = data.content || ''
      }
      const langMap: Record<string, string> = {
        py: 'python', tex: 'latex', md: 'markdown', json: 'json', excalidraw: 'json',
        yaml: 'yaml', yml: 'yaml', sh: 'shell', js: 'javascript', ts: 'typescript',
        pdf: 'pdf', png: 'image', jpg: 'image', jpeg: 'image', svg: 'image',
        webp: 'image', gif: 'image',
      }
      useWorkspaceStore.getState().openFile({
        path: filePath,
        name,
        language: langMap[ext] || 'plaintext',
        content,
      })
    } catch (error) {
      console.error('Failed to open artifact file', { filePath, error })
    }
  }
  const apiCreate = async (path: string, isDir: boolean) => {
    await fetch(`${API_BASE}/api/files/create`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, is_directory: isDir }),
    })
    loadFiles()
  }

  const apiDelete = async (path: string) => {
    await fetch(`${API_BASE}/api/files/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    useWorkspaceStore.getState().closeFile(path)
    loadFiles()
  }

  const apiRename = async (oldPath: string, newName: string) => {
    if (!newName.trim() || newName === oldPath.split(/[\\/]/).pop()) { setRenaming(null); return }
    const parent = oldPath.substring(0, oldPath.length - oldPath.split(/[\\/]/).pop()!.length)
    await fetch(`${API_BASE}/api/files/rename`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_path: oldPath, new_path: parent + newName }),
    })
    setRenaming(null)
    loadFiles()
  }

  const apiMove = async (src: string, destDir: string) => {
    const srcName = src.split(/[\\/]/).pop()!
    const destPath = destDir + sep + srcName
    if (src === destPath) return
    await fetch(`${API_BASE}/api/files/rename`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_path: src, new_path: destPath }),
    })
    loadFiles()
  }

  const commitCreate = async () => {
    if (!creating || !createName.trim()) { setCreating(null); setCreateName(''); return }
    const path = creating.parentDir + sep + createName.trim()
    setCreating(null); setCreateName('')
    await apiCreate(path, creating.type === 'folder')
  }

  const renderEntries = (entries: DirEntry[], depth: number, parentDirPath: string): React.ReactNode =>
    entries.map(f => {
      const isRenaming = renaming === f.path
      const showCreate = creating?.parentDir === f.path && f.is_directory
      return (
        <div key={f.path}>
          <div
            data-conv-node
            className="flex items-center gap-1 px-2 py-0.5 cursor-pointer hover:bg-muted text-xs select-none group"
            style={{ paddingLeft: `${0.5 + depth * 0.75}rem` }}
            onClick={() => !isRenaming && (f.is_directory ? toggleDir(f.path) : openFile(f.path))}
            onContextMenu={e => { e.preventDefault(); e.stopPropagation(); setCtxMenu({ x: e.clientX, y: e.clientY, entry: f, parentDir: parentDirPath }) }}
            draggable
            onDragStart={e => e.dataTransfer.setData('text/plain', f.path)}
            onDragOver={e => { if (f.is_directory) e.preventDefault() }}
            onDrop={e => { if (f.is_directory) { e.preventDefault(); e.stopPropagation(); const src = e.dataTransfer.getData('text/plain'); if (src) apiMove(src, f.path) } }}
          >
            <span className="mr-1 shrink-0 text-muted-foreground">
              {f.is_directory
                ? (expanded.has(f.path) ? <FolderOpen size={14} /> : <Folder size={14} />)
                : <FileText size={14} />}
            </span>
            {isRenaming ? (
              <Input
                autoFocus
                value={renameValue}
                onChange={e => setRenameValue(e.target.value)}
                onBlur={() => apiRename(f.path, renameValue)}
                onKeyDown={e => { if (e.key === 'Enter') apiRename(f.path, renameValue); if (e.key === 'Escape') setRenaming(null) }}
                className="flex-1 h-5 px-1 bg-background border-ring text-xs text-foreground"
                onClick={e => e.stopPropagation()}
              />
            ) : (
              <span className="truncate flex-1 text-foreground">{f.name}</span>
            )}
          </div>
          {showCreate && (
            <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: `${0.5 + (depth + 1) * 0.75}rem` }}>
              {creating!.type === 'file' ? <FileText size={12} className="text-muted-foreground shrink-0" /> : <Folder size={12} className="text-muted-foreground shrink-0" />}
              <Input
                autoFocus value={createName}
                onChange={e => setCreateName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') commitCreate(); if (e.key === 'Escape') { setCreating(null); setCreateName('') } }}
                onBlur={() => { if (createName.trim()) commitCreate(); else { setCreating(null); setCreateName('') } }}
                placeholder={creating!.type === 'file' ? 'filename.ext' : 'folder-name'}
                className="flex-1 h-5 px-1 bg-background border-ring text-xs text-foreground"
              />
            </div>
          )}
          {f.is_directory && expanded.has(f.path) && subEntries[f.path] && (
            <div>{renderEntries(subEntries[f.path], depth + 1, f.path)}</div>
          )}
        </div>
      )
    })

  if (!projectPath) return <p className="px-3 py-4 text-xs text-muted-foreground">请先打开项目</p>

  return (
    <div
      className="h-full flex flex-col"
      onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, entry: null, parentDir: rootDir }) }}
    >
      {/* 标题栏 + 新建按钮 */}
      <div className="px-3 py-2 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{title}</h3>
          <p className="text-2xs text-muted-foreground mt-0.5">{dir}/</p>
        </div>
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon-sm" onClick={() => setCreating({ type: 'file', parentDir: rootDir })} title="新建文件">
            <FilePlus size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => setCreating({ type: 'folder', parentDir: rootDir })} title="新建文件夹">
            <FolderPlus size={14} />
          </Button>
        </div>
      </div>

      {/* 根目录级新建输入框 */}
      {creating && creating.parentDir === rootDir && (
        <div className="px-3 py-1.5 border-b border-border flex items-center gap-1">
          {creating.type === 'file' ? <FileText size={12} className="text-muted-foreground shrink-0" /> : <Folder size={12} className="text-muted-foreground shrink-0" />}
          <Input
            autoFocus value={createName}
            onChange={e => setCreateName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') commitCreate(); if (e.key === 'Escape') { setCreating(null); setCreateName('') } }}
            onBlur={() => { if (createName.trim()) commitCreate(); else { setCreating(null); setCreateName('') } }}
            placeholder={creating.type === 'file' ? 'filename.ext' : 'folder-name'}
            className="flex-1 h-6 px-2 py-0.5 bg-background border-ring text-xs text-foreground"
          />
        </div>
      )}

      <ScrollArea className="flex-1">
        <div
          className="p-1 min-h-full"
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            if ((e.target as HTMLElement).closest('[data-conv-node]')) return
            const src = e.dataTransfer.getData('text/plain')
            if (src) apiMove(src, rootDir)
          }}
        >
          {rootEntries.length === 0 ? (
            <div className="px-2 py-4 text-center">
              <p className="text-xs text-muted-foreground mb-2">暂无文件</p>
              <Button size="xs" variant="outline" onClick={() => apiCreate(rootDir, true)}>
                创建 {dir}/ 目录
              </Button>
            </div>
          ) : renderEntries(rootEntries, 0, rootDir)}
          <div className="h-16" />
        </div>
      </ScrollArea>

      {/* 右键菜单 */}
      {ctxMenu && (
        <ConvContextMenu
          menu={ctxMenu}
          onNewFile={() => { setCreating({ type: 'file', parentDir: ctxMenu.entry?.is_directory ? ctxMenu.entry.path : ctxMenu.parentDir }); setCtxMenu(null) }}
          onNewFolder={() => { setCreating({ type: 'folder', parentDir: ctxMenu.entry?.is_directory ? ctxMenu.entry.path : ctxMenu.parentDir }); setCtxMenu(null) }}
          onRename={() => { if (ctxMenu.entry) { setRenaming(ctxMenu.entry.path); setRenameValue(ctxMenu.entry.name) }; setCtxMenu(null) }}
          onDelete={() => { if (ctxMenu.entry) apiDelete(ctxMenu.entry.path); setCtxMenu(null) }}
          onCopyPath={() => { if (ctxMenu.entry) navigator.clipboard.writeText(ctxMenu.entry.path); setCtxMenu(null) }}
          onClose={() => setCtxMenu(null)}
        />
      )}
    </div>
  )
}

export function ConvContextMenu({ menu, onNewFile, onNewFolder, onRename, onDelete, onCopyPath, onClose }: {
  menu: ConvCtxMenu
  onNewFile: () => void; onNewFolder: () => void; onRename: () => void
  onDelete: () => void; onCopyPath: () => void; onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: menu.x, y: menu.y })
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!ref.current) return
    const { width, height } = ref.current.getBoundingClientRect()
    setPos({
      x: menu.x + width > window.innerWidth - 8 ? Math.max(8, menu.x - width) : menu.x,
      y: menu.y + height > window.innerHeight - 8 ? Math.max(8, menu.y - height) : menu.y,
    })
  }, [menu.x, menu.y])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const isDir = menu.entry?.is_directory === true
  const hasEntry = menu.entry !== null

  return (
    <div
      ref={ref}
      data-conv-ctx
      className="fixed z-[9999] bg-popover border border-border rounded-md shadow-xl py-1 min-w-[172px]"
      style={{ left: pos.x, top: pos.y }}
      onClick={e => e.stopPropagation()}
    >
      {(isDir || !hasEntry) && (
        <>
          <ConvMenuItem icon={<FilePlus size={13} />} label="新建文件" onClick={onNewFile} />
          <ConvMenuItem icon={<FolderPlus size={13} />} label="新建文件夹" onClick={onNewFolder} />
        </>
      )}
      {hasEntry && (
        <>
          {(isDir || !hasEntry) && <Separator className="mx-2 my-1" />}
          <ConvMenuItem icon={<Pencil size={13} />} label="重命名" onClick={onRename} hint="F2" />
          <ConvMenuItem icon={<Copy size={13} />} label="复制路径" onClick={onCopyPath} />
          <Separator className="mx-2 my-1" />
          {confirmDelete ? (
            <div className="px-3 py-2 flex items-center justify-between gap-2">
              <span className="text-2xs text-destructive truncate max-w-[100px]">删除 "{menu.entry!.name}"?</span>
              <div className="flex gap-1.5 shrink-0">
                <button onClick={onDelete} className="text-2xs font-medium text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded hover:bg-red-500/10">确认</button>
                <button onClick={() => setConfirmDelete(false)} className="text-2xs text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded hover:bg-muted">取消</button>
              </div>
            </div>
          ) : (
            <ConvMenuItem icon={<Trash2 size={13} />} label="删除" onClick={() => setConfirmDelete(true)} danger />
          )}
        </>
      )}
    </div>
  )
}

export function ConvMenuItem({ icon, label, onClick, danger, hint }: {
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
