import type { SessionAccess } from './sessionAccess'
import { startupPresentation } from './startupPresentation'
import { useBackendStartup } from './useBackendStartup'
import './StartupScreen.css'

function StartupMark() {
  return <div className="merak-startup-mark" aria-hidden="true">
    <div className="merak-startup-halo" />
    <svg className="merak-startup-orbit" viewBox="0 0 320 320" fill="none">
      <circle cx="160" cy="160" r="140" className="startup-orbit-guide" />
      <circle cx="160" cy="160" r="116" className="startup-orbit-guide" strokeDasharray="2 12" />
      <g className="startup-orbit-moving"><path d="M160 20a140 140 0 0 1 140 140" /><circle cx="300" cy="160" r="3" /></g>
      <path d="M160 8v16M160 296v16M8 160h16M296 160h16" className="startup-orbit-ticks" />
    </svg>
    <svg className="merak-startup-symbol" viewBox="0 0 256 256" fill="none">
      <path d="M48 191L83 87L128 131V169L95 137L77 191Z" className="startup-m-left" />
      <path d="M128 131L173 87L208 191H179L161 137L128 169Z" className="startup-m-right" />
      <path d="M128 27L136 49L158 57L136 65L128 87L120 65L98 57L120 49Z" className="startup-star" />
    </svg>
  </div>
}

export function StartupScreen({ access, desktop, retry, restart }: {
  access: SessionAccess; desktop: boolean; retry: () => Promise<void>; restart: () => Promise<void>
}) {
  const backend = useBackendStartup()
  const view = startupPresentation(access, backend, desktop)
  const stages = ['载入界面', desktop ? '启动本地服务' : '连接服务', '连接工作区']
  return <section className={`merak-startup${view.failed ? ' merak-startup-paused' : ''}`} aria-label="工作区连接状态">
    <div className="merak-startup-grid" aria-hidden="true" />
    <header className="merak-startup-top titlebar-drag">
      <span>MERAK <span className="startup-top-divider">/</span> RESEARCH WORKSPACE</span>
      {desktop && window.merakIDE?.window && <div className="merak-startup-controls titlebar-no-drag">
        <button aria-label="最小化" onClick={() => window.merakIDE.window.minimize()}>−</button>
        <button aria-label="关闭窗口" onClick={() => window.merakIDE.window.close()}>×</button>
      </div>}
    </header>
    <div className="merak-startup-content">
      <StartupMark />
      <h1 className="merak-startup-name">Merak<span aria-hidden="true">.</span></h1>
      <p className="merak-startup-tagline">让每一个问题，走向发现。</p>
      <div className="merak-startup-progress">
        <div className="merak-startup-status" role="status" aria-live="polite">
          <span className="startup-status-dot" aria-hidden="true" /><span>{view.title}</span>
          <span className="startup-stage-count" aria-hidden="true">0{view.stage + 1} <span>/ 03</span></span>
        </div>
        <ol className="merak-startup-stages" aria-label="启动阶段">
          {stages.map((label, index) => <li key={label} data-state={index < view.stage ? 'done' : index === view.stage ? 'active' : 'pending'} aria-current={index === view.stage ? 'step' : undefined}>
            <span className="startup-stage-line" aria-hidden="true" /><span>{index < view.stage ? '✓ ' : ''}{label}</span>
          </li>)}
        </ol>
        <p className="merak-startup-detail">{view.detail}</p>
        {view.failed && <div className="merak-startup-actions">
          <button onClick={() => void retry()}>重新连接</button>
          {desktop && window.merakIDE?.backend && <button onClick={() => void restart()}>重启本地服务</button>}
        </div>}
      </div>
    </div>
    <footer className="merak-startup-footer"><span>文献 · 实验 · 发现</span><span>NorthS Team</span></footer>
  </section>
}
