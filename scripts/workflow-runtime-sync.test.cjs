const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const ts = require('typescript')
const vm = require('node:vm')
const path = require('node:path')

function load(file, imports = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, fetch,
    require: name => imports[name] || {} })
  return module.exports
}
const { pollWorkflowRuntime } = load('src/components/workflow/workflowRuntimeSync.ts')
const { transportRecoveryNotice } = load('src/components/workflow/workflowTransportNotice.ts')
const { handleTerminalWorkflowEvent } = load('src/components/workflow/workflowEventTerminal.ts', {
  './workflowResume': { toNodeStatus: status => status === 'awaiting_revision' ? 'idle' : status,
    selectedNodeIdsFromRunState: state => new Set(Object.keys(state.nodes_status)) },
})
const reply = value => ({ ok: true, json: async () => value })
const run = { id: 'run', project_path: 'F:/research/test-1', status: 'incomplete', nodes: [{ id: 'lit', status: 'running' }] }
const durable = { run_id: 'run', status: 'incomplete', runtime_active: false,
  phases: { lit: { status: 'awaiting_revision' }, idea: { status: 'pending' } }, config: { direction: 'fixture' } }
function fixture() {
  const result = { running: true, resumed: null, active: 'run', nodes: [{ id: 'lit', status: 'running' }], binds: 0 }
  const context = {
    currentRunIdRef: { current: 'run' }, flushAgentOutput() {}, setPausedRunIdSafe() {},
    setNodes(update) { result.nodes = update(result.nodes) }, addLog() {},
    setResumableState(value) { result.resumed = value }, setIsRunning(value) { result.running = value },
    setIsResuming() {}, setActiveRunId(value) { result.active = value }, closeWorkflowWs() {},
    revisionLimitCheckpointRef: { current: null },
  }
  const poll = { base: '', projectPath: 'F:\\research\\test-1', currentRunId: 'run', stopped: new Set(),
    isCurrent: () => true, onRunning() { result.binds++ },
    onTerminal(event) { handleTerminalWorkflowEvent(event, context) } }
  return { poll, result }
}

test('a lost terminal push is repaired by HTTP 200 incomplete status and exposes manual resume', async () => {
  const { poll, result } = fixture()
  const requests = []
  await pollWorkflowRuntime(poll, async url => { requests.push(url); return reply(requests.length === 1 ? [run] : durable) })
  assert.equal(result.running, false)
  assert.equal(result.active, null)
  assert.equal(result.resumed.run_id, 'run')
  assert.equal(result.resumed.current_node, 'lit')
  assert.equal(result.nodes[0].status, 'idle')
  assert.equal(requests.length, 2)
})

test('a delayed running response cannot overwrite a more recent terminal event', async () => {
  const { poll, result } = fixture()
  let current = true, complete
  poll.isCurrent = () => current
  const pending = pollWorkflowRuntime(poll, () => new Promise(resolve => { complete = resolve }))
  current = false
  complete(reply([{ ...run, status: 'running' }]))
  await pending
  assert.equal(result.binds, 0)
})

test('an old terminal snapshot cannot interrupt a new manual resume', async () => {
  const { poll, result } = fixture()
  let current = true, release
  poll.isCurrent = () => current
  const pending = pollWorkflowRuntime(poll, async url => url.endsWith('/runs') ? reply([run]) : new Promise(resolve => { release = resolve }))
  while (!release) await Promise.resolve()
  current = false
  release(reply(durable))
  await pending
  assert.equal(result.running, true)
  assert.equal(result.resumed, null)
})

test('after backend restart a durable checkpoint ends the stale running display', async () => {
  const { poll, result } = fixture()
  await pollWorkflowRuntime(poll, async url => reply(url.endsWith('/runs') ? [] : durable))
  assert.equal(result.running, false)
  assert.equal(result.resumed.run_id, 'run')
})

test('manual stop, foreign project, and HTTP failure cannot bind a phantom run', async () => {
  for (const snapshot of [[{ ...run, status: 'running', project_path: 'F:/other' }], [{ ...run, status: 'running' }]]) {
    const { poll, result } = fixture()
    poll.currentRunId = null
    poll.stopped.add('run')
    await pollWorkflowRuntime(poll, async () => reply(snapshot))
    assert.equal(result.binds, 0)
  }
  const { poll, result } = fixture()
  await pollWorkflowRuntime(poll, async () => ({ ok: false }))
  assert.equal(result.running, true)
})

test('transport interruption never advertises an unscheduled automatic retry', () => {
  assert.match(transportRecoveryNotice({ transport_exhausted: true, max_transport_checkpoint_retries: 0 }), /手动恢复/)
  assert.match(transportRecoveryNotice({ transport_exhausted: true, retry_delay_seconds: 10, max_transport_checkpoint_retries: 2, manual_resume_required: true }), /手动恢复/)
  assert.match(transportRecoveryNotice({ transport_exhausted: true, retry_delay_seconds: 10, max_transport_checkpoint_retries: 2 }), /10 秒/)
})

test('a saved resumable run can be reconciled after another window finishes it', async () => {
  const { poll } = fixture()
  let event
  poll.onTerminal = value => { event = value }
  await pollWorkflowRuntime(poll, async url => reply(url.endsWith('/runs')
    ? [{ ...run, status: 'completed', completion: { completion_class: 'reviewable_draft_ready' } }]
    : { ...durable, status: 'completed', phases: { lit: { status: 'accepted' } } }))
  assert.equal(event.type, 'workflow_completed')
  assert.equal(event.run_id, 'run')
  assert.equal(event.completion_class, 'reviewable_draft_ready')
})
