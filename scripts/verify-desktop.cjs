/** Verify the packaged file:// renderer against its bundled backend in an empty profile. */
const assert = require('node:assert/strict')
const { spawn, spawnSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs')
const { rm } = require('node:fs/promises')
const net = require('node:net')
const path = require('node:path')
const { setTimeout: delay } = require('node:timers/promises')
const { probeDesktop } = require('./desktop-smoke-probes.cjs')
const { verifySessionStartup, probeSessionRecovery } = require('./desktop-session-smoke.cjs')
const root = path.resolve(__dirname, '..')
const release = path.join(root, 'release')
const appDirectory = path.resolve(process.argv[2] || path.join(release, 'win-unpacked'))
const inspectorSockets = new Map()

async function availablePort(port = 0) {
  const server = net.createServer()
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, '127.0.0.1', resolve)
  })
  const actual = server.address().port
  await new Promise(resolve => server.close(resolve))
  return actual
}

async function rendererTarget(child, port) {
  const deadline = Date.now() + 180000
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error('Packaged desktop exited before readiness')
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1000) })).json()
      const page = pages.find(item => item.type === 'page' && item.url.startsWith('file:') && item.url.includes('/dist/index.html'))
      const health = await (await fetch('http://127.0.0.1:8011/api/health', { signal: AbortSignal.timeout(1000) })).json()
      if (page && health.status === 'healthy' && health.desktop_owner_pid === child.pid) return page.webSocketDebuggerUrl
    } catch { /* Wait only within this fresh application's bounded startup. */ }
    await delay(500)
  }
  throw new Error('Packaged renderer/backend did not become ready')
}

async function inspectorCommand(address, method, params) {
  let socket = inspectorSockets.get(address)
  if (!socket || socket.readyState > WebSocket.OPEN) {
    socket = new WebSocket(address)
    inspectorSockets.set(address, socket)
  }
  return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Desktop probe timed out')), 45000)
      socket.onerror = () => { clearTimeout(timer); reject(new Error('Desktop inspector disconnected')) }
      const send = () => socket.send(JSON.stringify({ id: 1, method, params }))
      if (socket.readyState === WebSocket.OPEN) send()
      else socket.onopen = send
      socket.onmessage = event => {
        const message = JSON.parse(event.data)
        if (message.id !== 1) return
        clearTimeout(timer)
        if (message.error || message.result.exceptionDetails) reject(new Error(JSON.stringify(message)))
        else resolve(message.result)
      }
  })
}

async function evaluate(address, expression) {
  const result = await inspectorCommand(address, 'Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  return result.result.value
}

function verifySettingsDatabase(profile) {
  const script = path.join(profile, 'verify-settings.py')
  writeFileSync(script, [
    'import sqlite3', 'from pathlib import Path',
    'databases = list(Path(".").rglob("merak_ide.db"))', 'assert len(databases) == 1',
    'with sqlite3.connect(databases[0]) as db:',
    '    row = db.execute("SELECT value, updated_at FROM user_settings WHERE key = ?", ("models.openai_model",)).fetchone()',
    'assert row and row[0] == "desktop-storage-fixture" and row[1]',
  ].join('\n'))
  const executable = path.join(appDirectory, 'resources/server-bundle/runtime/win32-x64/merak-backend.exe')
  const result = spawnSync(executable, ['--run-figure-script', script], {
    cwd: profile, windowsHide: true, timeout: 30000, encoding: 'utf8',
    env: { SystemRoot: process.env.SystemRoot, PYTHONUTF8: '1', TEMP: profile, TMP: profile },
  })
  assert.equal(result.status, 0, result.error?.message || result.stderr)
}

async function stopDesktop(child, address, profile) {
  if (address && child.exitCode === null) {
    try { await evaluate(address, 'setTimeout(() => window.merakIDE.window.close(), 50); true') }
    catch { /* Fall back to terminating only the child created by this check. */ }
    const deadline = Date.now() + 10000
    while (child.exitCode === null && Date.now() < deadline) await delay(200)
  }
  if (child.pid && child.exitCode === null) {
    spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), delay(3000)])
  }
  for (const log of [path.join(profile, 'logs/backend.log'), path.join(profile, 'merak-ide/logs/backend.log')]) {
    if (existsSync(log)) writeFileSync(path.join(release, 'desktop-smoke.log'), readFileSync(log))
  }
  try { await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 }) }
  catch (error) { console.warn(`Desktop check profile retained at ${profile}: ${error.code}`) }
}

async function verifyDesktop() {
  assert.equal(process.platform, 'win32')
  await availablePort(8011) // Never attach this check to an existing user backend.
  const port = await availablePort()
  const profile = mkdtempSync(path.join(release, '.desktop-smoke-'))
  const resultPath = path.join(release, 'desktop-smoke.json')
  rmSync(resultPath, { force: true })
  const executable = path.join(appDirectory, 'Merak.exe')
  const env = { ...process.env, APPDATA: profile, LOCALAPPDATA: profile, TEMP: profile, TMP: profile }
  for (const key of Object.keys(env)) {
    if (/API_KEY|TOKEN|SECRET|PASSWORD|^(MERAK_|ANTHROPIC_|OPENAI_|CODEX_|CLAUDE_|ELECTRON_RUN_AS_NODE)/.test(key)) delete env[key]
  }
  const child = spawn(executable, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`], {
    cwd: profile, env, windowsHide: true, stdio: 'ignore',
  })
  let spawnError
  let address
  child.on('error', error => { spawnError = error })
  try {
    address = await rendererTarget(child, port)
    if (spawnError) throw spawnError
    const startup = await verifySessionStartup(address, inspectorCommand, evaluate)
    const recovery = await evaluate(address, `(${probeSessionRecovery.toString()})()`)
    assert.equal(recovery.passwordForm, false)
    assert.equal(recovery.reconnectOffered, true)
    assert.equal(recovery.recovered, true)
    const probe = await evaluate(address, `(${probeDesktop.toString()})()`)
    assert.deepEqual(probe.pings, ['pong', 'pong'], 'Workflow WebSocket must connect and reconnect')
    assert.equal(probe.chatPing, 'pong', 'Sidebar chat WebSocket must authenticate')
    assert.equal(probe.childDenied, true, 'Child frames must remain unauthorized')
    assert.equal(probe.settingsStatus, 200)
    assert.equal(probe.version, require('../package.json').version)
    assert.equal(probe.title, 'Merak')
    verifySettingsDatabase(profile)
    const asar = readFileSync(path.join(appDirectory, 'resources/app.asar'))
    const result = { accepted: true, ...probe, ...startup, session_recovery: recovery, settings_database_verified: true,
      asar_sha256: createHash('sha256').update(asar).digest('hex'),
      model_calls: 0, workflow_runs: 0, checked_at: new Date().toISOString() }
    writeFileSync(resultPath, JSON.stringify(result, null, 2) + '\n')
    console.log(JSON.stringify(result))
  } finally {
    await stopDesktop(child, address, profile)
    for (const socket of inspectorSockets.values()) socket.close()
    inspectorSockets.clear()
  }
}

verifyDesktop().catch(error => { console.error(error); process.exitCode = 1 })
