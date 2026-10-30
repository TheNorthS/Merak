/** Validate release identity and bind installer checksums to its successful smoke test. */
const assert = require('node:assert/strict')
const { execFileSync, spawnSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const { existsSync, readFileSync, writeFileSync } = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const version = require('../package.json').version

function checkVersion() {
  const lock = JSON.parse(readFileSync(path.join(root, 'package-lock.json'), 'utf8'))
  const python = readFileSync(path.join(root, 'pyproject.toml'), 'utf8')
  assert.equal(lock.version, version)
  assert.equal(lock.packages[''].version, version)
  assert.equal(python.match(/^version\s*=\s*"([^"]+)"/m)?.[1], version, 'Python and Electron versions differ')
  if (process.env.GITHUB_REF_TYPE === 'tag') {
    assert.equal(process.env.GITHUB_REF_NAME, `v${version}`, 'Tag does not match application version')
  }
}

function generateChecksums() {
  checkVersion()
  const directory = path.join(root, 'release')
  const filename = `Merak-Setup-${version}-x64.exe`
  const installer = path.join(directory, filename)
  assert(existsSync(installer), `Missing ${filename}`)
  const smoke = JSON.parse(readFileSync(path.join(directory, 'package-smoke.json'), 'utf8'))
  assert.equal(smoke.accepted, true)
  assert.equal(smoke.version, version)
  const manifest = JSON.parse(readFileSync(path.join(directory,
    'win-unpacked/resources/server-bundle/runtime/win32-x64/merak-bundle.json'), 'utf8'))
  assert.equal(smoke.backend_source_sha256, manifest.source_sha256)
  assert.equal(smoke.executable_sha256, manifest.executable_sha256)
  const desktop = JSON.parse(readFileSync(path.join(directory, 'desktop-smoke.json'), 'utf8'))
  assert.equal(desktop.accepted, true)
  assert.equal(desktop.version, version)
  const asar = readFileSync(path.join(directory, 'win-unpacked/resources/app.asar'))
  assert.equal(desktop.asar_sha256, createHash('sha256').update(asar).digest('hex'))
  const bytes = readFileSync(installer)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  let commit = null
  let workingTreeModified = null
  if (existsSync(path.join(root, '.git'))) {
    const revision = spawnSync('git', ['rev-parse', '--verify', '--quiet', 'HEAD'], { cwd: root, encoding: 'utf8' })
    assert(!revision.error && [0, 1].includes(revision.status), 'Cannot inspect Git revision')
    commit = revision.status === 0 ? revision.stdout.trim() : null
    workingTreeModified = Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim())
  }
  const info = { version, platform: 'win32', arch: 'x64', commit,
    working_tree_modified: workingTreeModified, built_at: new Date().toISOString(),
    filename, size_bytes: bytes.length, sha256, code_signed: false,
    backend_source_sha256: manifest.source_sha256, smoke, desktop_smoke: desktop }
  writeFileSync(path.join(directory, 'SHA256SUMS.txt'), `${sha256}  ${filename}\n`)
  writeFileSync(path.join(directory, 'build-info.json'), JSON.stringify(info, null, 2) + '\n')
  console.log(`${filename}: ${sha256}`)
}

try {
  if (process.argv.includes('--check-version')) checkVersion()
  else generateChecksums()
} catch (error) { console.error(error.message); process.exitCode = 1 }
