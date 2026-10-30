import React from 'react'
import ReactDOM from 'react-dom/client'
import { bootstrapRenderer, showBootstrapFailure } from './bootstrap/bootstrapRenderer'
import { StartupBoundary, StartupCommit } from './bootstrap/StartupBoundary'
import { createStartupSignal } from './bootstrap/startupSignal'
import { installApiSession } from './services/apiSession'
import { API_BASE } from './config'
import { SessionGate } from './components/common/SessionGate'
import { applyStoredTheme } from './bootstrap/theme'

applyStoredTheme()
installApiSession(API_BASE)

const startup = createStartupSignal(location.search, window.merakIDE?.startup?.notify)

void bootstrapRenderer({
  startup,
  loadApplication: async () => {
    const [application] = await Promise.all([import('./App'), import('./index.css')])
    return application.default
  },
  mountApplication: App => {
    const applicationRoot = document.getElementById('root')
    if (!applicationRoot) throw new Error('前端入口缺少应用挂载节点 #root。')
    ReactDOM.createRoot(applicationRoot).render(
      <React.StrictMode>
        <StartupBoundary startup={startup}>
          <SessionGate><App /></SessionGate>
          <StartupCommit startup={startup} applicationRoot={applicationRoot} />
        </StartupBoundary>
      </React.StrictMode>,
    )
  },
  showFailure: message => showBootstrapFailure(document, message),
})
