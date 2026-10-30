/** Bootstrap import failures remain visible even when application styles cannot load. */
import { startupErrorMessage, type StartupSignal } from './startupSignal'

export async function bootstrapRenderer<T>(options: {
  startup: StartupSignal
  loadApplication: () => Promise<T>
  mountApplication: (application: T) => void
  showFailure: (message: string) => void
}): Promise<void> {
  try {
    const application = await options.loadApplication()
    options.mountApplication(application)
  } catch (error) {
    options.startup.error(error)
    console.error('[Merak] Frontend bootstrap failed:', error)
    options.showFailure(startupErrorMessage(error))
  }
}

/** Text-only fallback avoids interpreting module error messages as HTML. */
export function showBootstrapFailure(document: Document, message: string): void {
  const panel = document.createElement('main')
  panel.setAttribute('role', 'alert')
  panel.style.cssText = 'padding:32px;background:#1e1e2e;color:#cdd6f4;min-height:100vh;font:15px system-ui'
  const heading = document.createElement('h1')
  heading.textContent = 'Merak — 前端启动失败'
  const description = document.createElement('p')
  description.textContent = '界面未能完成加载。请查看开发终端日志，修复后重新加载。'
  const detail = document.createElement('pre')
  detail.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere'
  detail.textContent = message
  const retry = document.createElement('button')
  retry.textContent = '重新加载'
  retry.addEventListener('click', () => document.defaultView?.location.reload())
  panel.append(heading, description, detail, retry)
  const root = document.getElementById('root')
  if (root) root.replaceChildren(panel)
  else document.body.append(panel)
}
