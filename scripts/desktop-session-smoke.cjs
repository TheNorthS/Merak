/** Observe the first paint, including forms that disappear before readiness. */
function observeStartup() {
  const evidence = { passwordRendered: false, sessionChecks: 0, startupScreenShown: false, startupStages: [] }
  window.__merakStartupProbe = evidence
  const inspect = node => {
    if (node instanceof Element && (node.matches('input[type="password"]') || node.querySelector('input[type="password"]'))) evidence.passwordRendered = true
    if (node instanceof Element && (node.matches('.merak-startup') || node.querySelector('.merak-startup'))) {
      evidence.startupScreenShown = true
      evidence.startupStages = Array.from(document.querySelectorAll('.merak-startup-stages li')).map(item => item.textContent)
    }
  }
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) inspect(node)
  }).observe(document, { childList: true, subtree: true })
  const original = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href)
    if (url.pathname === '/api/auth/me') {
      evidence.sessionChecks += 1
      await new Promise(resolve => setTimeout(resolve, 1500))
    }
    return original(input, init)
  }
}

async function verifySessionStartup(address, command, evaluate) {
  await command(address, 'Page.enable', {})
  await command(address, 'Page.addScriptToEvaluateOnNewDocument', { source: `(${observeStartup.toString()})()` })
  await command(address, 'Page.reload', {})
  const deadline = Date.now() + 20000
  let latest
  while (Date.now() < deadline) {
    try {
      const evidence = await evaluate(address, `({ probe: window.__merakStartupProbe,
        workspace: Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('打开文件夹')) })`)
      latest = evidence
      if (evidence.probe?.passwordRendered) throw new Error('Desktop startup displayed a password form')
      if (evidence.workspace && evidence.probe?.sessionChecks) {
        if (!evidence.probe.startupScreenShown || evidence.probe.startupStages.length !== 3) throw new Error('Startup animation stages missing')
        return { startup_password_form: false, workspace_entered: true, startup_animation: true, startup_stages: evidence.probe.startupStages }
      }
    } catch (error) {
      if (error.message.includes('password form') || error.message.includes('animation stages')) throw error
      // Page.reload briefly replaces the inspector execution context.
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('Desktop did not enter the workspace after automatic authentication: ' + JSON.stringify(latest))
}

async function probeSessionRecovery() {
  const original = window.fetch
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms))
  try {
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href)
      return url.pathname === '/api/auth/me' ? Promise.resolve(new Response('{}', { status: 401 })) : original(input, init)
    }
    window.dispatchEvent(new Event('merak-ide:authentication-required'))
    await wait(600)
    const passwordForm = Boolean(document.querySelector('input[type="password"]'))
    const reconnectOffered = Array.from(document.querySelectorAll('button')).some(b => b.textContent === '重新连接')
    window.fetch = original
    window.dispatchEvent(new Event('merak-ide:authentication-required'))
    const deadline = Date.now() + 10000
    while (Date.now() < deadline && document.querySelector('[aria-label="工作区连接状态"]')) await wait(100)
    return { passwordForm, reconnectOffered, recovered: !document.querySelector('[aria-label="工作区连接状态"]') }
  } finally { window.fetch = original }
}

module.exports = { verifySessionStartup, probeSessionRecovery }
