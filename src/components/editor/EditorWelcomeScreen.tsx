import { useState } from 'react'
import { BrandIcon } from '../common/BrandIcon'

import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { Button } from '@/components/ui/button'


function KeyboardShortcut({ keys, label }: { keys: string; label: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-1.5">
      <span>{label}</span>
      <kbd className="font-mono text-2xs bg-muted border border-border px-2 py-0.5 rounded">{keys}</kbd>
    </div>
  )
}

export function EditorWelcomeScreen() {
  const setProjectPath = useWorkspaceStore(state => state.setProjectPath)
  const [showNewForm, setShowNewForm] = useState(false)
  const [newProjectPath, setNewProjectPath] = useState('')
  const [newProjectName, setNewProjectName] = useState('')
  const [error, setError] = useState('')

  const resetForm = () => {
    setShowNewForm(false)
    setNewProjectPath('')
    setNewProjectName('')
    setError('')
  }
  const selectPath = async () => {
    const path = await window.merakIDE?.fs.openFolder()
    if (path) setNewProjectPath(path)
  }
  const openProject = async () => {
    const path = await window.merakIDE?.fs.openFolder()
    if (path) setProjectPath(path)
  }
  const createProject = async () => {
    if (!newProjectPath || !newProjectName.trim()) return
    const separator = newProjectPath.includes('\\') ? '\\' : '/'
    const fullPath = newProjectPath + separator + newProjectName
    setError('')
    const response = await fetch(`${API_BASE}/api/projects/scaffold`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: fullPath, name: newProjectName, venue: 'ICLR', mode: 'create',
      }),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      setError(payload.detail || response.statusText || '创建项目失败')
      return
    }
    setProjectPath(fullPath)
    resetForm()
  }

  return (
    <div className="h-full flex items-center justify-center bg-background">
      <div className="text-center max-w-md">
        <BrandIcon className="block w-16 h-16 mx-auto mb-6" />
        <h1 className="text-2xl font-semibold text-foreground mb-2">Merak</h1>
        <p className="text-sm text-muted-foreground mb-6">智能科研环境</p>
        {showNewForm ? (
          <div className="text-left space-y-3 p-4 rounded-lg border border-border bg-card">
            <h3 className="text-sm font-medium text-foreground">新建研究项目</h3>
            <label className="block text-xs text-muted-foreground">
              项目路径
              <span className="mt-1 flex gap-2">
                <input value={newProjectPath} onChange={event => setNewProjectPath(event.target.value)} placeholder="选择或输入路径" className="flex-1 h-8 px-2 rounded border border-border bg-background text-sm text-foreground" />
                <Button size="sm" variant="outline" onClick={selectPath}>选择</Button>
              </span>
            </label>
            <label className="block text-xs text-muted-foreground">
              项目名称
              <input value={newProjectName} onChange={event => setNewProjectName(event.target.value)} placeholder="项目名称（必填）" className="mt-1 w-full h-8 px-2 rounded border border-border bg-background text-sm text-foreground" />
            </label>
            {error && <p className="text-xs leading-5 text-destructive">{error}</p>}
            <div className="flex gap-2 pt-1">
              <Button size="sm" onClick={createProject} disabled={!newProjectPath || !newProjectName.trim()}>创建项目</Button>
              <Button size="sm" variant="ghost" onClick={resetForm}>取消</Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex justify-center gap-3 mb-8">
              <Button onClick={openProject}>打开文件夹</Button>
              <Button variant="outline" onClick={() => { setError(''); setShowNewForm(true) }}>+ 新建研究项目</Button>
            </div>
            <div className="space-y-1.5 text-xs text-muted-foreground mt-6">
              <KeyboardShortcut keys="Ctrl+Shift+P" label="命令面板" />
              <KeyboardShortcut keys="Ctrl+B" label="切换侧边栏" />
              <KeyboardShortcut keys="Ctrl+S" label="保存文件" />
            </div>
            <div className="mt-6 p-3 rounded-lg bg-card border border-border text-left">
              <p className="text-xs text-foreground font-medium mb-1">快速开始</p>
              <p className="text-xs text-muted-foreground">新建或打开项目，配置工作流，并明确选择是否授权科研执行。</p>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
