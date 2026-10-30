/** Wait for the selected development URL without overlapping or leaking probes. */
const http = require('node:http')
const https = require('node:https')
const { performance } = require('node:perf_hooks')

const defaultRuntime = {
  now: () => performance.now(),
  setTimeout,
  clearTimeout,
  request: (url, receive) => (
    url.protocol === 'https:' ? https : http
  ).get(url, { agent: false }, receive),
}

function abortError(signal) {
  const error = new Error('Development server wait cancelled', { cause: signal?.reason })
  error.name = 'AbortError'
  return error
}

function positiveDuration(value, fallback, name, allowZero = false) {
  const duration = value ?? fallback
  if (!Number.isFinite(duration) || duration < 0 || (!allowZero && duration === 0)) {
    throw new RangeError(`${name} must be a ${allowZero ? 'non-negative' : 'positive'} finite number`)
  }
  return duration
}

function waitForRetry(duration, signal, runtime) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError(signal))
    let timer = null
    const settle = (error) => {
      if (timer !== null) runtime.clearTimeout(timer)
      signal?.removeEventListener('abort', cancel)
      if (error) reject(error)
      else resolve()
    }
    const cancel = () => settle(abortError(signal))
    timer = runtime.setTimeout(() => settle(), duration)
    signal?.addEventListener('abort', cancel, { once: true })
    if (signal?.aborted) cancel()
  })
}

function probeResponse(url, duration, signal, runtime) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError(signal))
    let settled = false
    let request = null
    let response = null
    let timer = null
    const finish = (error) => {
      if (settled) return
      settled = true
      if (timer !== null) runtime.clearTimeout(timer)
      signal?.removeEventListener('abort', cancel)
      // Destroy without passing the failure: retained listeners absorb late errors.
      response?.destroy()
      request?.destroy()
      if (error) reject(error)
      else resolve()
    }
    const cancel = () => finish(abortError(signal))
    const receive = (incoming) => {
      response = incoming
      response.on('error', finish)
      if (settled) return response.destroy()
      const status = response.statusCode ?? 0
      if (status < 200 || status >= 300) return finish(new Error(`HTTP ${status}`))
      response.on('aborted', () => finish(new Error('response aborted')))
      response.on('close', () => {
        if (!response.complete) finish(new Error('incomplete response'))
      })
      response.on('end', () => finish(
        response.complete ? undefined : new Error('incomplete response'),
      ))
      response.resume()
    }
    timer = runtime.setTimeout(() => finish(new Error('request timeout')), duration)
    signal?.addEventListener('abort', cancel, { once: true })
    if (signal?.aborted) return cancel()
    try {
      request = runtime.request(url, receive)
      request.on('error', finish)
      if (settled) request.destroy()
    } catch (error) {
      finish(error)
    }
  })
}

/** Injection is only for deterministic local checks; production uses Node HTTP. */
function createDevServerWaiter(runtimeOverrides = {}) {
  const runtime = { ...defaultRuntime, ...runtimeOverrides }
  return async function waitForDevServer(url, options = {}) {
    const selectedUrl = new URL(url)
    if (!['http:', 'https:'].includes(selectedUrl.protocol)) {
      throw new TypeError('Development server URL must use HTTP or HTTPS')
    }
    const timeout = positiveDuration(options.timeoutMs, 120000, 'timeoutMs')
    const requestTimeout = positiveDuration(options.requestTimeoutMs, 15000, 'requestTimeoutMs')
    const retryDelay = positiveDuration(options.retryDelayMs, 350, 'retryDelayMs', true)
    const deadline = runtime.now() + timeout
    let lastError = new Error('server did not respond')
    let attempt = 0
    while (runtime.now() < deadline) {
      if (options.signal?.aborted) throw abortError(options.signal)
      try {
        await probeResponse(selectedUrl, Math.min(requestTimeout, deadline - runtime.now()), options.signal, runtime)
        return
      } catch (error) {
        if (options.signal?.aborted) throw abortError(options.signal)
        lastError = error
      }
      const remaining = deadline - runtime.now()
      if (remaining <= 0) break
      options.onRetry?.(lastError, ++attempt)
      await waitForRetry(Math.min(retryDelay, remaining), options.signal, runtime)
    }
    if (options.signal?.aborted) throw abortError(options.signal)
    throw new Error(`Timeout waiting for ${selectedUrl.href}: ${lastError.message}`, { cause: lastError })
  }
}

const waitForDevServer = createDevServerWaiter()
module.exports = { createDevServerWaiter, waitForDevServer }
