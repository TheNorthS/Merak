const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'merak-backend-lifecycle-'))
const sourcePath = path.resolve(__dirname, 'backend.ts')
const compiled = ts.transpileModule(fs.readFileSync(sourcePath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
})
const loaded = new Module(sourcePath, module)
loaded.filename = sourcePath
loaded.paths = Module._nodeModulePaths(path.dirname(sourcePath))
loaded.require = (specifier) => {
  if (specifier === '../trusted-ipc') return { handleTrusted: () => {} }
  if (specifier === '../backend-request-auth') return { installBackendRequestAuth: () => {} }
  if (specifier === 'electron') return {
    app: { getPath: () => root }, ipcMain: { handle: () => {} },
  }
  if (specifier === './backend-startup-service') return {
    BackendStartupService: class {
      constructor() {
        this.projectRoot = root
        this.installationSha256 = 'installation-a'
      }
      async probeExistingBackend() { return 'none' }
      clearRejectedDevelopmentInterpreters() {}
      cancelReadyWait() {}
    },
  }
  return Module.prototype.require.call(loaded, specifier)
}
loaded._compile(compiled.outputText, sourcePath)
const createManager = () => new loaded.exports.backendManager.constructor()

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

test('concurrent restart requests share one stop and start', async () => {
  const manager = createManager()
  const gate = deferred()
  let stops = 0
  let starts = 0
  manager.stopOnce = async () => { stops += 1; await gate.promise }
  manager.start = async () => { starts += 1 }
  const first = manager.restart()
  const second = manager.restart()
  assert.equal(stops, 1)
  gate.resolve()
  await Promise.all([first, second])
  assert.equal(stops, 1)
  assert.equal(starts, 1)
})

test('start waits until an in-flight stop settles', async () => {
  const manager = createManager()
  const gate = deferred()
  let started = 0
  manager.stopOnce = async () => { await gate.promise }
  manager.startOnce = async () => { started += 1 }
  manager.state.status = 'stopped'
  const stopping = manager.stop()
  const starting = manager.start()
  assert.equal(started, 0)
  gate.resolve()
  await Promise.all([stopping, starting])
  assert.equal(started, 1)
})

test('orphaned old desktop backend is never marked ready', async () => {
  const manager = createManager()
  manager.startup.probeExistingBackend = async () => 'stale-owned'
  manager.state.status = 'stopped'
  manager.stopOnce = async () => {}
  await manager.start()
  assert.equal(manager.getState().status, 'error')
  assert.match(manager.getState().error, /orphaned MERAK server/)
})

test.after(() => fs.rmSync(root, { recursive: true, force: true }))
