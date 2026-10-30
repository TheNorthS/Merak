/** Accept readiness only from the expected main frame and current navigation. */
import { ipcMain, type IpcMainEvent } from 'electron'
import { randomUUID } from 'node:crypto'
import {
  RENDERER_STARTUP_CHANNEL, RENDERER_STARTUP_QUERY, RENDERER_STARTUP_ERROR_LIMIT,
} from '../shared/renderer-startup'

interface StartupWindow {
  webContents: { mainFrame: { url: string } }
}

export interface RendererStartupAttempt {
  url: string
  ready: Promise<void>
  dispose(): void
}

export class RendererStartupFailure extends Error {
  constructor(message: string) {
    super(`Renderer startup failed: ${message}`)
    this.name = 'RendererStartupFailure'
  }
}

/** Every retry has a fresh nonce; late IPC from an earlier page is ignored. */
export function createRendererStartupAttempt(
  window: StartupWindow, selectedUrl: string, signal: AbortSignal,
): RendererStartupAttempt {
  const token = randomUUID()
  const navigationUrl = new URL(selectedUrl)
  navigationUrl.searchParams.set(RENDERER_STARTUP_QUERY, token)
  let settle: (error?: Error) => void = () => {}
  let settled = false
  const ready = new Promise<void>((resolve, reject) => {
    settle = error => {
      if (settled) return
      settled = true
      cleanup()
      if (error) reject(error)
      else resolve()
    }
  })
  const receive = (event: IpcMainEvent, notice: unknown) => {
    if (event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) return
    if (event.senderFrame?.url !== navigationUrl.href) return
    if (!notice || typeof notice !== 'object') return
    const payload = notice as Record<string, unknown>
    if (payload.token !== token) return
    if (payload.status === 'ready') settle()
    else if (payload.status === 'error') {
      const message = typeof payload.message === 'string' ? payload.message : 'Unknown renderer error'
      settle(new RendererStartupFailure(message.slice(0, RENDERER_STARTUP_ERROR_LIMIT)))
    }
  }
  const cancel = () => {
    const error = new Error('Renderer startup wait cancelled')
    error.name = 'AbortError'
    settle(error)
  }
  const cleanup = () => {
    ipcMain.removeListener(RENDERER_STARTUP_CHANNEL, receive)
    signal.removeEventListener('abort', cancel)
  }
  ipcMain.on(RENDERER_STARTUP_CHANNEL, receive)
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) cancel()
  return { url: navigationUrl.href, ready, dispose: cancel }
}
