const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')

const sourcePath = path.resolve(__dirname, 'backend-startup-policy.ts')
const source = fs.readFileSync(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
})
const policyModule = new Module(sourcePath, module)
policyModule.filename = sourcePath
policyModule.paths = Module._nodeModulePaths(path.dirname(sourcePath))
policyModule._compile(compiled.outputText, sourcePath)
const { buildProbeArgs, classifyHealth, dedupePythonCandidates } = policyModule.exports

test('Python probe checks dependencies without importing the backend', () => {
  const args = buildProbeArgs()
  assert.deepEqual(args.slice(0, 2), ['-B', '-c'])
  assert.match(args[2], /find_spec/)
  assert.match(args[2], /sys\.version_info/)
  assert.match(args[2], /structlog/)
  assert.doesNotMatch(args[2], /server\.main|import server|uvicorn\.run/)
})

test('PATH and absolute spelling of one interpreter are probed once', () => {
  const explicit = process.execPath
  const executableName = path.basename(explicit, path.extname(explicit))
  const candidates = [
    { executable: explicit, prefix: [] },
    { executable: executableName, prefix: [] },
    { executable: explicit, prefix: ['-3'] },
    { executable: explicit, prefix: [] },
  ]
  const result = dedupePythonCandidates(
    candidates,
    process.platform,
    path.dirname(explicit),
  )
  assert.deepEqual(result, [candidates[0], candidates[2]])
})

test('unresolved PATH commands deduplicate without inventing an interpreter', () => {
  const candidates = [
    { executable: 'missing-python-command', prefix: [] },
    { executable: 'missing-python-command', prefix: [] },
    { executable: 'missing-python-command', prefix: ['-3'] },
  ]
  assert.deepEqual(
    dedupePythonCandidates(candidates, process.platform, ''),
    [candidates[0], candidates[2]],
  )
})

const healthy = {
  status: 'healthy',
  service: 'merak-ide-server',
  installation_sha256: 'installation-a',
}

test('health policy reuses only a healthy matching installation', () => {
  assert.equal(classifyHealth({ ...healthy, desktop_owner_token_sha256: 'owner-a' }, 'owner-a', 'installation-a', true), 'owned')
  assert.equal(classifyHealth(healthy, 'owner-a', 'installation-a', false), 'external-merak')
  assert.equal(classifyHealth({ ...healthy, installation_sha256: 'installation-b' }, 'owner-a', 'installation-a', false), 'foreign-merak')
  assert.equal(classifyHealth({ status: 'healthy', service: 'merak-ide-server' }, 'owner-a', 'installation-a', false), 'foreign-merak')
  assert.equal(classifyHealth({ ...healthy, status: 'starting' }, 'owner-a', 'installation-a', false), 'none')
  assert.equal(classifyHealth({ ...healthy, service: 'other-service' }, 'owner-a', 'installation-a', false), 'none')
})

test('health policy distinguishes a dead desktop owner from a live foreign owner', () => {
  const foreign = { ...healthy, desktop_owner_token_sha256: 'owner-b', desktop_owner_pid: 1234 }
  assert.equal(classifyHealth(foreign, 'owner-a', 'installation-a', false), 'stale-owned')
  assert.equal(classifyHealth(foreign, 'owner-a', 'installation-a', true), 'foreign-merak')
  assert.equal(classifyHealth({ ...foreign, desktop_owner_pid: null }, 'owner-a', 'installation-a', false), 'foreign-merak')
})
