/** Backend launch selection and local health discovery for the desktop process. */

import { execFile } from 'child_process'
import { createHash } from 'crypto'
import { app } from 'electron'
import { existsSync, readdirSync } from 'fs'
import http from 'http'
import net from 'net'
import { basename, dirname, join } from 'path'
import {
  buildProbeArgs,
  classifyHealth,
  dedupePythonCandidates,
  type HealthClassification,
  type PythonCandidate,
} from './backend-startup-policy'

const HEALTH_CHECK_INTERVAL = 1000
const HEALTH_CHECK_TIMEOUT = 300000

export interface BackendLaunch {
  executable: string
  args: string[]
  packaged: boolean
}

export interface ReadyWaitCallbacks {
  isCancelled: () => boolean
  onReady: () => void
  onTimeout: () => void
}

export class BackendStartupService {
  readonly projectRoot: string
  readonly installationSha256: string
  private readonly rejectedDevelopmentInterpreters = new Set<string>()
  private healthCheckTimer: ReturnType<typeof setTimeout> | null = null
  private cancelPendingReadyWait: (() => void) | null = null

  constructor(
    private readonly ownerTokenSha256: string,
    private readonly appendLog: (line: string) => void,
  ) {
    this.projectRoot = this.resolveProjectRoot()
    this.installationSha256 = createHash('sha256')
      .update(this.projectRoot.replace(/\\/g, '/').toLowerCase())
      .digest('hex')
  }

  /** Keep validated bytecode caches outside mutable Conda environments. */
  pythonEnvironment(): NodeJS.ProcessEnv {
    const environment: NodeJS.ProcessEnv = {
      ...process.env,
      PYTHONPYCACHEPREFIX: join(
        app.getPath('userData'), 'python-bytecode-cache', this.installationSha256,
      ),
      PYTHONUTF8: '1',
    }
    delete environment.PYTHONDONTWRITEBYTECODE
    return environment
  }

  rejectDevelopmentInterpreter(executable: string): void {
    this.rejectedDevelopmentInterpreters.add(executable)
  }

  clearRejectedDevelopmentInterpreters(): void {
    this.rejectedDevelopmentInterpreters.clear()
  }

  /** Packaged builds never search the host for Python. */
  async selectBackendLaunch(port: number): Promise<BackendLaunch | null> {
    if (app.isPackaged) {
      const executable = join(
        this.projectRoot, 'runtime', `${process.platform}-${process.arch}`,
        process.platform === 'win32' ? 'merak-backend.exe' : 'merak-backend',
      )
      if (!existsSync(executable)) {
        throw new Error(`Installation is incomplete: bundled MERAK backend is missing (${executable})`)
      }
      return { executable, args: ['--host', '127.0.0.1', '--port', String(port)], packaged: true }
    }
    for (const candidate of this.pythonCandidates()) {
      if (this.rejectedDevelopmentInterpreters.has(candidate.executable)) continue
      if (await this.probePython(candidate)) {
        return {
          executable: candidate.executable,
          args: [...candidate.prefix, '-m', 'uvicorn', 'server.main:app',
            '--host', '127.0.0.1', '--port', String(port)],
          packaged: false,
        }
      }
    }
    return null
  }

  isPortAvailable(port: number): Promise<boolean> {
    return new Promise((resolve) => {
      const server = net.createServer()
      server.once('error', () => resolve(false))
      server.once('listening', () => { server.close(); resolve(true) })
      server.listen(port, '127.0.0.1')
    })
  }

  /** Distinguish owned, orphaned, external, and foreign local listeners. */
  probeExistingBackend(port: number): Promise<HealthClassification> {
    return new Promise((resolve) => {
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        let body = ''
        res.on('data', (chunk) => { body += chunk })
        res.on('end', () => {
          try {
            const data = JSON.parse(body)
            const ownerPid = Number(data?.desktop_owner_pid)
            let ownerAlive = true
            if (Number.isSafeInteger(ownerPid) && ownerPid > 0) {
              try { process.kill(ownerPid, 0) } catch (error) {
                ownerAlive = (error as NodeJS.ErrnoException).code !== 'ESRCH'
              }
            }
            resolve(classifyHealth(
              data, this.ownerTokenSha256, this.installationSha256, ownerAlive,
            ))
          } catch { resolve('none') }
        })
      })
      req.on('error', () => resolve('none'))
      req.setTimeout(3000, () => { req.destroy(); resolve('none') })
    })
  }

  /** Wait only for a listener already holding the canonical port. */
  async waitForExistingBackend(port: number, timeoutMs = 8000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      const backend = await this.probeExistingBackend(port)
      if (backend === 'owned' || backend === 'external-merak') return true
      if (await this.isPortAvailable(port)) return false
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
    const backend = await this.probeExistingBackend(port)
    return backend === 'owned' || backend === 'external-merak'
  }

  /** Poll only for the just-spawned owned server; cancellation always settles. */
  waitForReady(port: number, callbacks: ReadyWaitCallbacks): Promise<void> {
    this.cancelReadyWait()
    return new Promise((resolve) => {
      const start = Date.now()
      let finished = false
      let retryScheduled = false
      let activeRequest: ReturnType<typeof http.get> | null = null
      const finish = () => {
        if (finished) return
        finished = true
        if (this.healthCheckTimer) clearTimeout(this.healthCheckTimer)
        this.healthCheckTimer = null
        this.cancelPendingReadyWait = null
        resolve()
      }
      this.cancelPendingReadyWait = () => {
        finish()
        activeRequest?.destroy()
      }
      const scheduleRetry = () => {
        if (finished || retryScheduled) return
        if (Date.now() - start > HEALTH_CHECK_TIMEOUT) {
          callbacks.onTimeout()
          finish()
        } else {
          retryScheduled = true
          this.healthCheckTimer = setTimeout(check, HEALTH_CHECK_INTERVAL)
        }
      }
      const check = () => {
        retryScheduled = false
        if (callbacks.isCancelled()) return finish()
        activeRequest = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
          let body = ''
          res.on('data', (chunk) => { body += chunk })
          res.on('end', () => {
            try {
              const data = JSON.parse(body)
              if (
                data.status === 'healthy'
                && data.service === 'merak-ide-server'
                && data.desktop_owner_token_sha256 === this.ownerTokenSha256
              ) {
                callbacks.onReady()
                finish()
                return
              }
            } catch { /* retry */ }
            scheduleRetry()
          })
        })
        activeRequest.on('error', scheduleRetry)
        activeRequest.setTimeout(2000, () => { activeRequest?.destroy(); scheduleRetry() })
      }
      check()
    })
  }

  cancelReadyWait(): void {
    this.cancelPendingReadyWait?.()
  }

  private resolveProjectRoot(): string {
    if (!app.isPackaged) {
      const candidates = [app.getAppPath(), join(__dirname, '..'), process.cwd()]
      for (const candidate of candidates) {
        if (
          existsSync(join(candidate, 'package.json'))
          && existsSync(join(candidate, 'server', 'main.py'))
        ) return candidate
      }
      return app.getAppPath()
    }
    return join(process.resourcesPath, 'server-bundle')
  }

  /** Probe interpreter metadata; the full application imports only at spawn. */
  private probePython(candidate: PythonCandidate): Promise<boolean> {
    return new Promise((resolve) => {
      execFile(candidate.executable, [...candidate.prefix, ...buildProbeArgs()], {
        cwd: this.projectRoot, timeout: 20000,
        env: this.pythonEnvironment(), windowsHide: true,
      }, (error, _stdout, stderr) => {
        if (!error) return resolve(true)
        const detail = String(stderr || error.message || 'probe failed')
          .replace(/\s+/g, ' ').trim().slice(-800)
        this.appendLog(`[backend] Python probe rejected ${candidate.executable}: ${detail}`)
        resolve(false)
      })
    })
  }

  private pythonCandidates(): PythonCandidate[] {
    const candidates: PythonCandidate[] = []
    const add = (executable: string, prefix: string[] = []) => {
      if (existsSync(executable)) candidates.push({ executable, prefix })
    }
    if (process.env.MERAK_DEV_PYTHON) {
      if (!existsSync(process.env.MERAK_DEV_PYTHON)) {
        throw new Error(`MERAK_DEV_PYTHON does not exist: ${process.env.MERAK_DEV_PYTHON}`)
      }
      return [{ executable: process.env.MERAK_DEV_PYTHON, prefix: [] }]
    }
    for (const prefix of ['.venv', 'venv']) {
      add(join(this.projectRoot, prefix, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'))
    }
    if (process.env.CONDA_PREFIX) {
      add(join(process.env.CONDA_PREFIX, process.platform === 'win32' ? 'python.exe' : 'bin/python'))
    }
    candidates.push(...(process.platform === 'win32'
      ? [{ executable: 'python', prefix: [] }, { executable: 'py', prefix: ['-3'] }]
      : [{ executable: 'python3', prefix: [] }, { executable: 'python', prefix: [] }]))
    for (const directory of String(process.env.PATH || '').split(process.platform === 'win32' ? ';' : ':')) {
      const python = join(directory, process.platform === 'win32' ? 'python.exe' : 'python')
      if (directory && existsSync(python)) candidates.push({ executable: python, prefix: [] })
    }
    const prefixes = new Set<string>()
    if (process.env.CONDA_PREFIX) {
      const active = process.env.CONDA_PREFIX
      prefixes.add(basename(dirname(active)).toLowerCase() === 'envs'
        ? dirname(dirname(active)) : active)
    }
    for (const candidate of candidates) {
      if (candidate.executable.toLowerCase().includes('python') && existsSync(candidate.executable)) {
        const directory = dirname(candidate.executable)
        prefixes.add(basename(dirname(directory)).toLowerCase() === 'envs'
          ? dirname(dirname(directory)) : directory)
      }
    }
    for (const prefix of prefixes) {
      try {
        for (const entry of readdirSync(join(prefix, 'envs'), { withFileTypes: true })) {
          if (entry.isDirectory()) {
            add(join(prefix, 'envs', entry.name, process.platform === 'win32' ? 'python.exe' : 'bin/python'))
          }
        }
      } catch {
        // Conda siblings are optional and searched only after preferred candidates.
      }
    }
    return dedupePythonCandidates(candidates, process.platform, process.env.PATH || '')
  }
}
