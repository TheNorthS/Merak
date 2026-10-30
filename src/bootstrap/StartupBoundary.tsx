/** Report only a committed application, with an explicit error view on render failure. */
import { Component, useEffect, type ErrorInfo, type ReactNode } from 'react'
import { startupErrorMessage, type StartupSignal } from './startupSignal'

interface StartupBoundaryProps {
  children: ReactNode
  startup: StartupSignal
}

export class StartupBoundary extends Component<StartupBoundaryProps> {
  state = { failed: false, message: '' }

  static getDerivedStateFromError(error: unknown) {
    return { failed: true, message: startupErrorMessage(error) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.props.startup.error(error)
    console.error('[Merak] Frontend render failed:', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return <StartupFailureView message={this.state.message} />
  }
}

export function StartupCommit({ startup, applicationRoot }: {
  startup: StartupSignal
  applicationRoot: HTMLElement
}) {
  useEffect(() => {
    if (applicationRoot.childElementCount === 0) {
      throw new Error('前端已执行，但未渲染出应用界面。')
    }
    let active = true
    // Error-boundary commits and StrictMode cleanup must settle before ready.
    queueMicrotask(() => { if (active) startup.ready() })
    return () => { active = false }
  }, [startup, applicationRoot])
  return null
}

function StartupFailureView({ message }: { message: string }) {
  return (
    <main role="alert" style={{ padding: 32, color: '#cdd6f4', background: '#1e1e2e', minHeight: '100vh' }}>
      <h1>Merak — 前端启动失败</h1>
      <p>界面未能完成加载。请查看开发终端日志，修复后重新加载。</p>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{message}</pre>
      <button onClick={() => location.reload()}>重新加载</button>
      <button onClick={() => window.merakIDE?.window.close()}>关闭窗口</button>
    </main>
  )
}
