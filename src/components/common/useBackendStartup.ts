import { useEffect, useState } from 'react'
import type { BackendState } from '../../types/global'

export function useBackendStartup() {
  const [state, setState] = useState<BackendState | null>(null)
  useEffect(() => {
    const backend = window.merakIDE?.backend
    if (!backend?.getStatus || !backend.onStatusChange) return
    let active = true
    let receivedEvent = false
    const unsubscribe = backend.onStatusChange(value => {
      receivedEvent = true
      if (active) setState(value)
    })
    void backend.getStatus().then(value => {
      if (active && !receivedEvent) setState(value)
    }).catch(() => { /* Session checking still exposes connection failures and retry. */ })
    return () => { active = false; unsubscribe() }
  }, [])
  return state
}
