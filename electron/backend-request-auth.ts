import type { BrowserWindow } from 'electron'

/** Attach the desktop capability only to requests originating in this renderer. */
export function installBackendRequestAuth(window: BrowserWindow, token: string) {
  window.webContents.session.webRequest.onBeforeSendHeaders(
    { urls: ['http://127.0.0.1:8011/*', 'ws://127.0.0.1:8011/*'] },
    (details, callback) => {
      const headers = { ...details.requestHeaders }
      // Do not forward a previously injected secret from another frame/session.
      for (const key of Object.keys(headers)) {
        if (key.toLowerCase() === 'x-merak-owner-token') delete headers[key]
      }
      // file:// GET requests can omit both Origin and Referer. Electron's frame
      // URL remains available and is checked alongside the main-frame identity.
      const originKey = Object.keys(headers).find(key => key.toLowerCase() === 'origin')
      const origin = String((originKey && headers[originKey]) || details.referrer || details.frame?.url || '')
      const page = window.webContents.getURL()
      const mainFrame = window.webContents.mainFrame
      const isMainFrame = details.frame?.routingId === mainFrame.routingId
        && details.frame?.processId === mainFrame.processId
      // Chromium sends file:// for packaged WebSocket handshakes, while fetch
      // uses the opaque origin null. Normalize only our verified main document;
      // a child frame or an unrelated local file must never inherit its token.
      const packagedSocket = details.resourceType === 'webSocket' && origin === 'file://'
        && page.startsWith('file://') && details.frame?.url === page
      if (details.webContentsId === window.webContents.id && isMainFrame && (packagedSocket || trustedOrigin(origin, page))) {
        if (packagedSocket && originKey) headers[originKey] = 'null'
        headers['X-Merak-Owner-Token'] = token
      }
      callback({ requestHeaders: headers })
    },
  )
}

export function trustedOrigin(source: string, page: string): boolean {
  try {
    const current = new URL(page)
    if (current.protocol === 'file:') return source === 'null' || source === page
    return ['http:', 'https:'].includes(current.protocol) && new URL(source).origin === current.origin
  } catch {
    return false
  }
}
