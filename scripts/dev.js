/**
 * Start Vite and Electron with one coordinated development-server URL.
 *
 * Port 5178 is the development default. When it is already occupied we
 * select the next free loopback port and pass that exact URL to both Vite and
 * Electron, preventing Electron from loading an unrelated stale dev server.
 */
const net = require('net')
const { spawn } = require('child_process')
const { join } = require('path')

const root = join(__dirname, '..')
const cliArgs = process.argv.slice(2)
const webOnly = cliArgs.includes('--web-only')
const printPortOnly = cliArgs.includes('--print-port')
const host = process.env.MERAK_VITE_HOST || '127.0.0.1'

function requestedPort() {
  const portIndex = cliArgs.indexOf('--port')
  const raw = portIndex >= 0 ? cliArgs[portIndex + 1] : process.env.MERAK_VITE_PORT
  const parsed = Number.parseInt(raw || '5178', 10)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`Invalid development port: ${raw}`)
  }
  return parsed
}

function portIsAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.unref()
    server.once('error', () => resolve(false))
    server.listen({ host, port, exclusive: true }, () => {
      server.close(() => resolve(true))
    })
  })
}

async function findAvailablePort(startPort, attempts = 100) {
  for (let offset = 0; offset < attempts; offset += 1) {
    const candidate = startPort + offset
    if (candidate > 65535) break
    if (await portIsAvailable(candidate)) return candidate
  }
  throw new Error(`No free development port found from ${startPort}`)
}

function startNode(args, env) {
  return spawn(process.execPath, args, {
    cwd: root,
    env,
    stdio: 'inherit',
  })
}

function waitForExit(child, timeoutMs = 8000) {
  if (!child || child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve()
    }
    const timer = setTimeout(finish, timeoutMs)
    child.once('close', finish)
  })
}

async function stopProcessTree(child) {
  if (!child || !child.pid) return
  if (child.exitCode !== null || child.signalCode !== null) return

  if (process.platform === 'win32') {
    // Vite and build-electron each own descendants. In particular, killing
    // only build-electron leaves its Electron child alive with no Vite server,
    // which then shows ERR_FAILED against a dead development URL.
    const killer = spawn(
      'taskkill',
      ['/pid', String(child.pid), '/T', '/F'],
      { stdio: 'ignore', windowsHide: true },
    )
    await Promise.race([
      new Promise((resolve) => killer.once('close', resolve)),
      new Promise((resolve) => setTimeout(resolve, 8000)),
    ])
    return
  }

  child.kill('SIGTERM')
  await waitForExit(child)
  if (child.exitCode === null && child.signalCode === null) {
    child.kill('SIGKILL')
    await waitForExit(child, 2000)
  }
}

async function main() {
  const preferredPort = requestedPort()
  const port = await findAvailablePort(preferredPort)
  const viteUrl = `http://${host}:${port}`

  if (port !== preferredPort) {
    console.log(`[Merak] Port ${preferredPort} is busy; using ${port}.`)
  } else {
    console.log(`[Merak] Using development port ${port}.`)
  }
  if (printPortOnly) {
    console.log(port)
    return
  }

  const env = {
    ...process.env,
    MERAK_VITE_HOST: host,
    MERAK_VITE_PORT: String(port),
    VITE_DEV_SERVER_URL: viteUrl,
  }
  const viteBin = join(root, 'node_modules', 'vite', 'bin', 'vite.js')
  const children = [
    startNode(
      [viteBin, '--host', host, '--port', String(port), '--strictPort'],
      env,
    ),
  ]
  if (!webOnly) {
    children.push(
      startNode([join(root, 'scripts', 'build-electron.js'), '--watch'], env),
    )
  }

  let shutdownPromise = null
  const shutdown = (exitCode = 0) => {
    if (shutdownPromise) return shutdownPromise
    shutdownPromise = (async () => {
      await Promise.allSettled(children.map(stopProcessTree))
      process.exitCode = exitCode
    })()
    return shutdownPromise
  }

  for (const child of children) {
    child.once('exit', (code, signal) => {
      if (shutdownPromise) return
      const exitCode = typeof code === 'number' ? code : 1
      console.error(
        `[Merak] Development child exited (${signal || `code ${exitCode}`}); stopping peers.`,
      )
      void shutdown(exitCode || 1)
    })
    child.once('error', (error) => {
      if (shutdownPromise) return
      console.error(`[Merak] Failed to start development child: ${error.message}`)
      void shutdown(1)
    })
  }

  process.once('SIGINT', () => { void shutdown(0) })
  process.once('SIGTERM', () => { void shutdown(0) })
}

main().catch((error) => {
  console.error(`[Merak] ${error instanceof Error ? error.message : String(error)}`)
  process.exit(1)
})
