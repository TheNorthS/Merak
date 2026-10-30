const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const Module = require('node:module')
const path = require('node:path')
const test = require('node:test')
const esbuild = require('esbuild')

const root = path.resolve(__dirname, '..')

function source(relative, electron = {}) {
  const filename = path.join(root, relative)
  const compiled = esbuild.buildSync({
    entryPoints: [filename], bundle: true, write: false,
    platform: 'node', format: 'cjs', target: 'node20', external: ['electron'],
    alias: { '@shared': path.join(root, 'shared') }, logLevel: 'silent',
  })
  const loaded = new Module(filename, module)
  loaded.filename = filename
  loaded.paths = Module._nodeModulePaths(path.dirname(filename))
  loaded.require = name => name === 'electron' ? electron : Module.prototype.require.call(loaded, name)
  loaded._compile(compiled.outputFiles[0].text, filename)
  return loaded.exports
}

const { loadDevelopmentUi } = source('electron/development-ui-loader.ts')
const { createStartupSignal } = source('src/bootstrap/startupSignal.ts')
const flush = async () => { for (let turn = 0; turn < 16; turn++) await Promise.resolve() }

function fixture(t) {
  const ipcMain = new EventEmitter()
  const { createRendererStartupAttempt } = source('electron/renderer-startup-session.ts', { ipcMain })
  const window = new EventEmitter()
  Object.assign(window, {
    destroyed: false, loads: [], stops: 0,
    webContents: { mainFrame: { url: '' }, stop() { window.stops++ } },
    isDestroyed() { return this.destroyed }, show() {},
    loadURL(url) { this.loads.push(url); this.webContents.mainFrame.url = url; return Promise.resolve() },
    close() { if (!this.destroyed) { this.destroyed = true; this.emit('closed') } },
  })
  t.after(() => window.close())
  let bridge
  source('electron/preload.ts', {
    contextBridge: { exposeInMainWorld(name, api) { assert.equal(name, 'merakIDE'); bridge = api } },
    ipcRenderer: { send(channel, notice) {
      ipcMain.emit(channel, { sender: window.webContents, senderFrame: window.webContents.mainFrame }, notice)
    } },
  })
  let reporter
  let settled = false
  const pending = loadDevelopmentUi(window, 'http://127.0.0.1:5178', {
    waitForServer: async () => {},
    startRenderer(url, signal) {
      const attempt = createRendererStartupAttempt(window, url, signal)
      reporter = createStartupSignal(new URL(attempt.url).search, bridge.startup.notify)
      return attempt
    },
  }).then(result => { settled = true; return result })
  return { ipcMain, window, pending, settled: () => settled, reporter: () => reporter }
}

test('real preload and nonce session require renderer commit rather than document completion', async t => {
  const f = fixture(t)
  await flush()
  assert.equal(f.settled(), false)
  assert.equal(f.window.loads.length, 2)
  assert.match(f.window.loads[1], /__merak_startup=/)
  f.reporter().ready()
  assert.equal(await f.pending, 'loaded')
  assert.equal(f.window.stops, 0)
  assert.equal(f.ipcMain.listenerCount('renderer:startup'), 0)
  assert.equal(f.window.listenerCount('closed'), 0)
})

test('real startup failure crosses the fixed preload channel and preserves its diagnostic page', async t => {
  const f = fixture(t)
  await flush()
  f.reporter().error(new Error('Application module failed'))
  f.reporter().ready()
  assert.equal(await f.pending, 'failed')
  assert.equal(f.window.loads.length, 2, 'renderer failure must not cause a blind navigation loop')
  assert.equal(f.ipcMain.listenerCount('renderer:startup'), 0)
})

test('a previous document token cannot complete the real bridge navigation', async t => {
  const f = fixture(t)
  await flush()
  f.ipcMain.emit('renderer:startup', {
    sender: f.window.webContents, senderFrame: f.window.webContents.mainFrame,
  }, { token: 'old-document', status: 'ready' })
  await flush()
  assert.equal(f.settled(), false)
  f.reporter().ready()
  assert.equal(await f.pending, 'loaded')
})
