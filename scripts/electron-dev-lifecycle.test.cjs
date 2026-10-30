const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const test = require('node:test')
const { createElectronDevLifecycle } = require('./electron-dev-lifecycle.cjs')

const flush = async () => {
  for (let turn = 0; turn < 12; turn++) await Promise.resolve()
}

class FakeClock {
  now = 0
  nextId = 1
  timers = new Map()
  setTimeout = (callback, duration) => {
    const id = this.nextId++
    this.timers.set(id, { callback, at: this.now + duration })
    return id
  }
  clearTimeout = id => this.timers.delete(id)

  async advance(duration) {
    const target = this.now + duration
    await flush()
    while (true) {
      const next = [...this.timers].sort((a, b) => a[1].at - b[1].at)[0]
      if (!next || next[1].at > target) break
      this.now = next[1].at
      this.timers.delete(next[0])
      next[1].callback()
      await flush()
    }
    this.now = target
    await flush()
  }
}

class FakeChild extends EventEmitter {
  exitCode = null
  signalCode = null
  kills = 0

  constructor(pid, closeOnKill = true) {
    super()
    this.pid = pid
    this.closeOnKill = closeOnKill
  }

  kill() {
    this.kills++
    if (this.closeOnKill) this.close()
    return true
  }

  close() {
    if (this.exitCode !== null) return
    this.exitCode = 0
    this.emit('close', 0, null)
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail })
  return { promise, resolve, reject }
}

function fixture(options = {}) {
  const clock = new FakeClock()
  const children = []
  const probes = []
  const spawnUrls = []
  const treePids = []
  const errors = []
  const lifecycle = createElectronDevLifecycle({
    viteUrl: 'http://127.0.0.1:5186/app?selected=1',
    platform: 'linux',
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    waitForServer: async (url, waitOptions) => { probes.push({ url, options: waitOptions }) },
    spawnElectron: url => {
      spawnUrls.push(url)
      const child = new FakeChild(100 + children.length, children.length > 0)
      assert.equal(children.filter(previous => previous.exitCode === null).length, 0)
      children.push(child)
      return child
    },
    terminateTree: pid => {
      treePids.push(pid)
      return new Promise(resolve => clock.setTimeout(() => {
        children.find(child => child.pid === pid).close()
        resolve()
      }, 10))
    },
    onInfo: () => {},
    onError: error => { errors.push(error) },
    ...options,
  })
  return { lifecycle, clock, children, probes, spawnUrls, treePids, errors }
}

test('overlapping builds join old teardown and only the newest build spawns', async () => {
  const { lifecycle, clock, children, probes, spawnUrls } = fixture()
  await lifecycle.restart()
  const firstRestart = lifecycle.restart()
  await flush()
  const newestRestart = lifecycle.restart()
  await flush()
  assert.equal(children.length, 1)
  assert.equal(children[0].kills, 1)
  assert.equal(probes.length, 1, 'new builds cannot probe or spawn before the old owner closes')
  children[0].close()
  await Promise.all([firstRestart, newestRestart])
  assert.equal(children.length, 2)
  assert.equal(probes.length, 2)
  assert.deepEqual(spawnUrls, Array(2).fill('http://127.0.0.1:5186/app?selected=1'))
  assert.equal(clock.timers.size, 0)
  await lifecycle.shutdown()
  assert.equal(children[1].kills, 1)
  assert.equal(clock.timers.size, 0)
})

test('shutdown joins concurrent rebuild teardown and kills exactly the owned tree once', async () => {
  const { lifecycle, clock, children, probes, treePids } = fixture({ platform: 'win32' })
  await lifecycle.restart()
  const oldRestart = lifecycle.restart()
  const newRestart = lifecycle.restart()
  const shutdown = lifecycle.shutdown()
  assert.equal(lifecycle.shutdown(), shutdown, 'repeated shutdown uses one teardown promise')
  let finished = false
  const done = Promise.all([oldRestart, newRestart, shutdown]).then(() => { finished = true })
  await flush()
  assert.equal(finished, false)
  assert.equal(children[0].kills, 0, 'Windows must not terminate the parent before its owned tree')
  await clock.advance(9)
  assert.equal(finished, false)
  assert.deepEqual(treePids, [100])
  await clock.advance(1)
  await done
  assert.equal(finished, true)
  assert.equal(children.length, 1)
  assert.equal(probes.length, 1)
  assert.equal(children[0].exitCode, 0)
  await lifecycle.restart()
  assert.equal(children.length, 1, 'shutdown is terminal even when a late build completes')
  assert.equal(clock.timers.size, 0)
})

test('a stale probe cannot spawn even if its transport ignores abort and resolves late', async () => {
  const waits = []
  const { lifecycle, clock, children, spawnUrls } = fixture({
    waitForServer: (url, options) => {
      const gate = deferred()
      waits.push({ ...gate, url, options })
      return gate.promise
    },
  })
  const oldRestart = lifecycle.restart()
  await flush()
  const currentRestart = lifecycle.restart()
  await flush()
  assert.equal(waits.length, 2)
  assert.equal(waits[0].options.signal.aborted, true)
  assert.equal(waits[1].options.signal.aborted, false)
  waits[1].resolve()
  await currentRestart
  assert.equal(children.length, 1)
  waits[0].resolve()
  await oldRestart
  assert.equal(children.length, 1)
  assert.deepEqual(waits.map(wait => wait.url), Array(2).fill(spawnUrls[0]))
  children[0].closeOnKill = true
  await lifecycle.shutdown()
  assert.equal(clock.timers.size, 0)
})

test('shutdown cancels readiness and never spawns a child after its completion', async () => {
  const waits = []
  const { lifecycle, clock, children } = fixture({
    waitForServer: (url, options) => {
      const gate = deferred()
      const cancel = () => gate.reject(new Error('cancelled readiness'))
      options.signal.addEventListener('abort', cancel, { once: true })
      waits.push({ url, options })
      return gate.promise.finally(() => options.signal.removeEventListener('abort', cancel))
    },
  })
  const restart = lifecycle.restart()
  await flush()
  await lifecycle.shutdown()
  await restart
  assert.equal(waits.length, 1)
  assert.equal(waits[0].options.signal.aborted, true)
  assert.equal(children.length, 0)
  assert.equal(clock.timers.size, 0)
})

test('transient readiness rounds keep the exact selected URL before spawning', async () => {
  const attempts = []
  const { lifecycle, children, errors, spawnUrls } = fixture({
    waitForServer: async (url, options) => {
      attempts.push({ url, options })
      if (attempts.length === 1) throw new Error('request timeout')
    },
  })
  await lifecycle.restart()
  assert.equal(children.length, 1)
  assert.equal(errors.length, 1)
  assert.equal(errors[0].cause.message, 'request timeout')
  assert.deepEqual(attempts.map(attempt => attempt.url), Array(2).fill(spawnUrls[0]))
  assert.equal(attempts[0].options.timeoutMs, 120000)
  assert.equal(attempts[0].options.signal, attempts[1].options.signal)
  children[0].closeOnKill = true
  await lifecycle.shutdown()
})

test('unconfirmed teardown rejects replacement and preserves the old child for retry', async () => {
  const { lifecycle, clock, children, treePids } = fixture({ platform: 'linux' })
  await lifecycle.restart()
  const failedRestart = lifecycle.restart()
  const rejection = assert.rejects(failedRestart, /did not exit; replacement was not started/)
  await clock.advance(8000)
  await rejection
  assert.equal(children.length, 1)
  assert.equal(children[0].kills, 1)
  assert.deepEqual(treePids, [])
  const successfulRestart = lifecycle.restart()
  await flush()
  assert.equal(children[0].kills, 2, 'the unclosed child remains owned, not forgotten')
  children[0].close()
  await successfulRestart
  assert.equal(children.length, 2)
  await lifecycle.shutdown()
  assert.equal(clock.timers.size, 0)
})

test('a failed Windows tree termination never permits a conflicting new owner', async () => {
  const treePids = []
  const { lifecycle, clock, children } = fixture({
    platform: 'win32',
    terminateTree: async pid => {
      treePids.push(pid)
      throw new Error('taskkill failed')
    },
  })
  await lifecycle.restart()
  const restart = lifecycle.restart()
  const rejection = assert.rejects(restart, /taskkill failed/)
  await flush()
  await rejection
  assert.equal(children.length, 1)
  assert.deepEqual(treePids, [100])
  assert.equal(children[0].kills, 0)
  children[0].close()
  const rejectionAfterClose = assert.rejects(lifecycle.restart(), /taskkill failed/)
  await rejectionAfterClose
  assert.equal(children.length, 1, 'failed descendant teardown remains blocked even after parent exit')
  await assert.rejects(lifecycle.shutdown(), /taskkill failed/)
  assert.equal(clock.timers.size, 0)
})

test('an early parent close cannot skip required Windows descendant teardown', async () => {
  const tree = deferred()
  const treePids = []
  const { lifecycle, clock, children, probes } = fixture({
    platform: 'win32',
    terminateTree: pid => { treePids.push(pid); return tree.promise },
  })
  await lifecycle.restart()
  let restarted = false
  const restart = lifecycle.restart().then(() => { restarted = true })
  await flush()
  assert.deepEqual(treePids, [100])
  assert.equal(children[0].kills, 0)
  children[0].close()
  await flush()
  assert.equal(restarted, false)
  assert.equal(children.length, 1)
  assert.equal(probes.length, 1)
  tree.resolve()
  await restart
  assert.equal(children.length, 2)
  children[1].close()
  await lifecycle.shutdown()
  assert.equal(clock.timers.size, 0)
})

test('a successful tree command still requires confirmation that old Electron exited', async () => {
  const treePids = []
  const { lifecycle, clock, children } = fixture({
    platform: 'win32',
    terminateTree: async pid => {
      treePids.push(pid)
      if (treePids.length > 1) children[0].close()
    },
  })
  await lifecycle.restart()
  const restart = lifecycle.restart()
  const rejection = assert.rejects(restart, /did not exit; replacement was not started/)
  await clock.advance(5000)
  await rejection
  assert.equal(children.length, 1)
  assert.deepEqual(treePids, [100])
  await lifecycle.shutdown()
  assert.equal(clock.timers.size, 0)
})

test('invalid configured URL fails once before readiness can enter a retry loop', () => {
  let probes = 0
  let spawns = 0
  const options = {
    waitForServer: async () => { probes++ },
    spawnElectron: () => { spawns++ },
  }
  assert.throws(() => createElectronDevLifecycle({ ...options, viteUrl: 'not-a-url' }), /Invalid URL/)
  assert.throws(() => createElectronDevLifecycle({ ...options, viteUrl: 'file:///app' }), /HTTP or HTTPS/)
  assert.equal(probes, 0)
  assert.equal(spawns, 0)
})
