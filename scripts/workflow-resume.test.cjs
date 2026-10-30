const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const ts = require('typescript')
const vm = require('node:vm')
const path = require('node:path')

const source = fs.readFileSync(path.join(__dirname, '../src/components/workflow/workflowEventTerminal.ts'), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const moduleScope = { exports: {} }
vm.runInNewContext(code, {
  module: moduleScope, exports: moduleScope.exports,
  require: () => ({ toNodeStatus: status => status, selectedNodeIdsFromRunState: () => new Set() }),
})
const { handleTerminalWorkflowEvent } = moduleScope.exports

for (const type of ['workflow_error', 'workflow_cancelled', 'workflow_interrupted']) {
  test(`${type} exposes a manual resume point immediately`, () => {
    let resume, nodes = [{ id: 'exp-design', status: 'running' }], running = true
    const context = {
      currentRunIdRef: { current: 'run' }, flushAgentOutput() {},
      setPausedRunIdSafe() {}, setNodes(update) { nodes = update(nodes) }, addLog() {},
      setResumableState(value) { resume = value }, setIsRunning(value) { running = value },
      setIsResuming() {}, setActiveRunId() {}, closeWorkflowWs() {},
    }
    handleTerminalWorkflowEvent({ type, run_id: 'run', current_node: 'exp-design',
      nodes_status: { 'exp-design': 'pending' }, config: { options: { run_experiment: false } } }, context)
    assert.equal(running, false)
    assert.equal(resume.run_id, 'run')
    assert.equal(resume.current_node, 'exp-design')
    assert.equal(resume.config.options.run_experiment, false)
    assert.equal(nodes[0].status, 'pending')
  })
}

test('request retry log distinguishes attempts from total node duration', () => {
  const logs = []
  handleTerminalWorkflowEvent({ type: 'agent_status', status: 'retrying_provider',
    next_attempt: 2, max_attempts: 2, retry_in_seconds: 2, remaining_seconds: 160 },
    { addLog: (...args) => logs.push(args) })
  assert.match(logs[0][1], /2\/2/)
  assert.match(logs[0][1], /160s/)
})
