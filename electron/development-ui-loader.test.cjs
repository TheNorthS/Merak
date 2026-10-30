const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const Module = require('node:module')
const path = require('node:path')
const test = require('node:test')
const ts = require('typescript')

test('desktop entry has no external network assets on the startup path', () => {
  const entry = fs.readFileSync(path.resolve(__dirname, '../index.html'), 'utf8')
  const styles = fs.readFileSync(path.resolve(__dirname, '../src/index.css'), 'utf8')
  assert.doesNotMatch(entry, /<(?:link|script)\b[^>]*(?:href|src)\s*=\s*['"](?:https?:)?\/\//i)
  assert.doesNotMatch(styles, /@import\s+(?:url\()?\s*['"]?(?:https?:)?\/\//i)
  assert.match(styles, /font-family:\s*'Inter',\s*system-ui,\s*sans-serif/)
})

const sourcePath = path.resolve(__dirname, 'development-ui-loader.ts')
const compiled = ts.transpileModule(fs.readFileSync(sourcePath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
})

const flush = async () => {
  for (let turn = 0; turn < 12; turn += 1) await Promise.resolve()
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((accept, fail) => { resolve = accept; reject = fail })
  return { promise, resolve, reject }
}

class FakeClock {
  now = 0
  nextId = 0
  tasks = new Map()
  setTimeout = (callback, milliseconds) => {
    const id = ++this.nextId
    this.tasks.set(id, { callback, at: this.now + milliseconds })
    return id
  }
  clearTimeout = (id) => { this.tasks.delete(id) }

  async advance(milliseconds) {
    const target = this.now + milliseconds
    await flush()
    for (;;) {
      const next = [...this.tasks.entries()]
        .filter(([, task]) => task.at <= target)
        .sort((left, right) => left[1].at - right[1].at)[0]
      if (!next) break
      const [id, task] = next
      this.now = task.at
      this.tasks.delete(id)
      task.callback()
      await flush()
    }
    this.now = target
    await flush()
  }
}

class FakeWindow extends EventEmitter {
  destroyed = false
  loads = []
  shows = 0
  stops = 0
  navigate = () => Promise.resolve()
  webContents = { stop: () => { this.stops += 1 } }

  isDestroyed() { return this.destroyed }
  loadURL(url) {
    this.loads.push(url)
    return this.navigate(url)
  }
  show() { this.shows += 1 }
  close() {
    this.destroyed = true
    this.emit('closed')
  }
  pages() {
    return this.loads.filter(url => url.startsWith('data:'))
      .map(url => decodeURIComponent(url.slice(url.indexOf(',') + 1)))
  }
  appLoads() { return this.loads.filter(url => !url.startsWith('data:')) }
}

function loadFixture(waitForDevServer = async () => {}, clock = new FakeClock()) {
  const loaded = new Module(sourcePath, module)
  loaded.filename = sourcePath
  loaded.paths = Module._nodeModulePaths(path.dirname(sourcePath))
  loaded.testClock = clock
  loaded.require = (specifier) => {
    if (specifier === '../scripts/dev-server-readiness.cjs') return { waitForDevServer }
    return Module.prototype.require.call(loaded, specifier)
  }
  loaded._compile(
    'const setTimeout = module.testClock.setTimeout; const clearTimeout = module.testClock.clearTimeout;\n'
      + compiled.outputText,
    sourcePath,
  )
  return { loadDevelopmentUi: loaded.exports.loadDevelopmentUi, clock }
}

function controlledProbe() {
  const gate = deferred()
  const calls = []
  const waiter = (url, options) => {
    calls.push({ url, options })
    const abort = () => {
      const error = new Error('probe aborted')
      error.name = 'AbortError'
      gate.reject(error)
    }
    options.signal.addEventListener('abort', abort, { once: true })
    return gate.promise.finally(() => options.signal.removeEventListener('abort', abort))
  }
  return { gate, calls, waiter }
}

function controlledRenderers() {
  const attempts = []
  const active = new Set()
  const startRenderer = (url, signal) => {
    const gate = deferred()
    const attempt = {
      ...gate, signal, disposals: 0, aborts: 0,
      url: `${url}/?__merak_startup=attempt-${attempts.length + 1}`,
    }
    const abort = () => {
      attempt.aborts += 1
      const error = new Error('renderer wait aborted')
      error.name = 'AbortError'
      gate.reject(error)
    }
    signal.addEventListener('abort', abort, { once: true })
    active.add(attempt)
    attempts.push(attempt)
    return {
      url: attempt.url,
      ready: gate.promise,
      dispose() {
        attempt.disposals += 1
        active.delete(attempt)
        signal.removeEventListener('abort', abort)
      },
    }
  }
  return { startRenderer, attempts, active }
}

test('loading page appears immediately and a slow selected server is given 15 seconds', async () => {
  const calls = []
  const clock = new FakeClock()
  const fixture = loadFixture((url, options) => {
    calls.push({ url, options })
    return new Promise(resolve => clock.setTimeout(resolve, 8000))
  }, clock)
  const window = new FakeWindow()
  const selectedUrl = 'http://127.0.0.1:5187/'
  const result = fixture.loadDevelopmentUi(window, selectedUrl)
  await flush()
  assert.equal(window.shows, 1)
  assert.equal(window.pages().length, 1)
  assert.deepEqual(window.appLoads(), [])
  assert.equal(calls[0].url, selectedUrl)
  assert.equal(calls[0].options.requestTimeoutMs, 15000)
  assert.equal(calls[0].options.timeoutMs, 120000)
  await clock.advance(8000)
  assert.equal(await result, 'loaded')
  assert.deepEqual(window.appLoads(), [selectedUrl])
  assert.equal(clock.tasks.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
  await clock.advance(240000)
  assert.equal(calls.length, 1)
  assert.deepEqual(window.appLoads(), [selectedUrl])
})

test('readiness round timeout retries the same URL and recovers automatically', async () => {
  const clock = new FakeClock()
  const calls = []
  const retries = []
  const { loadDevelopmentUi } = loadFixture((url, options) => {
    calls.push({ url, options })
    if (calls.length > 1) return Promise.resolve()
    return new Promise((_, reject) => {
      clock.setTimeout(() => reject(new Error('readiness round timed out')), options.timeoutMs)
    })
  }, clock)
  const window = new FakeWindow()
  const selectedUrl = 'http://127.0.0.1:5179'
  const result = loadDevelopmentUi(window, selectedUrl, { onRetry: error => retries.push(error) })
  await clock.advance(120000)
  assert.equal(retries.length, 1)
  assert.match(window.pages()[1], /readiness round timed out/)
  await clock.advance(1000)
  assert.equal(await result, 'loaded')
  assert.deepEqual(calls.map(call => call.url), [selectedUrl, selectedUrl])
  assert.deepEqual(window.appLoads(), [selectedUrl])
  assert.equal(clock.tasks.size, 0)
})

test('probe success followed by transient Chromium failure retries navigation', async () => {
  const calls = []
  const retries = []
  const { loadDevelopmentUi, clock } = loadFixture(async url => { calls.push(url) })
  const window = new FakeWindow()
  let attempt = 0
  window.navigate = async url => {
    if (!url.startsWith('data:') && ++attempt === 1) throw new Error('ERR_CONNECTION_RESET')
  }
  const selectedUrl = 'http://127.0.0.1:5192'
  const result = loadDevelopmentUi(window, selectedUrl, {
    retryDelayMs: 10,
    onRetry: error => retries.push(error),
  })
  await flush()
  assert.equal(retries.length, 1)
  assert.match(window.pages()[1], /ERR_CONNECTION_RESET/)
  await clock.advance(10)
  assert.equal(await result, 'loaded')
  assert.deepEqual(calls, [selectedUrl, selectedUrl])
  assert.deepEqual(window.appLoads(), [selectedUrl, selectedUrl])
  assert.equal(window.stops, 0)
  assert.equal(clock.tasks.size, 0)
})

test('hung navigation is stopped before retry and late completion cannot replace the app', async () => {
  const hanging = deferred()
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  let attempt = 0
  window.navigate = url => {
    if (!url.startsWith('data:') && ++attempt === 1) return hanging.promise
    return Promise.resolve()
  }
  const selectedUrl = 'http://127.0.0.1:5178'
  const result = loadDevelopmentUi(window, selectedUrl, {
    navigationTimeoutMs: 30, retryDelayMs: 10,
  })
  await clock.advance(30)
  assert.equal(window.stops, 1)
  assert.match(window.pages()[1], /Navigation timeout loading/)
  await clock.advance(10)
  assert.equal(await result, 'loaded')
  const loadedUrls = [...window.loads]
  hanging.resolve()
  await clock.advance(300000)
  assert.deepEqual(window.loads, loadedUrls)
  assert.deepEqual(window.appLoads(), [selectedUrl, selectedUrl])
  assert.equal(window.stops, 1)
  assert.equal(clock.tasks.size, 0)
})

test('closing while probing aborts the probe without app navigation or timers', async () => {
  const probe = controlledProbe()
  const { loadDevelopmentUi, clock } = loadFixture(probe.waiter)
  const window = new FakeWindow()
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178')
  await flush()
  assert.equal(probe.calls.length, 1)
  window.close()
  assert.equal(await result, 'closed')
  assert.equal(probe.calls[0].options.signal.aborted, true)
  assert.deepEqual(window.appLoads(), [])
  assert.equal(window.listenerCount('closed'), 0)
  assert.equal(clock.tasks.size, 0)
})

test('closing during retry delay cancels it and does not issue another probe', async () => {
  let calls = 0
  const { loadDevelopmentUi, clock } = loadFixture(async () => {
    calls += 1
    throw new Error('server still starting')
  })
  const window = new FakeWindow()
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178')
  await flush()
  assert.equal(window.pages().length, 2)
  assert.equal(clock.tasks.size, 1)
  window.close()
  assert.equal(await result, 'closed')
  await clock.advance(240000)
  assert.equal(calls, 1)
  assert.deepEqual(window.appLoads(), [])
  assert.equal(clock.tasks.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
})

test('closing during navigation stops it and ignores late rejection', async () => {
  const hanging = deferred()
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  window.navigate = url => url.startsWith('data:') ? Promise.resolve() : hanging.promise
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178')
  await flush()
  // Emit the lifecycle event before destruction to verify stop is called when legal.
  window.emit('closed')
  assert.equal(await result, 'closed')
  assert.equal(window.stops, 1)
  const loadedUrls = [...window.loads]
  hanging.reject(new Error('late ERR_ABORTED'))
  await clock.advance(240000)
  assert.deepEqual(window.loads, loadedUrls)
  assert.equal(clock.tasks.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
})

test('destroyed window starts no probe or navigation', async () => {
  let calls = 0
  const { loadDevelopmentUi, clock } = loadFixture(async () => { calls += 1 })
  const window = new FakeWindow()
  window.destroyed = true
  assert.equal(await loadDevelopmentUi(window, 'http://127.0.0.1:5178'), 'closed')
  assert.equal(calls, 0)
  assert.deepEqual(window.loads, [])
  assert.equal(clock.tasks.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
})

test('old closed-window task cannot navigate a replacement window', async () => {
  const oldProbe = controlledProbe()
  const calls = []
  const oldUrl = 'http://127.0.0.1:5178'
  const newUrl = 'http://127.0.0.1:5186'
  const { loadDevelopmentUi, clock } = loadFixture((url, options) => {
    calls.push(url)
    return url === oldUrl ? oldProbe.waiter(url, options) : Promise.resolve()
  })
  const oldWindow = new FakeWindow()
  const oldResult = loadDevelopmentUi(oldWindow, oldUrl)
  await flush()
  oldWindow.close()
  const replacement = new FakeWindow()
  const newResult = loadDevelopmentUi(replacement, newUrl)
  assert.equal(await oldResult, 'closed')
  assert.equal(await newResult, 'loaded')
  await clock.advance(240000)
  assert.deepEqual(oldWindow.appLoads(), [])
  assert.deepEqual(replacement.appLoads(), [newUrl])
  assert.deepEqual(calls, [oldUrl, newUrl])
  assert.equal(oldWindow.listenerCount('closed'), 0)
  assert.equal(replacement.listenerCount('closed'), 0)
  assert.equal(clock.tasks.size, 0)
})

test('URL and failure text are escaped in the offline waiting page', async () => {
  const selectedUrl = 'http://127.0.0.1:5178/?unsafe=<img src=x onerror="fail()">&quote=\''
  const reason = '<script>fail("x" & \'y\')</script>'
  let calls = 0
  const { loadDevelopmentUi, clock } = loadFixture(async url => {
    assert.equal(url, selectedUrl)
    if (++calls === 1) throw new Error(reason)
  })
  const window = new FakeWindow()
  const result = loadDevelopmentUi(window, selectedUrl, { retryDelayMs: 10 })
  await flush()
  const initialPage = window.pages()[0]
  const failurePage = window.pages()[1]
  assert.match(initialPage, /<code>http:\/\/127\.0\.0\.1:5178\/\?unsafe=&lt;img src=x onerror=&quot;fail\(\)&quot;&gt;&amp;quote=&#39;<\/code>/)
  assert.match(failurePage, /&lt;script&gt;fail\(&quot;x&quot; &amp; &#39;y&#39;\)&lt;\/script&gt;/)
  assert.equal(failurePage.includes(reason), false)
  assert.equal(initialPage.includes(selectedUrl), false)
  assert.match(initialPage, /default-src 'none'/)
  assert.match(initialPage, /window\.merakIDE\?\.window\.close\(\)/)
  assert.match(initialPage, /-webkit-app-region:drag/)
  assert.doesNotMatch(initialPage, /<link|<img|<script src=/)
  await clock.advance(10)
  assert.equal(await result, 'loaded')
  assert.deepEqual(window.appLoads(), [selectedUrl])
  assert.equal(clock.tasks.size, 0)
})

test('synchronous navigation failure is retried and options reach the readiness owner', async () => {
  const calls = []
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  let attempt = 0
  window.navigate = url => {
    if (!url.startsWith('data:') && ++attempt === 1) throw new Error('navigation adapter failure')
    return Promise.resolve()
  }
  const selectedUrl = 'http://127.0.0.1:5182'
  const result = loadDevelopmentUi(window, selectedUrl, {
    readinessTimeoutMs: 12345,
    requestTimeoutMs: 4567,
    retryDelayMs: 10,
    waitForServer: async (url, options) => { calls.push({ url, options }) },
  })
  await clock.advance(10)
  assert.equal(await result, 'loaded')
  assert.equal(calls.length, 2)
  assert.equal(calls[0].options.timeoutMs, 12345)
  assert.equal(calls[0].options.requestTimeoutMs, 4567)
  assert.deepEqual(calls.map(call => call.url), [selectedUrl, selectedUrl])
  assert.equal(clock.tasks.size, 0)
})

test('failed local loading pages do not prevent initial or retry app navigation', async () => {
  let probes = 0
  const retries = []
  const { loadDevelopmentUi, clock } = loadFixture(async () => {
    if (++probes === 1) throw new Error('server still starting')
  })
  const window = new FakeWindow()
  window.navigate = url => {
    if (url.startsWith('data:')) throw new Error('local loading page rejected')
    return Promise.resolve()
  }
  const selectedUrl = 'http://127.0.0.1:5178'
  const result = loadDevelopmentUi(window, selectedUrl, {
    retryDelayMs: 10,
    onRetry: error => retries.push(error),
  })
  await flush()
  assert.equal(probes, 1)
  assert.equal(window.pages().length, 2)
  assert.equal(retries.length, 3)
  assert.match(retries[0].message, /Development loading page failed to load/)
  assert.match(retries[0].cause.message, /local loading page rejected/)
  assert.match(retries[1].message, /server still starting/)
  assert.match(retries[2].message, /Development loading page failed to load/)
  assert.match(retries[2].cause.message, /local loading page rejected/)
  await clock.advance(10)
  assert.equal(await result, 'loaded')
  assert.equal(probes, 2)
  assert.deepEqual(window.appLoads(), [selectedUrl])
  assert.equal(clock.tasks.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
})

test('stop throwing during navigation timeout still settles and permits recovery', async () => {
  const hanging = deferred()
  const retries = []
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  let attempt = 0
  window.navigate = url => {
    if (!url.startsWith('data:') && ++attempt === 1) return hanging.promise
    return Promise.resolve()
  }
  window.webContents.stop = () => {
    window.stops += 1
    throw new Error('web contents already destroyed')
  }
  const selectedUrl = 'http://127.0.0.1:5178'
  const result = loadDevelopmentUi(window, selectedUrl, {
    navigationTimeoutMs: 30,
    retryDelayMs: 10,
    onRetry: error => retries.push(error),
  })
  await clock.advance(30)
  assert.equal(window.stops, 1)
  assert.equal(retries.length, 1)
  assert.match(retries[0].message, /Navigation timeout loading.*failed to stop navigation/)
  assert.match(retries[0].cause.message, /web contents already destroyed/)
  await clock.advance(10)
  assert.equal(await result, 'loaded')
  assert.deepEqual(window.appLoads(), [selectedUrl, selectedUrl])
  const loadedUrls = [...window.loads]
  hanging.reject(new Error('late navigation rejection'))
  await clock.advance(240000)
  assert.deepEqual(window.loads, loadedUrls)
  assert.equal(clock.tasks.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
})

test('renderer commit succeeds while Chromium load remains pending beyond the old deadline', async () => {
  const hanging = deferred()
  const renderers = controlledRenderers()
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  window.navigate = url => url.startsWith('data:') ? Promise.resolve() : hanging.promise
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', renderers)
  await clock.advance(45000)
  assert.equal(window.stops, 0)
  assert.equal(window.pages().length, 1)
  assert.equal(renderers.attempts.length, 1)
  renderers.attempts[0].resolve()
  assert.equal(await result, 'loaded')
  assert.equal(renderers.attempts[0].disposals, 1)
  assert.equal(renderers.active.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
  assert.equal(clock.tasks.size, 0)
  hanging.reject(new Error('late optional resource failure'))
  await clock.advance(240000)
  assert.equal(window.stops, 0)
  assert.equal(window.appLoads().length, 1)
})

test('Chromium load success alone does not claim that React has committed', async () => {
  const renderers = controlledRenderers()
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  let completed = false
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', renderers)
    .then(value => { completed = true; return value })
  await flush()
  assert.equal(window.appLoads().length, 1)
  assert.equal(completed, false)
  assert.equal(renderers.active.size, 1)
  renderers.attempts[0].resolve()
  assert.equal(await result, 'loaded')
  assert.equal(renderers.active.size, 0)
  assert.equal(clock.tasks.size, 0)
})

test('soft 30 second waiting notice leaves the same navigation intact until a 45 second commit', async () => {
  const hanging = deferred()
  const renderers = controlledRenderers()
  const notices = []
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  window.navigate = url => url.startsWith('data:') ? Promise.resolve() : hanging.promise
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', {
    ...renderers, onWaiting: url => notices.push(url),
  })
  await clock.advance(29999)
  assert.deepEqual(notices, [])
  await clock.advance(1)
  assert.deepEqual(notices, [renderers.attempts[0].url])
  assert.equal(window.stops, 0)
  assert.equal(window.pages().length, 1)
  assert.equal(window.appLoads().length, 1)
  await clock.advance(15000)
  renderers.attempts[0].resolve()
  assert.equal(await result, 'loaded')
  await clock.advance(240000)
  assert.equal(notices.length, 1)
  assert.equal(window.appLoads().length, 1)
  assert.equal(clock.tasks.size, 0)
})

test('renderer startup failure retains its actionable error page and never reloads indefinitely', async () => {
  const renderers = controlledRenderers()
  const retries = []
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', {
    ...renderers, onRetry: error => retries.push(error),
  })
  await flush()
  const error = new Error('React failed to mount: missing component')
  error.name = 'RendererStartupFailure'
  renderers.attempts[0].reject(error)
  assert.equal(await result, 'failed')
  assert.deepEqual(retries, [error])
  assert.equal(window.pages().length, 1)
  assert.equal(window.appLoads().length, 1)
  assert.equal(window.stops, 0)
  assert.equal(renderers.active.size, 0)
  assert.equal(renderers.attempts[0].disposals, 1)
  assert.equal(window.listenerCount('closed'), 0)
  assert.equal(clock.tasks.size, 0)
  await clock.advance(360000)
  assert.equal(renderers.attempts.length, 1)
  assert.equal(window.appLoads().length, 1)
})

test('hard 120 second renderer deadline stops navigation and retries with a fresh attempt token', async () => {
  const hanging = deferred()
  const renderers = controlledRenderers()
  const retries = []
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  window.navigate = url => url.startsWith('data:') ? Promise.resolve() : hanging.promise
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', {
    ...renderers, onRetry: error => retries.push(error),
  })
  await clock.advance(119999)
  assert.equal(window.stops, 0)
  await clock.advance(1)
  assert.equal(window.stops, 1)
  assert.equal(retries.length, 1)
  assert.match(retries[0].message, /Navigation timeout loading/)
  assert.equal(renderers.attempts[0].disposals, 1)
  assert.equal(renderers.active.size, 0)
  await clock.advance(1000)
  assert.equal(renderers.attempts.length, 2)
  assert.notEqual(renderers.attempts[0].url, renderers.attempts[1].url)
  assert.deepEqual(window.appLoads(), renderers.attempts.map(attempt => attempt.url))
  renderers.attempts[0].resolve()
  await flush()
  assert.equal(renderers.active.size, 1)
  renderers.attempts[1].resolve()
  assert.equal(await result, 'loaded')
  assert.equal(renderers.attempts[1].disposals, 1)
  assert.equal(renderers.active.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
  assert.equal(clock.tasks.size, 0)
})

test('closing while waiting for React cancels readiness, disposes listeners, and suppresses late notices', async () => {
  const renderers = controlledRenderers()
  const notices = []
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', {
    ...renderers, onWaiting: url => notices.push(url),
  })
  await flush()
  window.emit('closed')
  assert.equal(await result, 'closed')
  assert.equal(window.stops, 1)
  assert.equal(renderers.attempts[0].signal.aborted, true)
  assert.equal(renderers.attempts[0].aborts, 1)
  assert.equal(renderers.attempts[0].disposals, 1)
  assert.equal(renderers.active.size, 0)
  assert.equal(window.listenerCount('closed'), 0)
  assert.equal(clock.tasks.size, 0)
  await clock.advance(240000)
  assert.deepEqual(notices, [])
  assert.equal(window.appLoads().length, 1)
})

test('close between renderer registration and navigation consumes the disposed readiness rejection', async () => {
  const { loadDevelopmentUi, clock } = loadFixture()
  const window = new FakeWindow()
  const unhandled = []
  const observe = reason => unhandled.push(reason)
  process.on('unhandledRejection', observe)
  let disposals = 0
  let rendererSignal
  try {
    const result = loadDevelopmentUi(window, 'http://127.0.0.1:5178', {
      startRenderer(url, signal) {
        const gate = deferred()
        rendererSignal = signal
        window.close()
        return {
          url: `${url}/?__merak_startup=closed-at-registration`,
          ready: gate.promise,
          dispose() {
            disposals += 1
            const error = new Error('readiness listener disposed after close')
            error.name = 'AbortError'
            gate.reject(error)
          },
        }
      },
    })
    assert.equal(await result, 'closed')
    // An unhandled rejection is delivered on the next real event-loop turn.
    await new Promise(resolve => setImmediate(resolve))
    assert.deepEqual(unhandled, [])
    assert.equal(rendererSignal.aborted, true)
    assert.equal(disposals, 1)
    assert.deepEqual(window.appLoads(), [])
    assert.equal(window.listenerCount('closed'), 0)
    assert.equal(clock.tasks.size, 0)
  } finally {
    process.removeListener('unhandledRejection', observe)
  }
})
