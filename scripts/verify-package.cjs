/** Start the shipped backend without host Python or personal settings. */
const assert = require('node:assert/strict')
const { spawn, spawnSync } = require('node:child_process')
const { createHash, randomBytes } = require('node:crypto')
const { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs')
const net = require('node:net')
const path = require('node:path')
const { setTimeout: delay } = require('node:timers/promises')
const { sourceDigest, verifyBundledSources } = require('./build-backend.js')

const root = path.resolve(__dirname, '..')
const release = path.join(root, 'release')
const runtime = path.join(release, 'win-unpacked/resources/server-bundle/runtime/win32-x64')
const sha256 = data => createHash('sha256').update(data).digest('hex')

async function unusedPort() {
  const server = net.createServer()
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  return port
}

function verifyArchive() {
  const asar = require('@electron/asar')
  const archive = path.join(release, 'win-unpacked/resources/app.asar')
  const files = asar.listPackage(archive).map(item => item.replaceAll('\\', '/'))
  assert(files.includes('/dist/index.html'), 'Renderer entry is missing')
  assert(files.includes('/dist-electron/main.js'), 'Electron entry is missing')
  const html = asar.extractFile(archive, 'dist/index.html').toString('utf8')
  assert(!/(?:src|href)=["']\/(?!\/)/.test(html), 'Renderer assets must use relative paths for file://')
  assert(!files.some(item => /\/(?:\.env|user_settings\.json|[^/]+\.(?:db|sqlite3?))$/.test(item)), 'Private data in application archive')
  assert(!files.some(item => /^\/(?:output|server\/tests|node_modules)\//.test(item)), 'Development files in application archive')
}

async function waitUntilHealthy(child, base, token) {
  const deadline = Date.now() + 180000
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode) throw new Error('Bundled backend exited during startup')
    try {
      const response = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(1500) })
      const data = await response.json()
      if (response.ok && data.status === 'healthy' && data.service === 'merak-ide-server'
          && data.desktop_owner_token_sha256 === sha256(token)) return data
    } catch (error) {
      if (child.exitCode !== null) throw error
    }
    await delay(500)
  }
  throw new Error('Bundled backend did not become healthy within 180 seconds')
}

function verifyPlotRuntime(executable, temporary, systemRoot) {
  const script = path.join(temporary, 'package-plot-check.py')
  writeFileSync(script, [
    'import matplotlib', 'matplotlib.use("Agg")', 'import matplotlib.pyplot as plt',
    'import numpy, pandas, PIL, pypdf, pymupdf, pptx',
    'plt.plot([0, 1], [0, 1])', 'plt.savefig("package-plot-check.png")', 'plt.close()',
  ].join('\n'))
  const result = spawnSync(executable, ['--run-figure-script', script], {
    cwd: temporary, windowsHide: true, encoding: 'utf8', timeout: 90000,
    env: { SystemRoot: systemRoot, WINDIR: systemRoot, PATH: path.join(systemRoot, 'System32'),
      USERPROFILE: temporary, APPDATA: temporary, LOCALAPPDATA: temporary,
      TEMP: temporary, TMP: temporary, PYTHONUTF8: '1' },
  })
  assert.equal(result.status, 0, `Bundled plotting failed: ${result.error || result.stderr}`)
  assert(existsSync(path.join(temporary, 'package-plot-check.png')), 'Plot runtime produced no image')
}

function verifyResumeRuntime(executable, temporary, systemRoot) {
  const result = spawnSync(executable, ['--run-figure-script', path.join(root, 'scripts/verify_resume_runtime.py')], {
    cwd: temporary, windowsHide: true, encoding: 'utf8', timeout: 90000,
    env: { SystemRoot: systemRoot, WINDIR: systemRoot, PATH: path.join(systemRoot, 'System32'),
      USERPROFILE: temporary, APPDATA: temporary, LOCALAPPDATA: temporary, TEMP: temporary, TMP: temporary,
      MERAK_IDE_DATA_DIR: temporary, MERAK_IDE_MERAK_SKILLS_PATH: path.join(runtime, '_internal/merak-skills'),
      MERAK_SKILLS_PATH: path.join(runtime, '_internal/merak-skills'), PYTHONUTF8: '1' },
  })
  assert.equal(result.status, 0, `Bundled resume fingerprints failed: ${result.error || result.stderr}`)
  const receipt = JSON.parse(readFileSync(path.join(temporary, 'resume-smoke.json'), 'utf8'))
  assert.equal(receipt.nodes_checked.length, 13)
  writeFileSync(path.join(release, 'resume-smoke.json'), JSON.stringify(receipt, null, 2) + '\n')
}

async function verifyPackage() {
  assert.equal(process.platform, 'win32', 'Package smoke test requires Windows')
  const executable = path.join(runtime, 'merak-backend.exe')
  assert(existsSync(executable), 'Run npm run build first')
  const manifest = JSON.parse(readFileSync(path.join(runtime, 'merak-bundle.json'), 'utf8'))
  assert.equal(manifest.source_sha256, sourceDigest(), 'Package backend is stale')
  assert.equal(manifest.executable_sha256, sha256(readFileSync(executable)))
  verifyBundledSources(path.join(runtime, '_internal'))
  verifyArchive()
  mkdirSync(release, { recursive: true })
  rmSync(path.join(release, 'package-smoke.json'), { force: true })
  const temporary = mkdtempSync(path.join(release, '.smoke-'))
  const token = randomBytes(32).toString('hex')
  const port = await unusedPort()
  const systemRoot = process.env.SystemRoot || 'C:\\Windows'
  const child = spawn(executable, ['--host', '127.0.0.1', '--port', String(port)], {
    cwd: temporary, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { SystemRoot: systemRoot, WINDIR: systemRoot, PATH: path.join(systemRoot, 'System32'),
      USERPROFILE: temporary, APPDATA: temporary, LOCALAPPDATA: temporary,
      TEMP: temporary, TMP: temporary, PYTHONUTF8: '1',
      MERAK_IDE_MERAK_SKILLS_PATH: path.join(runtime, '_internal/merak-skills'),
      MERAK_SKILLS_PATH: path.join(runtime, '_internal/merak-skills'),
      MERAK_DESKTOP_OWNER_TOKEN: token, MERAK_DESKTOP_OWNER_PID: String(process.pid),
      MERAK_IDE_DATA_DIR: temporary, MERAK_IDE_WORKSPACE_ROOT: path.join(temporary, 'projects') },
  })
  let log = ''
  let spawnError
  child.on('error', error => { spawnError = error })
  for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => { log = (log + chunk).slice(-64000) })
  try {
    const base = `http://127.0.0.1:${port}`
    const health = await waitUntilHealthy(child, base, token)
    if (spawnError) throw spawnError
    const denied = await fetch(`${base}/api/merak/skills`, { signal: AbortSignal.timeout(10000) })
    assert.equal(denied.status, 401, 'Unauthenticated access must be rejected')
    const response = await fetch(`${base}/api/merak/skills`, {
      headers: { 'X-Merak-Owner-Token': token }, signal: AbortSignal.timeout(10000),
    })
    assert.equal(response.status, 200, 'Desktop capability must authenticate')
    const skills = await response.json()
    assert(Array.isArray(skills) && skills.some(skill => skill.id === 'domain-experiment-plan'), 'Packaged research skills are missing')
    verifyPlotRuntime(executable, temporary, systemRoot)
    verifyResumeRuntime(executable, temporary, systemRoot)
    const result = { accepted: true, version: require('../package.json').version,
      backend_source_sha256: manifest.source_sha256, executable_sha256: manifest.executable_sha256,
      checked_at: new Date().toISOString(), health: health.status, skill_count: skills.length,
      authentication_checked: true, host_python_required: false, bundled_plot_rendered: true, resume_fingerprints_verified: true,
      model_calls: 0, workflow_runs: 0 }
    writeFileSync(path.join(release, 'package-smoke.json'), JSON.stringify(result, null, 2) + '\n')
    console.log(JSON.stringify(result))
  } finally {
    if (child.pid && child.exitCode === null) {
      spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
      await Promise.race([new Promise(resolve => child.once('exit', resolve)), delay(3000)])
    }
    writeFileSync(path.join(release, 'package-smoke.log'), log)
    rmSync(temporary, { recursive: true, force: true, maxRetries: 3, retryDelay: 300 })
  }
}

verifyPackage().catch(error => { console.error(error); process.exitCode = 1 })
