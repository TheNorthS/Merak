const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const ts = require('typescript')
const vm = require('node:vm')
const path = require('node:path')
function load(name, resolver) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', name), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: resolver })
  return module.exports
}
const nodes = load('shared/workflow-nodes.ts', require)
const { decodeWorkflowMessage } = load('src/components/workflow/workflowMessages.ts', () => nodes)
test('state changing events validate node and run identities', () => {
  for (const value of [[], null, {}, { type: 'node_started', node_id: 'unknown' },
    { type: 'workflow_completed' }, { type: 'node_failed', node_id: 'paper', run_id: 3 },
    { type: 'workflow_failed', run_id: 'r', nodes_status: [] }]) {
    assert.throws(() => decodeWorkflowMessage(JSON.stringify(value)))
  }
  assert.equal(decodeWorkflowMessage('{"type":"node_started","node_id":"paper","run_id":"r"}').node_id, 'paper')
})
test('shared node order follows every declared dependency', () => {
  const seen = new Set()
  for (const node of nodes.WORKFLOW_NODES) {
    assert.ok(node.depends_on.every(id => seen.has(id)))
    seen.add(node.id)
  }
})
