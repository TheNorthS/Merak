const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const test = require('node:test')
const { createDevServerWaiter } = require('./dev-server-readiness.cjs')

class TestClock {
  time = 0
  nextId = 1
  timers = new Map()

  setTimeout = (callback, duration) => {
    const id = this.nextId++
    this.timers.set(id, { callback, at: this.time + duration })
    return id
  }

  clearTimeout = (id) => this.timers.delete(id)

  async advance(duration) {
    const target = this.time + duration
    await this.flush()
    while (true) {
      const pending = [...this.timers].sort((a, b) => a[1].at - b[1].at)
      const next = pending[0]
      if (!next || next[1].at > target) break
      this.time = next[1].at
      this.timers.delete(next[0])
      next[1].callback()
      await this.flush()
    }
    this.time = target
    await this.flush()
  }

  async flush() {
    for (let count = 0; count < 5; count++) await Promise.resolve()
  }
}

function fakeTransport(clock, plans) {
  const calls = []
  const active = new Set()
  let maximumActive = 0
  const request = (url, receive) => {
    const plan = plans[calls.length] ?? { stall: true }
    const outgoing = new EventEmitter()
    const scheduled = new Set()
    const incoming = new EventEmitter()
    Object.assign(incoming, { complete: false, statusCode: plan.status ?? 200 })
    incoming.resume = () => { incoming.resumed = true }
    incoming.destroy = () => {
      if (incoming.destroyed) return
      incoming.destroyed = true
      incoming.emit('close')
    }
    outgoing.destroy = () => {
      if (outgoing.destroyed) return
      outgoing.destroyed = true
      for (const timer of scheduled) clock.clearTimeout(timer)
      active.delete(outgoing)
    }
    const schedule = (delay, callback) => {
      const timer = clock.setTimeout(() => {
        scheduled.delete(timer)
        callback()
      }, delay)
      scheduled.add(timer)
    }
    calls.push({ url: url.href, outgoing, incoming })
    active.add(outgoing)
    maximumActive = Math.max(maximumActive, active.size)
    if (plan.errorAt !== undefined) {
      schedule(plan.errorAt, () => outgoing.emit('error', new Error('connection refused')))
    } else if (!plan.stall) {
      schedule(plan.headersAt ?? 0, () => receive(incoming))
      if (plan.bodyAt !== null) schedule(plan.bodyAt ?? 0, () => {
        incoming.complete = plan.complete !== false
        incoming.emit('end')
      })
      if (plan.bodyErrorAt !== undefined) {
        schedule(plan.bodyErrorAt, () => incoming.emit('error', new Error('body failed')))
      }
      if (plan.abortAt !== undefined) schedule(plan.abortAt, () => incoming.emit('aborted'))
    }
    return outgoing
  }
  return { request, calls, active, maximumActive: () => maximumActive }
}

function fixture(plans) {
  const clock = new TestClock()
  const transport = fakeTransport(clock, plans)
  const wait = createDevServerWaiter({
    now: () => clock.time,
    setTimeout: clock.setTimeout,
    clearTimeout: clock.clearTimeout,
    request: transport.request,
  })
  return { clock, transport, wait }
}

function capture(promise) {
  const state = { settled: false, error: null }
  const done = promise.then(
    () => { state.settled = true },
    (error) => { state.settled = true; state.error = error },
  )
  return { state, done }
}

function assertReleased(clock, transport) {
  assert.equal(clock.timers.size, 0)
  assert.equal(transport.active.size, 0)
  assert.equal(transport.maximumActive(), 1)
  for (const { outgoing } of transport.calls) assert.equal(outgoing.destroyed, true)
}

test('default probe accepts a slow complete response beyond the old two-second limit', async () => {
  const { clock, transport, wait } = fixture([{ headersAt: 8000, bodyAt: 9000 }])
  const { state, done } = capture(wait('http://127.0.0.1:5178/'))
  await clock.advance(2001)
  assert.equal(state.settled, false)
  await clock.advance(5999)
  assert.equal(transport.calls[0].incoming.resumed, true)
  assert.equal(state.settled, false, 'headers alone cannot mark a response ready')
  await clock.advance(1000)
  await done
  assert.equal(state.error, null)
  assert.equal(transport.calls.length, 1)
  assertReleased(clock, transport)
})

test('an overall deadline bounds all sequential requests and retry delays', async () => {
  const { clock, transport, wait } = fixture([{ stall: true }, { stall: true }, { stall: true }])
  const { state, done } = capture(wait('http://127.0.0.1:5178/', {
    timeoutMs: 12200, requestTimeoutMs: 5000,
  }))
  await clock.advance(12199)
  assert.equal(state.settled, false)
  await clock.advance(1)
  await done
  assert.match(state.error.message, /Timeout waiting for http:\/\/127\.0\.0\.1:5178\/: request timeout/)
  assert.equal(transport.calls.length, 3)
  assertReleased(clock, transport)
})

test('cancelling an in-flight body immediately destroys request and response', async () => {
  const { clock, transport, wait } = fixture([{ bodyAt: null }])
  const controller = new AbortController()
  const { state, done } = capture(wait('http://127.0.0.1:5178/', { signal: controller.signal }))
  await clock.advance(0)
  controller.abort('window closed')
  await done
  assert.equal(state.error.name, 'AbortError')
  assert.equal(state.error.cause, 'window closed')
  assert.equal(transport.calls[0].incoming.destroyed, true)
  assertReleased(clock, transport)
})

test('cancelling a retry delay prevents any following request', async () => {
  const { clock, transport, wait } = fixture([{ status: 503 }, {}])
  const controller = new AbortController()
  const { state, done } = capture(wait('http://127.0.0.1:5178/', { signal: controller.signal }))
  await clock.advance(1)
  controller.abort()
  await done
  assert.equal(state.error.name, 'AbortError')
  await clock.advance(100000)
  assert.equal(transport.calls.length, 1)
  assertReleased(clock, transport)
})

test('cancelling before response headers immediately releases the pending request', async () => {
  const { clock, transport, wait } = fixture([{ stall: true }])
  const controller = new AbortController()
  const { state, done } = capture(wait('http://127.0.0.1:5178/', { signal: controller.signal }))
  controller.abort()
  await done
  assert.equal(state.error.name, 'AbortError')
  assertReleased(clock, transport)
})

test('pre-cancelled waits do not open any connection', async () => {
  const { clock, transport, wait } = fixture([{}])
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(wait('http://127.0.0.1:5178/', { signal: controller.signal }), { name: 'AbortError' })
  assert.equal(clock.timers.size, 0)
  assert.equal(transport.calls.length, 0)
})

test('HTTP errors and redirects retry the same selected URL, without overlapping requests', async () => {
  const { clock, transport, wait } = fixture([{ status: 503 }, { status: 302 }, {}])
  const failures = []
  const { state, done } = capture(wait('http://127.0.0.1:5186/app?dev=1', {
    onRetry: (error, attempt) => failures.push([error.message, attempt]),
  }))
  await clock.advance(700)
  await done
  assert.equal(state.error, null)
  assert.deepEqual(failures, [['HTTP 503', 1], ['HTTP 302', 2]])
  assert.deepEqual(transport.calls.map(({ url }) => url), Array(3).fill('http://127.0.0.1:5186/app?dev=1'))
  assertReleased(clock, transport)
})

test('an ended but incomplete response is rejected before retrying', async () => {
  const { clock, transport, wait } = fixture([{ bodyAt: 100, complete: false }, {}])
  const failures = []
  const { state, done } = capture(wait('http://127.0.0.1:5178/', {
    onRetry: (error) => failures.push(error.message),
  }))
  await clock.advance(450)
  await done
  assert.equal(state.error, null)
  assert.deepEqual(failures, ['incomplete response'])
  assert.equal(transport.calls[0].incoming.destroyed, true)
  assertReleased(clock, transport)
})

test('request errors, body errors, and aborted bodies are retried safely', async () => {
  const { clock, transport, wait } = fixture([
    { errorAt: 0 },
    { bodyAt: null, bodyErrorAt: 50 },
    { bodyAt: null, abortAt: 50 },
    {},
  ])
  const failures = []
  const { state, done } = capture(wait('http://127.0.0.1:5178/', {
    onRetry: (error) => failures.push(error.message),
  }))
  await clock.advance(1150)
  await done
  assert.equal(state.error, null)
  assert.deepEqual(failures, ['connection refused', 'body failed', 'response aborted'])
  assertReleased(clock, transport)
})

test('the default request budget is fifteen seconds, not an unbounded body wait', async () => {
  const { clock, transport, wait } = fixture([{ bodyAt: null }, {}])
  const { state, done } = capture(wait('http://127.0.0.1:5178/'))
  await clock.advance(14999)
  assert.equal(state.settled, false)
  assert.equal(transport.calls.length, 1)
  await clock.advance(351)
  await done
  assert.equal(state.error, null)
  assert.equal(transport.calls.length, 2)
  assertReleased(clock, transport)
})

test('a deadline shorter than the retry delay settles without another connection', async () => {
  const { clock, transport, wait } = fixture([{ status: 503 }, {}])
  const { state, done } = capture(wait('http://127.0.0.1:5178/', { timeoutMs: 100 }))
  await clock.advance(100)
  await done
  assert.match(state.error.message, /Timeout waiting.*HTTP 503/)
  assert.equal(transport.calls.length, 1)
  assertReleased(clock, transport)
})

test('invalid URL protocols and timeout budgets fail without opening requests', async () => {
  const { clock, transport, wait } = fixture([{}])
  await assert.rejects(wait('file:///app'), /must use HTTP or HTTPS/)
  for (const options of [{ timeoutMs: 0 }, { requestTimeoutMs: Infinity }, { retryDelayMs: -1 }]) {
    await assert.rejects(wait('http://127.0.0.1:5178/', options), /finite number/)
  }
  assert.equal(clock.timers.size, 0)
  assert.equal(transport.calls.length, 0)
})
