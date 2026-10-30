const assert = require('node:assert/strict')
const test = require('node:test')
const fs = require('node:fs')
const ts = require('typescript')
const vm = require('node:vm')
const path = require('node:path')

function load(plan, approve) {
  const requests = [], questions = []
  const module = { exports: {} }
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/components/workflow/evidenceVersionApproval.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: () => ({ API_BASE: '' }),
    fetch: async url => { requests.push(url); return { ok: true, json: async () => plan } },
    confirm: question => { questions.push(question); return approve },
  })
  return { request: module.exports.evidenceVersionApproval, requests, questions }
}

test('unchanged evidence requires no approval and performs only a read', async () => {
  const fixture = load({ required: false }, true)
  assert.equal(await fixture.request('project', 'run'), undefined)
  assert.equal(fixture.questions.length, 0)
  assert.match(fixture.requests[0], /evidence-version-plan/)
})

test('cancelled evidence replacement does not produce authorization', async () => {
  const fixture = load({ required: true, changed_sources: ['experiments/RUN_SPEC.json'], input_sha256: 'new', manifest_sha256: 'old' }, false)
  assert.equal(await fixture.request('project', 'run'), null)
  assert.match(fixture.questions[0], /RUN_SPEC/)
})

test('approval binds both the reviewed new input and exact old manifest', async () => {
  const fixture = load({ required: true, changed_sources: ['config'], input_sha256: 'new', manifest_sha256: 'old' }, true)
  const approval = await fixture.request('project', 'run')
  assert.equal(approval.input_sha256, 'new')
  assert.equal(approval.manifest_sha256, 'old')
})
