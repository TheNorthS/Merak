/** Renderer readiness is a successful React commit, never a document load event. */
export const RENDERER_STARTUP_CHANNEL = 'renderer:startup'
export const RENDERER_STARTUP_QUERY = '__merak_startup'
export const RENDERER_STARTUP_ERROR_LIMIT = 1000

export interface RendererStartupNotice {
  token: string
  status: 'ready' | 'error'
  message?: string
}
