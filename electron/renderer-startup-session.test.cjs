const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { readFileSync } = require('node:fs')
const Module = require('node:module')
const { dirname, resolve } = require('node:path')
const test = require('node:test')
const ts = require('typescript')

const sourcePath = resolve(__dirname, 'renderer-startup-session.ts')
const sharedPath = resolve(__dirname, '../shared/renderer-startup.ts')

function compile(filePath, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(filePath, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const loaded = new Module(filePath, module)
  loaded.filename = filePath
  loaded.paths = Module._nodeModulePaths(dirname(filePath))
  loaded.require = (specifier) => imports[specifier] ?? Module.prototype.require.call(loaded, specifier)
  loaded._compile(compiled.outputText, filePath)
  return loaded.exports
}

function capture(promise) {
  const state = { settled: false, error: null }
  const done = promise.then(
    () => { state.settled = true },
    (error) => { state.settled = true; state.error = error },
  )
  return { state, done }
}

function fixture(selectedUrl = 'http://127.0.0.1:5178/') {
  const ipcMain = new EventEmitter()
  const contract = compile(sharedPath)
  const implementation = compile(sourcePath, {
    electron: { ipcMain }, '../shared/renderer-startup': contract,
  })
  const controller = new AbortController()
  const abortListeners = new Set()
  const add = controller.signal.addEventListener.bind(controller.signal)
  const remove = controller.signal.removeEventListener.bind(controller.signal)
  controller.signal.addEventListener = (type, listener, options) => {
    if (type === 'abort') abortListeners.add(listener)
    return add(type, listener, options)
  }
  controller.signal.removeEventListener = (type, listener, options) => {
    if (type === 'abort') abortListeners.delete(listener)
    return remove(type, listener, options)
  }
  const window = { webContents: { mainFrame: { url: '' } } }
  const attempt = implementation.createRendererStartupAttempt(window, selectedUrl, controller.signal)
  window.webContents.mainFrame.url = attempt.url
  const token = new URL(attempt.url).searchParams.get(contract.RENDERER_STARTUP_QUERY)
  const result = capture(attempt.ready)
  const emit = (notice, event = {
    sender: window.webContents, senderFrame: window.webContents.mainFrame,
  }) => ipcMain.emit(contract.RENDERER_STARTUP_CHANNEL, event, notice)
  const assertCleaned = () => {
    assert.equal(ipcMain.listenerCount(contract.RENDERER_STARTUP_CHANNEL), 0)
    assert.equal(abortListeners.size, 0)
  }
  return { ipcMain, contract, implementation, controller, window, attempt, token, emit,
    ...result, assertCleaned }
}

async function assertPending(fixture) {
  await Promise.resolve()
  assert.equal(fixture.state.settled, false, 'untrusted or malformed messages must not settle readiness')
}

test('only current main-frame readiness succeeds and removes all listeners', async () => {
  const f = fixture('http://127.0.0.1:5193/workspace?mode=dev#editor')
  const url = new URL(f.attempt.url)
  assert.equal(url.origin, 'http://127.0.0.1:5193')
  assert.equal(url.pathname, '/workspace')
  assert.equal(url.searchParams.get('mode'), 'dev')
  assert.equal(url.hash, '#editor')
  assert.match(f.token, /^[a-f0-9-]{36}$/)
  f.emit({ token: f.token, status: 'ready' })
  await f.done
  assert.equal(f.state.error, null)
  f.assertCleaned()
  f.controller.abort()
  f.attempt.dispose()
  assert.equal(f.state.error, null, 'later cleanup cannot turn success into cancellation')
})

test('a correct nonce cannot authorize readiness from another URL', async () => {
  const f = fixture()
  f.window.webContents.mainFrame.url = f.attempt.url.replace('5178', '5179')
  f.emit({ token: f.token, status: 'ready' })
  await assertPending(f)
  f.window.webContents.mainFrame.url = f.attempt.url
  f.emit({ token: f.token, status: 'ready' })
  await f.done
  assert.equal(f.state.error, null)
  f.assertCleaned()
})

test('subframes and foreign windows cannot acknowledge the current navigation', async () => {
  const f = fixture()
  f.emit({ token: f.token, status: 'ready' }, {
    sender: f.window.webContents, senderFrame: { url: f.attempt.url },
  })
  f.emit({ token: f.token, status: 'ready' }, {
    sender: { mainFrame: f.window.webContents.mainFrame }, senderFrame: f.window.webContents.mainFrame,
  })
  f.emit({ token: f.token, status: 'ready' }, { sender: f.window.webContents, senderFrame: null })
  await assertPending(f)
  f.attempt.dispose()
  await f.done
  assert.equal(f.state.error.name, 'AbortError')
  f.assertCleaned()
})

test('every retry has a fresh nonce and ignores late readiness from an earlier page', async () => {
  const f = fixture()
  f.attempt.dispose()
  await f.done
  const next = f.implementation.createRendererStartupAttempt(
    f.window, 'http://127.0.0.1:5178/', new AbortController().signal,
  )
  const nextToken = new URL(next.url).searchParams.get(f.contract.RENDERER_STARTUP_QUERY)
  assert.notEqual(nextToken, f.token)
  f.window.webContents.mainFrame.url = next.url
  const current = capture(next.ready)
  f.emit({ token: f.token, status: 'ready' })
  await assertPending(current)
  f.emit({ token: nextToken, status: 'ready' })
  await current.done
  assert.equal(current.state.error, null)
  assert.equal(f.ipcMain.listenerCount(f.contract.RENDERER_STARTUP_CHANNEL), 0)
})

test('malformed notices and unsupported statuses leave the attempt pending', async () => {
  const f = fixture()
  for (const notice of [null, undefined, false, 1, 'ready', [], {},
    { token: f.token }, { token: 123, status: 'ready' },
    { token: f.token, status: 'loaded' }, { token: 'old-token', status: 'error', message: 'stale' }]) {
    f.emit(notice)
  }
  await assertPending(f)
  f.controller.abort()
  await f.done
  assert.equal(f.state.error.name, 'AbortError')
  f.assertCleaned()
})

test('a renderer error is typed, bounds untrusted text, and releases listeners', async () => {
  const f = fixture()
  f.emit({ token: f.token, status: 'error', message: 'x'.repeat(2000) })
  await f.done
  assert.ok(f.state.error instanceof f.implementation.RendererStartupFailure)
  assert.equal(f.state.error.name, 'RendererStartupFailure')
  assert.equal(f.state.error.message, `Renderer startup failed: ${'x'.repeat(1000)}`)
  assert.equal(f.contract.RENDERER_STARTUP_ERROR_LIMIT, 1000)
  f.assertCleaned()
})

test('a renderer error with non-text details uses the explicit unknown-error diagnostic', async () => {
  const f = fixture()
  f.emit({ token: f.token, status: 'error', message: { secret: 'not printable' } })
  await f.done
  assert.equal(f.state.error.message, 'Renderer startup failed: Unknown renderer error')
  f.assertCleaned()
})

test('abort cancellation immediately rejects and removes IPC and abort listeners', async () => {
  const f = fixture()
  f.controller.abort()
  await f.done
  assert.equal(f.state.error.name, 'AbortError')
  f.assertCleaned()
  f.emit({ token: f.token, status: 'ready' })
  assert.equal(f.state.error.name, 'AbortError')
})

test('disposing an unfinished attempt is idempotent and rejects as cancellation', async () => {
  const f = fixture()
  f.attempt.dispose()
  f.attempt.dispose()
  await f.done
  assert.equal(f.state.error.name, 'AbortError')
  f.assertCleaned()
})

test('pre-aborted attempts reject without leaving an IPC subscription', async () => {
  const f = fixture()
  f.attempt.dispose()
  await f.done
  const controller = new AbortController()
  controller.abort()
  const next = f.implementation.createRendererStartupAttempt(
    f.window, 'http://127.0.0.1:5178/', controller.signal,
  )
  await assert.rejects(next.ready, { name: 'AbortError' })
  assert.equal(f.ipcMain.listenerCount(f.contract.RENDERER_STARTUP_CHANNEL), 0)
})
