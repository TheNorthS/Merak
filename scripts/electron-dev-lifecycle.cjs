/** One development launcher owns one Electron child and serializes its teardown. */
const { spawn } = require('node:child_process')
const { waitForDevServer } = require('./dev-server-readiness.cjs')

function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null
}

function waitForChildClose(child, timeoutMs, runtime) {
  if (hasExited(child)) return Promise.resolve(true)
  return new Promise(resolve => {
    const finish = (closed) => {
      runtime.clearTimeout(timer)
      child.removeListener('close', close)
      resolve(closed)
    }
    const close = () => finish(true)
    const timer = runtime.setTimeout(() => finish(false), timeoutMs)
    child.once('close', close)
  })
}

async function terminateWindowsTree(pid, runtime) {
  const killer = spawn('taskkill', ['/pid', String(pid), '/T', '/F'], {
    stdio: 'ignore', windowsHide: true,
  })
  let spawnError = null
  killer.on('error', error => { spawnError = error })
  const closed = await waitForChildClose(killer, runtime.treeKillTimeoutMs, runtime)
  if (!closed) killer.kill()
  if (!closed || spawnError || killer.exitCode !== 0) {
    throw new Error(`Failed to terminate owned Electron process tree ${pid}`, { cause: spawnError })
  }
}

async function stopChild(child, runtime) {
  if (hasExited(child)) return
  // Windows child.kill is abrupt: terminate descendants while the owner still exists.
  if (runtime.platform === 'win32' && child.pid) {
    runtime.onInfo(`[Merak] Terminating owned Electron process tree ${child.pid}.`)
    await runtime.terminateTree(child.pid)
    if (await waitForChildClose(child, runtime.treeKillTimeoutMs, runtime)) return
    throw new Error(`Owned Electron process ${child.pid} did not exit; replacement was not started`)
  }
  const closeWait = waitForChildClose(child, runtime.stopTimeoutMs, runtime)
  try {
    child.kill()
  } catch (error) {
    runtime.onError(error)
  }
  if (await closeWait) return
  throw new Error(`Owned Electron process ${child.pid ?? 'unknown'} did not exit; replacement was not started`)
}

/** New builds and shutdown all join the same stop; a live child is never forgotten. */
class ElectronDevLifecycle {
  ownedChild = null
  stoppingPromise = null
  stopFailure = null
  shutdownPromise = null
  generation = 0
  waitController = null
  shuttingDown = false

  constructor(options) {
    const selectedUrl = new URL(options.viteUrl)
    if (!['http:', 'https:'].includes(selectedUrl.protocol)) {
      throw new TypeError('Development server URL must use HTTP or HTTPS')
    }
    this.runtime = {
      platform: process.platform, setTimeout, clearTimeout,
      stopTimeoutMs: 8000, treeKillTimeoutMs: 5000,
      waitForServer: waitForDevServer,
      onInfo: message => console.log(message),
      onError: error => console.error(error),
      ...options,
    }
    this.runtime.terminateTree ??= pid => terminateWindowsTree(pid, this.runtime)
  }

  cancelWait() {
    this.waitController?.abort()
    this.waitController = null
  }

  stopOwnedChild() {
    if (this.stoppingPromise) return this.stoppingPromise
    const child = this.ownedChild
    if (!child && this.stopFailure) return Promise.reject(this.stopFailure)
    if (!child) return Promise.resolve()
    this.ownedChild = null
    const stop = stopChild(child, this.runtime).then(() => {
      this.stopFailure = null
    }).catch(error => {
      this.stopFailure = error
      if (!hasExited(child)) this.ownedChild = child
      throw error
    }).finally(() => {
      if (this.stoppingPromise === stop) this.stoppingPromise = null
    })
    this.stoppingPromise = stop
    return stop
  }

  shutdown() {
    if (this.shutdownPromise) return this.shutdownPromise
    this.shuttingDown = true
    this.generation += 1
    this.cancelWait()
    this.shutdownPromise = this.stopOwnedChild()
    return this.shutdownPromise
  }

  async restart() {
    if (this.shuttingDown) return
    const selectedGeneration = ++this.generation
    this.cancelWait()
    await this.stopOwnedChild()
    if (this.shuttingDown || selectedGeneration !== this.generation) return
    const controller = new AbortController()
    this.waitController = controller
    const runtime = this.runtime
    runtime.onInfo(`[Merak] Waiting for Vite at ${runtime.viteUrl} before starting Electron...`)
    try {
      while (!controller.signal.aborted && selectedGeneration === this.generation) {
        try {
          await runtime.waitForServer(runtime.viteUrl, { timeoutMs: 120000, signal: controller.signal })
          break
        } catch (error) {
          if (controller.signal.aborted) return
          runtime.onError(new Error(`Vite is still starting at ${runtime.viteUrl}`, { cause: error }))
        }
      }
      if (this.shuttingDown || controller.signal.aborted || selectedGeneration !== this.generation) return
      runtime.onInfo(`⚡ Starting Electron (${runtime.viteUrl})...`)
      const child = runtime.spawnElectron(runtime.viteUrl)
      this.ownedChild = child
      child.on('error', error => runtime.onError(error))
      child.on('close', () => {
        if (this.ownedChild === child) this.ownedChild = null
      })
    } finally {
      if (this.waitController === controller) this.waitController = null
    }
  }
}

function createElectronDevLifecycle(options) {
  const lifecycle = new ElectronDevLifecycle(options)
  return { restart: () => lifecycle.restart(), shutdown: () => lifecycle.shutdown() }
}

module.exports = { createElectronDevLifecycle }
