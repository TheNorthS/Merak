const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

function load(relative, overrides = {}, browser = {}) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, { module, exports: module.exports, window: browser, fetch,
    require: name => overrides[name] || require(name) })
  return module.exports
}
const policy = load('src/components/common/sessionAccess.ts')
const presentation = load('src/components/common/startupPresentation.ts')
const startup = load('src/components/common/StartupScreen.tsx', {
  './startupPresentation': presentation,
  './useBackendStartup': { useBackendStartup: () => null },
  './StartupScreen.css': {},
}, { merakIDE: { backend: {} } })
const probe = (desktop, status) => policy.requestSessionAccess(desktop, 'http://fixture/api/auth/me',
  new AbortController().signal, async () => ({ ok: status === 200, status }))

function render(access, desktop = true, file = desktop) {
  const browser = { location: { protocol: file ? 'file:' : 'https:' }, merakIDE: desktop ? { backend: {} } : undefined }
  const { SessionGate } = load('src/components/common/SessionGate.tsx', {
    '../../config': { API_BASE: 'http://fixture' },
    './useSessionAccess': { useSessionAccess: () => ({ access }) },
    './StartupScreen': startup,
  }, browser)
  return renderToStaticMarkup(React.createElement(SessionGate, null, React.createElement('div', null, 'workspace-fixture')))
}

test('initial desktop and browser rendering wait without a password form', () => {
  for (const desktop of [true, false]) {
    const html = render(policy.pendingSessionAccess(desktop), desktop)
    assert(!html.includes('<form'))
    assert(!html.includes('workspace-fixture'))
    assert(html.includes('role="status"'))
  }
})

test('desktop authorization failures never ask for a password or admit the workspace', async () => {
  for (const code of [401, 403, 500]) {
    const state = await probe(true, code)
    assert.equal(state.status, 'unavailable')
    const html = render(state)
    assert(!html.includes('<form') && !html.includes('type="password"'))
    assert(!html.includes('workspace-fixture'))
    assert(html.includes('重新连接') && html.includes('重启本地服务'))
    assert(!render(state, false, true).includes('<form'), 'Missing preload must not turn file:// into a web login')
  }
})

test('only a confirmed unauthenticated browser session requests credentials', async () => {
  assert(render(await probe(false, 401), false).includes('type="password"'))
  for (const code of [403, 500]) assert(!render(await probe(false, code), false).includes('<form'))
})

test('connection failure remains retryable and a later authorized response admits the workspace', async () => {
  const state = await policy.requestSessionAccess(true, 'http://fixture', new AbortController().signal,
    async () => { throw new Error('connection refused') })
  assert.equal(state.status, 'unavailable')
  assert(!render(state).includes('<form'))
  const recovered = render(await probe(true, 200))
  assert(recovered.includes('workspace-fixture') && !recovered.includes('<form'))
})

test('startup stages follow backend readiness and preserve failure controls', () => {
  const checking = policy.pendingSessionAccess(true)
  const starting = presentation.startupPresentation(checking, { status: 'starting' }, true)
  assert.equal(starting.stage, 1)
  assert.equal(starting.failed, false)
  assert.equal(presentation.startupPresentation(checking, { status: 'ready' }, true).stage, 2)
  const unavailable = { status: 'unavailable', message: 'connection failed' }
  assert.equal(presentation.startupPresentation(unavailable, { status: 'starting' }, true).failed, false)
  assert.equal(presentation.startupPresentation(unavailable, { status: 'ready' }, true).failed, true)
  assert.equal(presentation.startupPresentation(checking, { status: 'error' }, true).failed, true)
})
