import { ipcMain, type BrowserWindow, type IpcMainInvokeEvent } from 'electron'

let trustedWindow: BrowserWindow | null = null
let trustedUrl = ''

export function trustRenderer(window: BrowserWindow, url: string) {
  trustedWindow = window
  trustedUrl = url
}

export function requireTrustedSender(event: IpcMainInvokeEvent): void {
  if (!trustedWindow || trustedWindow.isDestroyed() || event.sender !== trustedWindow.webContents
      || event.senderFrame !== trustedWindow.webContents.mainFrame) throw new Error('Untrusted IPC sender')
  const current = new URL(event.senderFrame.url)
  const expected = new URL(trustedUrl)
  if (current.protocol === 'file:' ? current.href.split('?')[0] !== expected.href.split('?')[0]
    : current.origin !== expected.origin) throw new Error('Untrusted IPC origin')
}

export function handleTrusted<T extends unknown[], R>(
  channel: string, listener: (event: IpcMainInvokeEvent, ...args: T) => R,
) {
  ipcMain.handle(channel, (event, ...args) => {
    requireTrustedSender(event)
    return listener(event, ...args as T)
  })
}
