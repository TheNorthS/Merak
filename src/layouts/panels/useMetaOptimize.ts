import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../../config'

export interface SkillMutation {
  id: string
  skill_name: string
  description: string
  diff: string
  status: 'pending' | 'approved' | 'rejected' | 'applied' | 'rolled_back'
}

export function useMetaOptimize(projectPath: string | null) {
  const [mutations, setMutations] = useState<SkillMutation[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const currentProject = useRef(projectPath)
  currentProject.current = projectPath
  const url = `${API_BASE}/api/meta-optimize/mutations`

  useEffect(() => {
    let active = true
    setMutations([])
    setError('')
    const refresh = async () => {
      if (!projectPath) return
      try {
        const response = await fetch(`${url}?project_path=${encodeURIComponent(projectPath)}`)
        if (!response.ok) throw new Error(`读取优化提案失败（HTTP ${response.status}）`)
        const data = await response.json()
        if (active) setMutations(data.mutations || [])
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : '读取优化提案失败')
      }
    }
    void refresh()
    window.addEventListener('merak-ide:meta-optimize-changed', refresh)
    return () => { active = false; window.removeEventListener('merak-ide:meta-optimize-changed', refresh) }
  }, [projectPath, url])

  const handleAction = async (id: string, action: 'approve' | 'reject' | 'rollback') => {
    if (!projectPath || busy) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${url}/${encodeURIComponent(id)}/${action}?project_path=${encodeURIComponent(projectPath)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decided_by: 'human' }),
      })
      const result = await response.json()
      if (!response.ok || result.success !== true) throw new Error(result.error || result.detail || '优化提案操作失败')
      if (currentProject.current === projectPath) window.dispatchEvent(new Event('merak-ide:meta-optimize-changed'))
    } catch (reason) {
      if (currentProject.current === projectPath) setError(reason instanceof Error ? reason.message : '优化提案操作失败')
    } finally { setBusy(false) }
  }
  return { mutations, error, busy, handleAction }
}
