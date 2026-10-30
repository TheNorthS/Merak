import type { ClientRequest, IncomingMessage } from 'node:http'

export interface DevServerWaitOptions {
  timeoutMs?: number
  requestTimeoutMs?: number
  retryDelayMs?: number
  signal?: AbortSignal
  onRetry?: (error: Error, attempt: number) => void
}

export interface DevServerWaitRuntime {
  now: () => number
  setTimeout: typeof setTimeout
  clearTimeout: typeof clearTimeout
  request: (url: URL, receive: (response: IncomingMessage) => void) => ClientRequest
}

/** Resolve only after a complete 2xx response; cancellation rejects with AbortError. */
export function waitForDevServer(url: string | URL, options?: DevServerWaitOptions): Promise<void>
export function createDevServerWaiter(
  runtime?: Partial<DevServerWaitRuntime>,
): typeof waitForDevServer
