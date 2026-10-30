import { useEffect, useState } from 'react'
import { useWorkspaceStore } from '../../stores/workspace'

export function FileSaveNotice() {
  const [message, setMessage] = useState('')
  useEffect(() => {
    const notice = (event: Event) => setMessage(String((event as CustomEvent<unknown>).detail))
    const protect = (event: BeforeUnloadEvent) => {
      if (!useWorkspaceStore.getState().openFiles.some(file => file.isDirty)) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('merak-ide:save-warning', notice)
    window.addEventListener('beforeunload', protect)
    return () => {
      window.removeEventListener('merak-ide:save-warning', notice)
      window.removeEventListener('beforeunload', protect)
    }
  }, [])
  return message ? <div role="alert" className="px-4 py-2 text-sm bg-destructive/10 text-destructive">
    {message}<button className="ml-4 underline" onClick={() => setMessage('')}>关闭提示</button>
  </div> : null
}
