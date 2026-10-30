/**
 * Start the development backend with the same bytecode isolation guarantees
 * as Electron. This launcher never starts workflows or experiments.
 */

const { existsSync } = require('fs')
const { join } = require('path')
const { spawn, spawnSync } = require('child_process')
const { PROBE_CODE } = require('./backend-probe.cjs')

const root = join(__dirname, '..')
const pythonEnvironment = {
  ...process.env,
  PYTHONPYCACHEPREFIX: join(root, '.backend-bytecode-cache'),
  PYTHONUTF8: '1',
  PYTHONUNBUFFERED: '1',
  MERAK_IDE_PORT: '8011',
}
delete pythonEnvironment.PYTHONDONTWRITEBYTECODE

function pythonCandidates() {
  const candidates = []
  if (process.env.MERAK_DEV_PYTHON) {
    if (!existsSync(process.env.MERAK_DEV_PYTHON)) {
      throw new Error(`MERAK_DEV_PYTHON does not exist: ${process.env.MERAK_DEV_PYTHON}`)
    }
    return [{ executable: process.env.MERAK_DEV_PYTHON, prefix: [] }]
  }
  const local = process.platform === 'win32'
    ? join(root, '.venv', 'Scripts', 'python.exe')
    : join(root, '.venv', 'bin', 'python')
  if (existsSync(local)) candidates.push({ executable: local, prefix: [] })
  if (process.env.CONDA_PREFIX) {
    const executable = process.platform === 'win32'
      ? join(process.env.CONDA_PREFIX, 'python.exe')
      : join(process.env.CONDA_PREFIX, 'bin', 'python')
    if (existsSync(executable)) candidates.push({ executable, prefix: [] })
  }
  candidates.push({ executable: process.platform === 'win32' ? 'python' : 'python3', prefix: [] })
  if (process.platform === 'win32') candidates.push({ executable: 'py', prefix: ['-3'] })
  return candidates.filter((candidate, index, all) => (
    all.findIndex(item => item.executable === candidate.executable) === index
  ))
}

function selectPython() {
  const failures = []
  for (const candidate of pythonCandidates()) {
    const probe = spawnSync(
      candidate.executable,
      [...candidate.prefix, '-c', PROBE_CODE],
      {
        cwd: root,
        env: pythonEnvironment,
        encoding: 'utf8',
        timeout: 20000,
        windowsHide: true,
      },
    )
    if (!probe.error && probe.status === 0) return candidate
    const detail = String(probe.error?.message || probe.stderr || `exit ${probe.status}`)
      .trim()
      .split(/\r?\n/)
      .slice(-2)
      .join(' ')
    failures.push(`${candidate.executable}: ${detail}`)
  }
  throw new Error(`No development Python has MERAK dependencies. Set MERAK_DEV_PYTHON. ${failures.join(' | ')}`)
}

function run() {
  const python = selectPython()
  if (process.argv.includes('--probe-only')) {
    console.log(`[Merak] Backend Python probe passed: ${python.executable}`)
    return
  }
  const args = [
    ...python.prefix,
    '-m', 'uvicorn', 'server.main:app',
    '--reload', '--host', '127.0.0.1', '--port', '8011',
  ]
  console.log(`[Merak] Backend Python: ${python.executable}`)
  console.log('[Merak] Backend endpoint: http://127.0.0.1:8011')
  const child = spawn(python.executable, args, {
    cwd: root,
    env: pythonEnvironment,
    stdio: 'inherit',
    windowsHide: true,
  })
  child.once('error', (error) => {
    console.error(`[Merak] Backend launch failed: ${error.message}`)
    process.exitCode = 1
  })
  child.once('exit', (code, signal) => {
    if (signal) console.error(`[Merak] Backend stopped by ${signal}`)
    process.exitCode = typeof code === 'number' ? code : 1
  })
}

try {
  run()
} catch (error) {
  console.error(`[Merak] ${error instanceof Error ? error.message : String(error)}`)
  process.exitCode = 1
}
