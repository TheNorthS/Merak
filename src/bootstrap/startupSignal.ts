/** One document owns one startup result; an error can never be followed by ready. */
import { RENDERER_STARTUP_ERROR_LIMIT, RENDERER_STARTUP_QUERY, type RendererStartupNotice } from '@shared/renderer-startup'

export interface StartupSignal {
  ready(): void
  error(error: unknown): void
}

export function startupErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : ''
  const safe = Array.from(message, char => {
    const code = char.charCodeAt(0)
    return code < 32 || code === 127 ? ' ' : char
  }).join('')
  return safe.trim().slice(0, RENDERER_STARTUP_ERROR_LIMIT)
    || '前端启动失败。请查看开发终端日志。'
}

export function createStartupSignal(
  search: string,
  notify?: (notice: RendererStartupNotice) => void,
): StartupSignal {
  const token = new URLSearchParams(search).get(RENDERER_STARTUP_QUERY)
  let state: 'pending' | 'ready' | 'error' = 'pending'
  const send = (status: 'ready' | 'error', message?: string) => {
    if (!token || !notify) return
    notify({ token, status, ...(message ? { message } : {}) })
  }
  return {
    ready() {
      if (state !== 'pending') return
      state = 'ready'
      send('ready')
    },
    error(error) {
      if (state === 'error') return
      state = 'error'
      send('error', startupErrorMessage(error))
    },
  }
}
