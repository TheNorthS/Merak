import { useEffect, useState } from 'react'
import { API_BASE } from '../config'

/** Fetch in the authenticated main frame; previews never receive credentials. */
export function useArtifactUrl(path: string) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const abort = new AbortController()
    let objectUrl = ''
    setUrl('')
    void fetch(`${API_BASE}/api/files/read-binary?path=${encodeURIComponent(path)}`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`预览读取失败 (${response.status})`)
        const blob = await response.blob()
        if (abort.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      }).catch(error => {
        if (!abort.signal.aborted) window.dispatchEvent(new CustomEvent('merak-ide:save-warning', { detail: String(error) }))
      })
    return () => { abort.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [path])
  return url
}
