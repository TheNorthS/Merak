import { handleTrusted } from '../trusted-ipc'
/**
 * 后端进程管理器 — Electron 主进程自动启动/管理 Python 后端
 *
 * 职责：
 * - 定位 Python 解释器
 * - spawn uvicorn 子进程
 * - 安全复用用户显式启动的本地 MERAK 后端
 * - 健康检查轮询
 * - 崩溃自动重启（指数退避，最多 3 次）
 * - 日志收集（ring buffer）
 * - 进程清理（graceful + force kill）
 */

import { spawn, execSync, ChildProcess } from 'child_process'
import { app } from 'electron'
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
} from 'fs'
import { dirname, join } from 'path'
import http from 'http'
import { createHash, randomUUID } from 'crypto'
import { BackendStartupService, type BackendLaunch } from './backend-startup-service'
import { installBackendRequestAuth } from '../backend-request-auth'
import type { BrowserWindow } from 'electron'

export type BackendStatus = 'stopped' | 'starting' | 'ready' | 'error' | 'restarting'

interface BackendState {
  status: BackendStatus
  port: number
  pid: number | null
  error: string | null
  restartCount: number
}

const MAX_LOG_LINES = 500
const MAX_RESTART_ATTEMPTS = 3
const STABLE_RUN_RESET_MS = 60000
const BASE_PORT = 8011
const MAX_PERSISTED_LOG_BYTES = 2 * 1024 * 1024

class BackendManager {
  authorizeRenderer(window: BrowserWindow): void {
    installBackendRequestAuth(window, this.ownerToken)
  }
  private process: ChildProcess | null = null
  private state: BackendState = {
    status: 'stopped',
    port: BASE_PORT,
    pid: null,
    error: null,
    restartCount: 0,
  }
  private logs: string[] = []
  private statusListeners: Array<(state: BackendState) => void> = []
  private stableRunTimer: ReturnType<typeof setTimeout> | null = null
  private startPromise: Promise<void> | null = null
  private stopPromise: Promise<void> | null = null
  private restartPromise: Promise<void> | null = null
  private stopping = false
  private readonly ownerToken = randomUUID()
  private readonly ownerTokenSha256 = createHash('sha256').update(this.ownerToken).digest('hex')
  private readonly backendLogPath: string
  private readonly startup: BackendStartupService

  constructor() {
    this.startup = new BackendStartupService(this.ownerTokenSha256, (line) => this.appendLog(line))
    this.backendLogPath = join(app.getPath('userData'), 'logs', 'backend.log')
    this.rotatePersistedLog()
    this.loadPersistedLog()
  }

  private rotatePersistedLog(): void {
    try {
      mkdirSync(join(app.getPath('userData'), 'logs'), { recursive: true })
      if (!existsSync(this.backendLogPath)) return
      if (statSync(this.backendLogPath).size <= MAX_PERSISTED_LOG_BYTES) return
      const previous = `${this.backendLogPath}.previous`
      rmSync(previous, { force: true })
      renameSync(this.backendLogPath, previous)
    } catch {
      // File logging is diagnostic-only and must never block backend startup.
    }
  }

  private loadPersistedLog(): void {
    try {
      if (!existsSync(this.backendLogPath)) return
      this.logs = readFileSync(this.backendLogPath, 'utf8')
        .split(/\r?\n/)
        .filter(Boolean)
        .slice(-MAX_LOG_LINES)
    } catch {
      this.logs = []
    }
  }

  /** 启动后端 */
  async start(): Promise<void> {
    if (this.stopPromise) await this.stopPromise
    if (this.state.status === 'ready') return
    if (this.startPromise) return this.startPromise
    const pending = this.startOnce()
    this.startPromise = pending
    try {
      await pending
    } finally {
      if (this.startPromise === pending) this.startPromise = null
    }
  }

  private async startOnce(): Promise<void> {
    if (this.state.status === 'ready' || this.state.status === 'starting') return

    this.stopping = false
    this.setState({ status: 'starting', error: null })

    // 先检查端口是否已有 MERAK 后端在跑
    const existingBackend = await this.startup.probeExistingBackend(BASE_PORT)
    if (this.stopping) return
    if (existingBackend === 'owned') {
      this.appendLog('[backend] Backend owned by this desktop session detected; reusing.')
      this.setState({ status: 'ready', port: BASE_PORT, pid: null })
      return
    }
    if (existingBackend === 'external-merak') {
      this.appendLog('[backend] External local MERAK server detected; reusing without taking process ownership.')
      this.setState({ status: 'ready', port: BASE_PORT, pid: null })
      return
    }
    if (existingBackend === 'stale-owned') {
      const error = `Backend port ${BASE_PORT} contains an orphaned MERAK server from a previous desktop session. Stop that process before restarting Merak.`
      this.appendLog(`[backend] ERROR: ${error}`)
      this.setState({ status: 'error', error })
      return
    }
    if (existingBackend === 'foreign-merak') {
      const error = `Backend port ${BASE_PORT} is occupied by an MERAK server from another or stale desktop session.`
      this.appendLog(`[backend] ERROR: ${error}`)
      this.setState({ status: 'error', error })
      return
    }

    // Another Electron/backend process may have bound 8011 but not completed
    // FastAPI startup yet. Wait for that process instead of immediately
    // spawning a second long-lived backend on 8002.
    const basePortAvailable = await this.startup.isPortAvailable(BASE_PORT)
    if (this.stopping) return
    if (!basePortAvailable) {
      const becameReady = await this.startup.waitForExistingBackend(BASE_PORT)
      if (this.stopping) return
      if (becameReady) {
        this.appendLog('[backend] Merak server became ready during startup; reusing.')
        this.setState({ status: 'ready', port: BASE_PORT, pid: null })
        return
      }
    }

    // Packaged builds use only their bundled executable; development probes
    // interpreter metadata without importing the application a second time.
    let launch: BackendLaunch | null
    try {
      launch = await this.startup.selectBackendLaunch(BASE_PORT)
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      this.appendLog(`[backend] ERROR: ${detail}`)
      this.setState({ status: 'error', error: detail })
      return
    }
    if (!launch) {
      const err = 'No development Python has the required MERAK dependencies. Set MERAK_DEV_PYTHON to an installed environment.'
      this.appendLog(`[backend] ERROR: ${err}`)
      this.setState({ status: 'error', error: err })
      return
    }
    if (this.stopping) return
    this.appendLog(`[backend] Using ${launch.packaged ? 'bundled backend' : 'development Python'}: ${launch.executable}`)

    // The renderer's production API contract is fixed to 8011. Starting on a
    // different port would report the backend as ready while every UI request
    // still targets 8011, producing an endless loading screen. Fail clearly
    // when another non-MERAK process owns the canonical port.
    const port = BASE_PORT
    if (!(await this.startup.isPortAvailable(port))) {
      const becameReady = await this.startup.waitForExistingBackend(port)
      if (this.stopping) return
      if (becameReady) {
        this.appendLog('[backend] Merak server won the port race; reusing.')
        this.setState({ status: 'ready', port, pid: null })
        return
      }
      const error = `Backend port ${port} is occupied by a non-MERAK process.`
      this.appendLog(`[backend] ERROR: ${error}`)
      this.setState({ status: 'error', error })
      return
    }
    this.state.port = port

    this.appendLog(`[backend] Starting: ${launch.executable} ${launch.args.join(' ')}`)
    this.appendLog(`[backend] CWD: ${this.startup.projectRoot}`)

    try {
      // 安装包携带工具目录（mmdc / drawio CLI）供 Python 后端使用
      const toolsDir = existsSync(join(this.startup.projectRoot, 'resources', 'tools'))
        ? join(this.startup.projectRoot, 'resources', 'tools')
        : join(app.getPath('userData'), 'tools')
      const runtimeCwd = launch.packaged ? app.getPath('userData') : this.startup.projectRoot
      if (launch.packaged) mkdirSync(runtimeCwd, { recursive: true })

      // Close the final check/spawn gap as far as possible. If another MERAK
      // instance won 8011, reuse it; never silently create a duplicate 8012.
      if (!(await this.startup.isPortAvailable(port))) {
        if (port === BASE_PORT && await this.startup.waitForExistingBackend(BASE_PORT)) {
          if (this.stopping) return
          this.appendLog('[backend] Merak server became ready before spawn; reusing.')
          this.setState({ status: 'ready', port: BASE_PORT, pid: null })
          return
        }
        if (this.stopping) return
        this.setState({ status: 'error', error: `Backend port ${port} was claimed during startup` })
        return
      }
      if (this.stopping) return

      const child = spawn(launch.executable, launch.args, {
        cwd: runtimeCwd,
        env: {
          ...this.startup.pythonEnvironment(),
          PYTHONUNBUFFERED: '1',
          ...(launch.packaged ? {
            MERAK_IDE_MERAK_SKILLS_PATH: join(dirname(launch.executable), '_internal', 'merak-skills'),
            MERAK_SKILLS_PATH: join(dirname(launch.executable), '_internal', 'merak-skills'),
            MERAK_BACKEND_EXECUTABLE: launch.executable,
          } : {}),
          MERAK_IDE_PORT: String(port),
          MERAK_TOOLS_DIR: toolsDir,
          MERAK_DESKTOP_OWNER_TOKEN: this.ownerToken,
          MERAK_DESKTOP_OWNER_PID: String(process.pid),
          MERAK_INSTALLATION_SHA256: this.startup.installationSha256,
        },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      })
      this.process = child

      this.state.pid = child.pid ?? null
      this.appendLog(`[backend] Process spawned, PID: ${this.state.pid}`)

      child.stdout?.on('data', (data: Buffer) => {
        const lines = data.toString('utf-8').split('\n').filter(Boolean)
        lines.forEach((line) => this.appendLog(`[uvicorn] ${line}`))
      })

      child.stderr?.on('data', (data: Buffer) => {
        const lines = data.toString('utf-8').split('\n').filter(Boolean)
        lines.forEach((line) => this.appendLog(`[uvicorn] ${line}`))
      })

      child.on('exit', (code, signal) => {
        this.appendLog(`[backend] Process exited: code=${code}, signal=${signal}`)
        if (this.state.status === 'starting' && !launch.packaged) {
          this.startup.rejectDevelopmentInterpreter(launch.executable)
          this.appendLog(`[backend] Startup rejected development Python: ${launch.executable}`)
        }
        if (this.process === child) {
          this.process = null
          this.state.pid = null
        }
        if (
          !this.stopping
          && (this.state.status === 'ready' || this.state.status === 'starting')
        ) {
          void this.handleCrash()
        }
      })

      child.on('error', (err) => {
        this.appendLog(`[backend] Spawn error: ${err.message}`)
        if (!launch.packaged) this.startup.rejectDevelopmentInterpreter(launch.executable)
        if (this.process === child) {
          this.process = null
          this.state.pid = null
        }
        if (!this.stopping && !launch.packaged) {
          void this.handleCrash()
        } else {
          this.setState({ status: 'error', error: err.message })
        }
      })

      // 开始健康检查
      await this.waitForReady(port, child)
    } catch (err: any) {
      this.appendLog(`[backend] Failed to start: ${err.message}`)
      this.setState({ status: 'error', error: err.message })
    }
  }

  /** Keep process lifecycle transitions beside the process owner. */
  private waitForReady(port: number, expectedProcess: ChildProcess): Promise<void> {
    return this.startup.waitForReady(port, {
      isCancelled: () => this.stopping || this.process !== expectedProcess
        || this.state.status === 'error' || this.state.status === 'stopped',
      onReady: () => {
        this.appendLog('[backend] Health check passed — server ready.')
        this.setState({ status: 'ready', port })
        if (this.stableRunTimer) clearTimeout(this.stableRunTimer)
        this.stableRunTimer = setTimeout(() => {
          if (!this.stopping && this.process === expectedProcess && this.state.status === 'ready') {
            this.state.restartCount = 0
          }
          this.stableRunTimer = null
        }, STABLE_RUN_RESET_MS)
      },
      onTimeout: () => {
        this.appendLog('[backend] Health check timed out after 300s.')
        // A hung child must release 8011 before bounded crash recovery.
        try {
          if (process.platform === 'win32' && expectedProcess.pid) {
            execSync(`taskkill /pid ${expectedProcess.pid} /T /F`, { stdio: 'pipe' })
          } else {
            expectedProcess.kill('SIGKILL')
          }
        } catch {
          this.setState({ status: 'error', error: 'Backend startup timed out and could not be stopped' })
        }
      },
    })
  }

  /** 崩溃处理：自动重启 */
  private async handleCrash() {
    if (this.stopping) return
    if (this.state.restartCount >= MAX_RESTART_ATTEMPTS) {
      this.appendLog(`[backend] Max restart attempts (${MAX_RESTART_ATTEMPTS}) reached. Giving up.`)
      this.setState({ status: 'error', error: 'Backend crashed repeatedly. Check logs.' })
      return
    }
    const delay = Math.min(1000 * Math.pow(2, this.state.restartCount), 10000)
    this.state.restartCount++
    this.appendLog(`[backend] Restarting in ${delay}ms (attempt ${this.state.restartCount}/${MAX_RESTART_ATTEMPTS})...`)
    this.setState({ status: 'restarting' })
    await new Promise((r) => setTimeout(r, delay))
    if (this.stopping) return
    // Let the failed start invocation unwind and clear its shared promise
    // before creating the replacement process.
    const previousStart = this.startPromise
    if (previousStart) await previousStart
    if (this.stopping) return
    await this.start()
  }

  /** 停止后端进程 */
  async stop(): Promise<void> {
    if (this.stopPromise) return this.stopPromise
    const pending = this.stopOnce()
    this.stopPromise = pending
    try {
      await pending
    } finally {
      if (this.stopPromise === pending) this.stopPromise = null
    }
  }

  private async stopOnce(): Promise<void> {
    this.stopping = true
    this.startup.cancelReadyWait()
    if (this.stableRunTimer) {
      clearTimeout(this.stableRunTimer)
      this.stableRunTimer = null
    }
    if (!this.process) {
      this.setState({ status: 'stopped', pid: null })
      return
    }

    this.appendLog('[backend] Stopping...')
    const proc = this.process
    this.process = null
    this.setState({ status: 'stopped', pid: null })

    // Windows cannot deliver a graceful POSIX signal to the hidden Uvicorn
    // child. Ask the owned backend to persist/cancel its workflow children
    // before terminating the process tree.
    await this.prepareBackendShutdown(this.state.port)

    // Graceful: SIGTERM (or taskkill on Windows)
    try {
      if (process.platform === 'win32' && proc.pid) {
        execSync(`taskkill /pid ${proc.pid} /T /F`, { stdio: 'pipe' })
      } else {
        proc.kill('SIGTERM')
        // 等 5 秒，强杀
        await new Promise<void>((resolve) => {
          const timer = setTimeout(() => {
            try { proc.kill('SIGKILL') } catch { /* already dead */ }
            resolve()
          }, 5000)
          proc.on('exit', () => { clearTimeout(timer); resolve() })
        })
      }
    } catch {
      // 进程可能已经退了
    }
    this.appendLog('[backend] Stopped.')
  }

  private prepareBackendShutdown(port: number): Promise<void> {
    return new Promise((resolve) => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        resolve()
      }
      const request = http.request({
        host: '127.0.0.1',
        port,
        path: '/api/desktop/prepare-shutdown',
        method: 'POST',
        headers: {
          'X-MERAK-Owner-Token': this.ownerToken,
          'Content-Length': '0',
        },
      }, (response) => {
        response.resume()
        response.once('end', finish)
      })
      request.once('error', finish)
      request.setTimeout(12000, () => request.destroy())
      request.once('close', finish)
      request.end()
    })
  }

  /** 重启 */
  async restart(): Promise<void> {
    if (this.restartPromise) return this.restartPromise
    const pending = (async () => {
      this.state.restartCount = 0
      this.startup.clearRejectedDevelopmentInterpreters()
      await this.stop()
      const pendingStart = this.startPromise
      if (pendingStart) await pendingStart
      await this.start()
    })()
    this.restartPromise = pending
    try {
      await pending
    } finally {
      if (this.restartPromise === pending) this.restartPromise = null
    }
  }

  /** 获取状态 */
  getState(): BackendState {
    return { ...this.state }
  }

  /** 获取日志 */
  getLogs(): string[] {
    return [...this.logs]
  }

  /** 获取后端端口 */
  getPort(): number {
    return this.state.port
  }

  /** 注册状态变化监听器 */
  onStatusChange(listener: (state: BackendState) => void) {
    this.statusListeners.push(listener)
  }

  private setState(patch: Partial<BackendState>) {
    Object.assign(this.state, patch)
    this.statusListeners.forEach((fn) => fn({ ...this.state }))
  }

  private appendLog(line: string) {
    const timestamped = `[${new Date().toLocaleTimeString()}] ${line}`
    this.logs.push(timestamped)
    if (this.logs.length > MAX_LOG_LINES) {
      this.logs = this.logs.slice(-MAX_LOG_LINES)
    }
    try {
      appendFileSync(this.backendLogPath, `${new Date().toISOString()} ${line}\n`, 'utf8')
    } catch {
      // The in-memory ring buffer remains available if the log path is locked.
    }
  }
}

// 单例
export const backendManager = new BackendManager()

/** 注册 IPC handlers — 在主进程调用 */
export function registerBackendHandlers() {
  handleTrusted('backend:status', () => backendManager.getState())
  handleTrusted('backend:restart', () => backendManager.restart())
  handleTrusted('backend:logs', () => backendManager.getLogs())
  handleTrusted('backend:port', () => backendManager.getPort())
}
