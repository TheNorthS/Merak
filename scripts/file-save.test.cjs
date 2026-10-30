const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

function setup() {
  let fetchHandler
  const window = { dispatchEvent() {}, confirm: () => false }
  const globals = { window, console, Event: class {}, CustomEvent: class {},
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: (...args) => fetchHandler(...args) }
  const compile = (name, resolver) => {
    const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', name), 'utf8'), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText
    const module = { exports: {} }
    vm.runInNewContext(code, { ...globals, module, exports: module.exports, require: resolver })
    return module.exports
  }
  const storeModule = compile('src/stores/workspace.ts', name => require(name))
  const service = compile('src/services/fileSave.ts', name => (
    name.includes('workspace') ? storeModule : { API_BASE: 'http://fixture' }
  ))
  const store = storeModule.useWorkspaceStore
  store.getState().setProjectPath('C:/fixture')
  const file = { path: 'C:/fixture/a.py', name: 'a.py', language: 'python', content: 'base' }
  store.getState().openFile(file)
  store.getState().updateFileContent(file.path, 'snapshot-A')
  return { store, service, file, window, setFetch: fn => { fetchHandler = fn } }
}
const success = { ok: true, json: async () => ({}) }
const tick = () => new Promise(resolve => setImmediate(resolve))

test('save acknowledgement preserves edits made while the request was in flight', async () => {
  const { store, service, file, setFetch } = setup()
  let resolve
  setFetch(() => new Promise(done => { resolve = done }))
  const saving = service.saveFile(file.path)
  await tick()
  store.getState().updateFileContent(file.path, 'newer-B')
  resolve(success)
  await saving
  assert.equal(store.getState().openFiles[0].content, 'newer-B')
  assert.equal(store.getState().openFiles[0].isDirty, true)
})

test('writes are serialized and a stale document acknowledgement cannot mark a reopened file saved', async () => {
  const { store, service, file, setFetch } = setup()
  const calls = []
  const completions = []
  setFetch((_url, init) => new Promise(resolve => { calls.push(JSON.parse(init.body).content); completions.push(resolve) }))
  const first = service.saveFile(file.path)
  store.getState().updateFileContent(file.path, 'second')
  const second = service.saveFile(file.path)
  await tick()
  assert.deepEqual(calls, ['snapshot-A'])
  completions[0](success)
  await first
  await tick()
  assert.deepEqual(calls, ['snapshot-A', 'second'])
  store.getState().closeFile(file.path)
  store.getState().openFile(file)
  store.getState().updateFileContent(file.path, 'reopened')
  completions[1](success)
  await second
  assert.equal(store.getState().openFiles[0].isDirty, true)
  assert.equal(store.getState().openFiles[0].content, 'reopened')
})

for (const failure of ['network', 'http']) {
  test(`${failure} failure preserves dirty state and blocks compilation`, async () => {
    const { store, service, file, setFetch } = setup()
    setFetch(async () => {
      if (failure === 'network') throw new Error('offline')
      return { ok: false, status: 500, text: async () => 'write failed' }
    })
    await assert.rejects(service.saveForCompilation(file.path))
    assert.equal(store.getState().openFiles[0].isDirty, true)
  })
}

test('compilation rejects edits arriving during save', async () => {
  const { store, service, file, setFetch } = setup()
  setFetch(async () => { store.getState().updateFileContent(file.path, 'new'); return success })
  await assert.rejects(service.saveForCompilation(file.path), /保存期间/)
})

test('desktop fallback requires an actual successful write and cannot bypass HTTP rejection', async () => {
  const { store, service, file, setFetch, window } = setup()
  let calls = 0
  window.merakIDE = { fs: { writeFile: async () => { calls += 1; throw new Error('disk failure') } } }
  setFetch(async () => { throw new Error('offline') })
  await assert.rejects(service.saveFile(file.path), /disk failure/)
  assert.equal(store.getState().openFiles[0].isDirty, true)
  window.merakIDE.fs.writeFile = async () => { calls += 1 }
  setFetch(async () => ({ ok: false, status: 403, text: async () => 'denied' }))
  await assert.rejects(service.saveFile(file.path), /403/)
  assert.equal(calls, 1)
  setFetch(async () => { throw new Error('offline') })
  await service.saveFile(file.path)
  assert.equal(calls, 2)
  assert.equal(store.getState().openFiles[0].isDirty, false)
})

test('project switch and project close honor cancel without discarding tabs', () => {
  const { store, window } = setup()
  store.getState().setProjectPath('C:/other')
  store.getState().setProjectPath(null)
  assert.equal(store.getState().projectPath, 'C:/fixture')
  assert.equal(store.getState().openFiles.length, 1)
  window.confirm = () => true
  store.getState().setProjectPath('C:/other')
  assert.equal(store.getState().projectPath, 'C:/other')
  assert.equal(store.getState().openFiles.length, 0)
})
