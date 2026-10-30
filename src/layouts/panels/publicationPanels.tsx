import { useState, useEffect } from 'react'
import { Folder, FileText } from 'lucide-react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'

export function LatexPanel() {
  const projectPath = useWorkspaceStore(s => s.projectPath)
  const [files, setFiles] = useState<Array<{ name: string; path: string; is_directory: boolean }>>([])
  const [compiling, setCompiling] = useState(false)
  const [compileResult, setCompileResult] = useState<{ success: boolean; message: string; pdfPath?: string } | null>(null)

  const loadFiles = () => {
    if (!projectPath) return
    const sep = projectPath.includes('\\') ? '\\' : '/'
    const paperDir = projectPath + sep + 'paper'
    fetch(`${API_BASE}/api/files/list?path=${encodeURIComponent(paperDir)}`)
      .then(r => r.ok ? r.json() : [])
      .then(entries => setFiles(entries || []))
      .catch(() => setFiles([]))
  }

  useEffect(() => {
    loadFiles()
    const timer = setInterval(loadFiles, 5000)
    return () => clearInterval(timer)
  }, [projectPath])

  const handleCompile = async (texPath: string) => {
    setCompiling(true)
    setCompileResult(null)
    try {
      const sep = texPath.includes('/') ? '/' : '\\'
      const lastSep = texPath.lastIndexOf(sep)
      const dir = texPath.substring(0, lastSep)
      const file = texPath.substring(lastSep + 1)
      const res = await fetch(`${API_BASE}/api/files/latex-compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_dir: dir, main_tex: file }),
      })
      const data = await res.json()
      if (data.success) {
        setCompileResult({ success: true, message: `${data.pages} pages compiled`, pdfPath: data.pdf })
      } else {
        setCompileResult({ success: false, message: data.error })
      }
    } catch (err: any) {
      setCompileResult({ success: false, message: err.message })
    }
    setCompiling(false)
  }

  const openTexFile = async (filePath: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/files/read?path=${encodeURIComponent(filePath)}`)
      if (!res.ok) return
      const data = await res.json()
      const name = filePath.split(/[\\/]/).pop() || ''
      useWorkspaceStore.getState().openFile({ path: filePath, name, language: 'latex', content: data.content || '' })
    } catch (error) {
      console.error('Failed to open TeX source', { filePath, error })
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">论文 (paper/)</h3>
      </div>
      {!projectPath ? (
        <p className="px-3 py-4 text-2xs text-muted-foreground">请先打开项目</p>
      ) : files.length === 0 ? (
        <div className="px-3 py-4 text-center">
          <p className="text-xs text-muted-foreground mb-2">paper/ 目录为空或不存在</p>
          <Button size="xs" variant="outline" onClick={async () => {
            const sep = projectPath.includes('\\') ? '\\' : '/'
            await fetch(`${API_BASE}/api/files/create`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: projectPath + sep + 'paper', is_directory: true }),
            })
            const paperDir = projectPath + sep + 'paper'
            fetch(`${API_BASE}/api/files/list?path=${encodeURIComponent(paperDir)}`)
              .then(r => r.ok ? r.json() : []).then(setFiles)
          }}>创建 paper/ 目录</Button>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="py-1">
            {files.map(f => (
              <div key={f.path} className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted cursor-pointer group">
                <span className="text-muted-foreground shrink-0">{f.is_directory ? <Folder size={14} /> : <FileText size={14} />}</span>
                <span className="flex-1 text-xs text-foreground truncate" onClick={() => !f.is_directory && openTexFile(f.path)}>{f.name}</span>
                {!f.is_directory && f.name.endsWith('.tex') && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleCompile(f.path)}
                    disabled={compiling}
                    className="opacity-0 group-hover:opacity-100 h-5 px-1.5 text-2xs"
                  >
                    编译
                  </Button>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
      {compileResult && (
        <div className={cn('px-3 py-2 border-t border-border text-2xs', compileResult.success ? 'text-green-400' : 'text-red-400')}>
          <p>{compileResult.message}</p>
          {compileResult.pdfPath && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                // 在编辑器中打开 PDF 预览
                useWorkspaceStore.getState().openFile({ path: compileResult.pdfPath!, name: compileResult.pdfPath!.split(/[\\/]/).pop() || 'output.pdf', language: 'pdf', content: '' })
              }}
              className="mt-1 h-5 px-2 text-2xs"
            >
              打开 PDF
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

export function PptPanel() {
  const projectPath = useWorkspaceStore(s => s.projectPath)
  const [files, setFiles] = useState<Array<{ name: string; path: string; is_directory: boolean }>>([])

  const loadFiles = () => {
    if (!projectPath) return
    const sep = projectPath.includes('\\') ? '\\' : '/'
    const slidesDir = projectPath + sep + 'slides'
    fetch(`${API_BASE}/api/files/list?path=${encodeURIComponent(slidesDir)}`)
      .then(r => r.ok ? r.json() : [])
      .then(entries => setFiles(entries || []))
      .catch(() => setFiles([]))
  }

  useEffect(() => {
    loadFiles()
    const timer = setInterval(loadFiles, 5000)
    return () => clearInterval(timer)
  }, [projectPath])

  const openFile = async (filePath: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/files/read?path=${encodeURIComponent(filePath)}`)
      if (!res.ok) return
      const data = await res.json()
      const name = filePath.split(/[\\/]/).pop() || ''
      useWorkspaceStore.getState().openFile({ path: filePath, name, language: 'latex', content: data.content || '' })
    } catch (error) {
      console.error('Failed to open slide source', { filePath, error })
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">演示 (slides/)</h3>
      </div>
      {!projectPath ? (
        <p className="px-3 py-4 text-2xs text-muted-foreground">请先打开项目</p>
      ) : files.length === 0 ? (
        <div className="px-3 py-4 text-center">
          <p className="text-xs text-muted-foreground mb-2">slides/ 目录为空或不存在</p>
          <Button size="xs" variant="outline" onClick={async () => {
            const sep = projectPath.includes('\\') ? '\\' : '/'
            await fetch(`${API_BASE}/api/files/create`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: projectPath + sep + 'slides', is_directory: true }),
            })
            const slidesDir = projectPath + sep + 'slides'
            fetch(`${API_BASE}/api/files/list?path=${encodeURIComponent(slidesDir)}`)
              .then(r => r.ok ? r.json() : []).then(setFiles)
          }}>创建 slides/ 目录</Button>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="py-1">
            {files.map(f => (
              <div key={f.path} className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted cursor-pointer" onClick={() => !f.is_directory && openFile(f.path)}>
                <span className="text-muted-foreground shrink-0">{f.is_directory ? <Folder size={14} /> : <FileText size={14} />}</span>
                <span className="flex-1 text-xs text-foreground truncate">{f.name}</span>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}
