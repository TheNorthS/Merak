const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const ts = require('typescript')
const vm = require('node:vm')
const path = require('node:path')

function load(name, electron) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', name), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, URL, require: () => electron })
  return module.exports
}
test('capability never reaches foreign child frames or external URLs', () => {
  const auth = load('electron/backend-request-auth.ts', {})
  let handler
  const window = { webContents: { id: 4, mainFrame: { routingId: 1, processId: 2 },
    getURL: () => 'http://127.0.0.1:5178/index.html',
    session: { webRequest: { onBeforeSendHeaders: (_filter, callback) => { handler = callback } } } } }
  auth.installBackendRequestAuth(window, 'fixture-secret')
  let result
  const request = { webContentsId: 4, frame: { routingId: 1, processId: 2 }, requestHeaders: { Origin: 'http://127.0.0.1:5178' } }
  handler(request, value => { result = value })
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], 'fixture-secret')
  handler({ ...request, frame: { routingId: 3, processId: 2 } }, value => { result = value })
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], undefined)
  handler({ ...request, requestHeaders: { Origin: 'https://untrusted.invalid' } }, value => { result = value })
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], undefined)
})
test('privileged IPC rejects another window, child frame and navigated document', () => {
  let handler
  const ipc = load('electron/trusted-ipc.ts', { ipcMain: { handle: (_channel, callback) => { handler = callback } } })
  const frame = { url: 'file:///app/index.html' }
  const window = { isDestroyed: () => false, webContents: { mainFrame: frame } }
  ipc.trustRenderer(window, frame.url)
  ipc.handleTrusted('fixture', () => 'allowed')
  assert.equal(handler({ sender: window.webContents, senderFrame: frame }), 'allowed')
  assert.throws(() => handler({ sender: {}, senderFrame: frame }))
  assert.throws(() => handler({ sender: window.webContents, senderFrame: { ...frame } }))
  frame.url = 'https://untrusted.invalid'
  assert.throws(() => handler({ sender: window.webContents, senderFrame: frame }))
})

test('packaged main-frame GET without Origin or Referer receives its capability', () => {
  const auth = load('electron/backend-request-auth.ts', {})
  let handler
  const page = 'file:///installed/resources/app.asar/dist/index.html'
  const frame = { routingId: 1, processId: 2, url: page }
  const window = { webContents: { id: 4, mainFrame: frame, getURL: () => page,
    session: { webRequest: { onBeforeSendHeaders: (_filter, callback) => { handler = callback } } } } }
  auth.installBackendRequestAuth(window, 'fixture-secret')
  let result
  const request = { webContentsId: 4, frame, referrer: '', requestHeaders: {} }
  handler(request, value => { result = value })
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], 'fixture-secret')
  for (const foreign of [undefined, { ...frame, routingId: 3 }, { ...frame, url: 'file:///other.html' }]) {
    handler({ ...request, frame: foreign }, value => { result = value })
    assert.equal(result.requestHeaders['X-Merak-Owner-Token'], undefined)
  }
})

test('packaged WebSocket file origin is normalized only for the verified main document', () => {
  const auth = load('electron/backend-request-auth.ts', {})
  let handler
  const page = 'file:///installed/resources/app.asar/dist/index.html'
  const frame = { routingId: 1, processId: 2, url: page }
  const window = { webContents: { id: 4, mainFrame: frame, getURL: () => page,
    session: { webRequest: { onBeforeSendHeaders: (_filter, callback) => { handler = callback } } } } }
  auth.installBackendRequestAuth(window, 'fixture-secret')
  const request = { webContentsId: 4, frame, resourceType: 'webSocket', referrer: '',
    requestHeaders: { Origin: 'file://' } }
  let result
  handler(request, value => { result = value })
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], 'fixture-secret')
  assert.equal(result.requestHeaders.Origin, 'null')
  for (const foreign of [undefined, { ...frame, routingId: 3 }, { ...frame, url: 'file:///other.html' }]) {
    handler({ ...request, frame: foreign }, value => { result = value })
    assert.equal(result.requestHeaders['X-Merak-Owner-Token'], undefined)
    assert.equal(result.requestHeaders.Origin, 'file://')
  }
  handler({ ...request, webContentsId: 5 }, value => { result = value })
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], undefined)
  handler({ ...request, requestHeaders: { origin: 'file://' } }, value => { result = value })
  assert.equal(result.requestHeaders.origin, 'null')
  assert.equal(result.requestHeaders['X-Merak-Owner-Token'], 'fixture-secret')
})
