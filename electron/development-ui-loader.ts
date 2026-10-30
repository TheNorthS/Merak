/** Development-only navigation owns retries; backend lifecycle is independent. */
import { waitForDevServer, type DevServerWaitOptions } from '../scripts/dev-server-readiness.cjs'

export interface DevelopmentWindow {
  isDestroyed(): boolean
  loadURL(url: string): Promise<unknown>
  show(): void
  webContents: { stop(): void }
  once(event: 'closed', listener: () => void): unknown
  removeListener(event: 'closed', listener: () => void): unknown
}

export interface DevelopmentLoadOptions {
  readinessTimeoutMs?: number
  requestTimeoutMs?: number
  navigationTimeoutMs?: number
  retryDelayMs?: number
  waitForServer?: (url: string, options: DevServerWaitOptions) => Promise<void>
  onRetry?: (error: Error) => void
  onWaiting?: (url: string) => void
  startRenderer?: (url: string, signal: AbortSignal) => {
    url: string
    ready: Promise<void>
    dispose(): void
  }
}

function closedError(): Error {
  const error = new Error('Development window was closed')
  error.name = 'AbortError'
  return error
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char] || char)
}

function waitingPage(url: string, reason = ''): string {
  const html = `<html lang="zh-CN"><head><meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
    <title>Merak — 正在连接前端</title><style>
    body{margin:0;background:#1e1e2e;color:#cdd6f4;font:15px system-ui;height:100vh;display:grid;place-items:center}
    header{position:fixed;inset:0 0 auto;height:36px;-webkit-app-region:drag}
    button{float:right;margin:6px 12px;background:none;border:0;color:#cdd6f4;cursor:pointer;-webkit-app-region:no-drag}
    main{max-width:720px;padding:32px;text-align:center}p{line-height:1.6}code{overflow-wrap:anywhere}
    .detail{color:#a6adc8;white-space:pre-wrap;overflow-wrap:anywhere}</style></head>
    <body><header><button onclick="window.merakIDE?.window.close()" aria-label="关闭">关闭</button></header>
    <main><h2>Merak</h2><p>正在等待开发前端：<code>${escapeHtml(url)}</code></p>
    <p>服务就绪后会自动进入界面，无需重新启动程序。</p>
    <p class="detail">${escapeHtml(reason)}</p><p class="detail">若启动命令已经退出，请在项目目录运行 npm run dev。</p>
    </main></body></html>`
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`
}

/** Stop an unfinished Chromium navigation before retrying or releasing the window. */
function navigate(
  window: DevelopmentWindow, url: string, signal: AbortSignal, timeoutMs: number,
  ready?: Promise<void>, onWaiting?: (url: string) => void,
): Promise<void> {
  if (signal.aborted || window.isDestroyed()) {
    // The attempt's dispose rejects its readiness wait; consume it even when
    // the window closes between creating the attempt and starting navigation.
    void ready?.catch(() => {})
    return Promise.reject(closedError())
  }
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      clearTimeout(waitingTimer)
      signal.removeEventListener('abort', abort)
      if (error) reject(error)
      else resolve()
    }
    const stop = (error: Error) => {
      if (settled) return
      try {
        if (!window.isDestroyed()) window.webContents.stop()
      } catch (stopError) {
        finish(new Error(`${error.message}; failed to stop navigation`, { cause: stopError }))
        return
      }
      finish(error)
    }
    const abort = () => stop(closedError())
    const timer = setTimeout(() => stop(new Error(`Navigation timeout loading ${url}`)), timeoutMs)
    // A slow resource must not destroy an already mounting React page every 30s.
    const waitingTimer = ready && onWaiting ? setTimeout(() => onWaiting(url), 30000) : undefined
    signal.addEventListener('abort', abort, { once: true })
    ready?.then(() => finish(), error => finish(error instanceof Error ? error : new Error(String(error))))
    try {
      Promise.resolve(window.loadURL(url)).then(() => {
        if (!ready) finish()
      }, error => {
        finish(error instanceof Error ? error : new Error(String(error)))
      })
    } catch (error) {
      finish(error instanceof Error ? error : new Error(String(error)))
    }
  })
}

function retryDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve()
  return new Promise(resolve => {
    const finish = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = setTimeout(finish, milliseconds)
    signal.addEventListener('abort', finish, { once: true })
  })
}

/** Retry the launcher's exact URL until loaded or closed, never a permanent error page. */
export async function loadDevelopmentUi(
  window: DevelopmentWindow, url: string, options: DevelopmentLoadOptions = {},
): Promise<'loaded' | 'closed' | 'failed'> {
  const controller = new AbortController()
  const close = () => controller.abort()
  window.once('closed', close)
  const signal = controller.signal
  const navigationTimeoutMs = options.navigationTimeoutMs ?? (options.startRenderer ? 120000 : 30000)
  const showWaiting = async (reason = '') => {
    try {
      await navigate(window, waitingPage(url, reason), signal, navigationTimeoutMs)
    } catch (error) {
      if (signal.aborted || window.isDestroyed()) throw error
      options.onRetry?.(new Error('Development loading page failed to load', { cause: error }))
    }
    if (!signal.aborted && !window.isDestroyed()) window.show()
  }
  try {
    await showWaiting()
    while (!signal.aborted) {
      try {
        await (options.waitForServer ?? waitForDevServer)(url, {
          timeoutMs: options.readinessTimeoutMs ?? 120000,
          requestTimeoutMs: options.requestTimeoutMs ?? 15000,
          signal,
        })
        if (signal.aborted) return 'closed'
        const renderer = options.startRenderer?.(url, signal)
        try {
          await navigate(window, renderer?.url ?? url, signal, navigationTimeoutMs, renderer?.ready, options.onWaiting)
        } finally {
          renderer?.dispose()
        }
        return 'loaded'
      } catch (error) {
        if (signal.aborted || window.isDestroyed()) return 'closed'
        const failure = error instanceof Error ? error : new Error(String(error))
        options.onRetry?.(failure)
        if (failure.name === 'RendererStartupFailure') {
          // The renderer's error boundary owns a visible, actionable failure UI.
          // Reloading the same broken application hides the useful diagnostic.
          window.show()
          return 'failed'
        }
        await showWaiting(failure.message)
        await retryDelay(options.retryDelayMs ?? 1000, signal)
      }
    }
    return 'closed'
  } catch (error) {
    if (signal.aborted || window.isDestroyed()) return 'closed'
    throw error
  } finally {
    controller.abort()
    window.removeListener('closed', close)
  }
}
