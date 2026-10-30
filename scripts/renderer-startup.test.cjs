const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const test = require('node:test')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ts = require('typescript')

const projectRoot = path.resolve(__dirname, '..')

function sourceLoader(overrides = {}) {
  const cache = new Map()
  function load(relative) {
    const filename = path.resolve(projectRoot, relative)
    if (cache.has(filename)) return cache.get(filename).exports
    const loaded = new Module(filename, module)
    loaded.filename = filename
    loaded.paths = Module._nodeModulePaths(path.dirname(filename))
    cache.set(filename, loaded)
    loaded.require = specifier => {
      if (Object.hasOwn(overrides, specifier)) return overrides[specifier]
      if (specifier === '@shared/renderer-startup') return load('shared/renderer-startup.ts')
      if (specifier.startsWith('.')) {
        const target = path.resolve(path.dirname(filename), specifier)
        for (const suffix of ['.ts', '.tsx']) {
          if (fs.existsSync(target + suffix)) return load(target + suffix)
        }
      }
      return Module.prototype.require.call(loaded, specifier)
    }
    const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    })
    loaded._compile(compiled.outputText, filename)
    return loaded.exports
  }
  return load
}

const load = sourceLoader()
const { createStartupSignal, startupErrorMessage } = load('src/bootstrap/startupSignal.ts')
const { bootstrapRenderer, showBootstrapFailure } = load('src/bootstrap/bootstrapRenderer.ts')

function fixture() {
  const notices = []
  const startup = createStartupSignal('?other=value&__merak_startup=runtime-nonce', notice => notices.push(notice))
  return { startup, notices }
}

test('startup is pending until a successful commit and only sends ready once', () => {
  const { startup, notices } = fixture()
  assert.deepEqual(notices, [])
  startup.ready()
  startup.ready()
  assert.deepEqual(notices, [{ token: 'runtime-nonce', status: 'ready' }])
})

test('error is terminal and prevents a later or already-queued ready', () => {
  const { startup, notices } = fixture()
  startup.error(new Error('module import failed'))
  startup.ready()
  startup.error(new Error('second failure'))
  assert.deepEqual(notices, [{ token: 'runtime-nonce', status: 'error', message: 'module import failed' }])
})

test('a post-commit render failure is reported but cannot send ready again', () => {
  const { startup, notices } = fixture()
  startup.ready()
  startup.error('render failed')
  startup.ready()
  assert.deepEqual(notices.map(notice => notice.status), ['ready', 'error'])
})

test('web-only and the old preload bridge do not fail when reporting startup', () => {
  const withoutBridge = createStartupSignal('?__merak_startup=nonce')
  assert.doesNotThrow(() => { withoutBridge.ready(); withoutBridge.error('failure') })
  const notices = []
  const withoutToken = createStartupSignal('?project=x', notice => notices.push(notice))
  withoutToken.ready()
  withoutToken.error('failure')
  assert.deepEqual(notices, [])
})

test('failure notices have bounded text, no control characters, and no stack', () => {
  assert.equal(startupErrorMessage(new Error('bad\nmodule\u0000')), 'bad module')
  assert.equal(startupErrorMessage('x'.repeat(3000)).length, 1000)
  assert.equal(startupErrorMessage({ secret: 'not an error message' }), '前端启动失败。请查看开发终端日志。')
})

test('bootstrap waits for imports and mounting alone never reports ready', async () => {
  const { startup, notices } = fixture()
  const events = []
  await bootstrapRenderer({
    startup,
    loadApplication: async () => { events.push('load'); return 'application' },
    mountApplication: app => { events.push(`mount:${app}`) },
    showFailure: () => assert.fail('successful imports must not show an error'),
  })
  assert.deepEqual(events, ['load', 'mount:application'])
  assert.deepEqual(notices, [])
})

test('application or CSS import failure reports error and never mounts', async () => {
  for (const failedImport of ['application', 'styles']) {
    const { startup, notices } = fixture()
    const displayed = []
    await bootstrapRenderer({
      startup,
      loadApplication: () => Promise.all(['application', 'styles'].map(name => (
        name === failedImport ? Promise.reject(new Error(`${name} unavailable`)) : Promise.resolve(name)
      ))),
      mountApplication: () => assert.fail('incomplete bootstrap must not mount'),
      showFailure: message => displayed.push(message),
    })
    startup.ready()
    assert.deepEqual(displayed, [`${failedImport} unavailable`])
    assert.equal(notices.length, 1)
    assert.equal(notices[0].status, 'error')
  }
})

test('a missing mount root is displayed as an explicit bootstrap failure', async () => {
  const { startup, notices } = fixture()
  const displayed = []
  await bootstrapRenderer({
    startup,
    loadApplication: async () => 'application',
    mountApplication: () => { throw new Error('missing root') },
    showFailure: message => displayed.push(message),
  })
  assert.deepEqual(displayed, ['missing root'])
  assert.equal(notices[0].status, 'error')
})

function commitFixture() {
  const effects = []
  const localLoad = sourceLoader({ react: { ...React, useEffect: callback => effects.push(callback) } })
  const components = localLoad('src/bootstrap/StartupBoundary.tsx')
  return { ...components, effects }
}

test('commit probe reports only after effect settlement, not during render', async () => {
  const { startup, notices } = fixture()
  const { StartupCommit, effects } = commitFixture()
  assert.equal(StartupCommit({ startup, applicationRoot: { childElementCount: 1 } }), null)
  assert.deepEqual(notices, [])
  effects[0]()
  assert.deepEqual(notices, [])
  await Promise.resolve()
  assert.equal(notices[0].status, 'ready')
})

test('StrictMode cleanup cancels its first pending ready without losing the second', async () => {
  const { startup, notices } = fixture()
  const { StartupCommit, effects } = commitFixture()
  StartupCommit({ startup, applicationRoot: { childElementCount: 1 } })
  const effect = effects[0]
  const cleanup = effect()
  cleanup()
  effect()
  await Promise.resolve()
  assert.equal(notices.length, 1)
  assert.equal(notices[0].status, 'ready')
})

test('a boundary error before the deferred commit suppresses ready', async () => {
  const { startup, notices } = fixture()
  const { StartupCommit, effects } = commitFixture()
  StartupCommit({ startup, applicationRoot: { childElementCount: 1 } })
  effects[0]()
  startup.error('effect failed')
  await Promise.resolve()
  assert.deepEqual(notices.map(notice => notice.status), ['error'])
})

test('an empty application cannot be mistaken for successful startup', () => {
  const { startup, notices } = fixture()
  const { StartupCommit, effects } = commitFixture()
  StartupCommit({ startup, applicationRoot: { childElementCount: 0 } })
  assert.throws(() => effects[0](), /未渲染出应用界面/)
  assert.deepEqual(notices, [])
})

test('render failure displays a safe error view and sends an error notice', () => {
  const { startup, notices } = fixture()
  const { StartupBoundary } = load('src/bootstrap/StartupBoundary.tsx')
  const failure = new Error('<script>alert(1)</script>')
  const boundary = new StartupBoundary({ startup, children: React.createElement('div', null, 'Application') })
  boundary.state = StartupBoundary.getDerivedStateFromError(failure)
  boundary.componentDidCatch(failure, { componentStack: 'App' })
  const markup = renderToStaticMarkup(boundary.render())
  assert.match(markup, /role="alert"/)
  assert.match(markup, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
  assert.doesNotMatch(markup, /<script>/)
  assert.deepEqual(notices.map(notice => notice.status), ['error'])
})

test('bootstrap fallback uses text nodes and remains usable without application CSS', () => {
  let panel
  let reloads = 0
  const document = {
    createElement: tag => ({
      tag, style: {}, attributes: {}, children: [], handlers: {},
      setAttribute(key, value) { this.attributes[key] = value },
      append(...children) { this.children.push(...children) },
      addEventListener(event, callback) { this.handlers[event] = callback },
    }),
    getElementById: () => ({ replaceChildren: value => { panel = value } }),
    defaultView: { location: { reload: () => { reloads += 1 } } },
  }
  showBootstrapFailure(document, '<img src=x onerror=alert(1)>')
  assert.equal(panel.attributes.role, 'alert')
  assert.equal(panel.children[2].textContent, '<img src=x onerror=alert(1)>')
  assert.equal(Object.hasOwn(panel.children[2], 'innerHTML'), false)
  panel.children[3].handlers.click()
  assert.equal(reloads, 1)
})

test('entry keeps App and its commit probe inside the same error boundary', () => {
  const entry = fs.readFileSync(path.join(projectRoot, 'src/main.tsx'), 'utf8')
  assert.match(entry, /Promise\.all\(\[import\('\.\/App'\), import\('\.\/index\.css'\)\]\)/)
  assert.match(entry, /<StartupBoundary[^>]*>\s*<SessionGate>\s*<App \/>\s*<\/SessionGate>\s*<StartupCommit[^>]*\/>\s*<\/StartupBoundary>/)
  assert.match(entry, /window\.merakIDE\?\.startup\?\.notify/)
  assert.doesNotMatch(entry, /DOMContentLoaded|load.*startup\.ready/)
})

test('preload exposes only the fixed startup channel for typed notices', () => {
  let bridge
  const calls = []
  const loadPreload = sourceLoader({ electron: {
    contextBridge: { exposeInMainWorld: (name, api) => { assert.equal(name, 'merakIDE'); bridge = api } },
    ipcRenderer: { send: (...args) => calls.push(args) },
  } })
  loadPreload('electron/preload.ts')
  const notice = { token: 'runtime-nonce', status: 'ready' }
  bridge.startup.notify(notice)
  assert.deepEqual(calls, [['renderer:startup', notice]])
})
