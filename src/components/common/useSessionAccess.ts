import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from '../../config'
import { pendingSessionAccess, requestSessionAccess, type SessionAccess } from './sessionAccess'

/** Keep the application mounted after admission while reconnecting fails closed. */
export function useSessionAccess(desktop: boolean) {
  const [access, setAccess] = useState<SessionAccess>(() => pendingSessionAccess(desktop))
  const current = useRef(access)
  const active = useRef<AbortController | null>(null)
  const publish = useCallback((value: SessionAccess) => {
    current.current = value
    setAccess(value)
  }, [])
  const retry = useCallback(async () => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    const timeout = window.setTimeout(() => controller.abort(), 10000)
    const result = await requestSessionAccess(desktop, `${API_BASE}/api/auth/me`, controller.signal)
    window.clearTimeout(timeout)
    if (active.current !== controller) return
    active.current = null
    publish(result)
  }, [desktop, publish])
  useEffect(() => {
    void retry()
    const unsubscribe = window.merakIDE?.backend?.onStatusChange(state => {
      if (state.status === 'ready') void retry()
    })
    const timer = window.setInterval(() => {
      if (current.current.status !== 'ready' && !active.current) void retry()
    }, 3000)
    const expired = () => {
      publish(pendingSessionAccess(desktop))
      if (!active.current) void retry()
    }
    window.addEventListener('merak-ide:authentication-required', expired)
    return () => {
      active.current?.abort(); active.current = null
      clearInterval(timer); unsubscribe?.()
      window.removeEventListener('merak-ide:authentication-required', expired)
    }
  }, [desktop, publish, retry])
  const restart = async () => {
    publish(pendingSessionAccess(desktop))
    try { await window.merakIDE?.backend?.restart(); await retry() }
    catch { publish({ status: 'unavailable', message: '本地服务重启失败，请关闭并重新打开 Merak。' }) }
  }
  return { access, publish, retry, restart }
}
