import { pathToFileURL } from 'url'
import { handleTrusted, trustRenderer } from './trusted-ipc'
import { app, BrowserWindow, ipcMain, shell, Menu, MenuItem, clipboard, dialog } from 'electron'
import { dirname, join } from 'path'
import { promises as fs } from 'fs'
import { registerFsHandlers } from './ipc/fs'
import { backendManager, registerBackendHandlers } from './ipc/backend'
import { registerDrawioHandlers, getElectronApiPort } from './ipc/drawio'
import { loadDevelopmentUi } from './development-ui-loader'
import { createRendererStartupAttempt } from './renderer-startup-session'

let mainWindow: BrowserWindow | null = null
const isDev = !app.isPackaged
const ownsDesktopInstance = app.requestSingleInstanceLock()

if (!ownsDesktopInstance) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
  })
}

const appStatePath = () => join(app.getPath('userData'), 'merak-ui-state.json')

async function readAppState(): Promise<Record<string, unknown>> {
  try {
    const payload = JSON.parse(await fs.readFile(appStatePath(), 'utf8'))
    return payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {}
  } catch {
    return {}
  }
}

async function writeAppState(state: Record<string, unknown>): Promise<void> {
  const target = appStatePath()
  await fs.mkdir(dirname(target), { recursive: true })
  await fs.writeFile(target, JSON.stringify(state, null, 2), 'utf8')
}

function createWindow() {
  mainWindow = new BrowserWindow({
    title: 'Merak',
    width: 1600,
    height: 1000,
    minWidth: 1024,
    minHeight: 600,
    frame: false,
    backgroundColor: '#242435',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
    show: false,
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })
  trustRenderer(mainWindow, isDev
    ? process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5178'
    : pathToFileURL(join(__dirname, '../dist/index.html')).href)
  backendManager.authorizeRenderer(mainWindow)
  mainWindow.webContents.on('will-prevent-unload', event => {
    const choice = dialog.showMessageBoxSync(mainWindow!, {
      type: 'warning', buttons: ['取消，保留修改', '放弃修改并关闭'],
      defaultId: 0, cancelId: 0, message: '文件有未保存的修改。',
    })
    if (choice === 1) event.preventDefault()
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const protocol = new URL(url).protocol
      if (['http:', 'https:', 'mailto:'].includes(protocol)) {
        void shell.openExternal(url)
      }
    } catch {
      // Ignore malformed or non-external navigation requests.
    }
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const current = mainWindow?.webContents.getURL()
    if (current && url !== current) event.preventDefault()
  })

  // 使用 Electron 原生 clipboard 模块，完全绕开浏览器权限限制
  mainWindow.webContents.session.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === 'clipboard-read' || permission === 'clipboard-sanitized-write')
  })
  mainWindow.webContents.session.setPermissionCheckHandler((_wc, permission) => {
    return permission === 'clipboard-read' || permission === 'clipboard-sanitized-write'
  })

  // 原生右键菜单（输入框/文本选中区域的复制粘贴）
  mainWindow.webContents.on('context-menu', (_e, params) => {
    if (!params.isEditable && !params.selectionText) return
    const menu = new Menu()
    if (params.selectionText && params.isEditable) {
      menu.append(new MenuItem({ label: '剪切', role: 'cut' }))
    }
    if (params.selectionText) {
      menu.append(new MenuItem({ label: '复制', role: 'copy' }))
    }
    if (params.isEditable) {
      menu.append(new MenuItem({ label: '粘贴', role: 'paste' }))
      menu.append(new MenuItem({ type: 'separator' }))
      menu.append(new MenuItem({ label: '全选', role: 'selectAll' }))
    }
    menu.popup({ window: mainWindow! })
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

async function loadApp() {
  // Each loader owns one window; retries from a closed window cannot touch a new one.
  const window = mainWindow
  if (!window || window.isDestroyed()) return
  if (isDev) {
    // The launcher's selected URL is authoritative; never probe unrelated ports.
    const viteUrl = process.env['VITE_DEV_SERVER_URL'] || 'http://127.0.0.1:5178'
    const loadStartedAt = Date.now()
    console.log(`[Merak] Waiting for Vite at ${viteUrl}...`)
    try {
      const result = await loadDevelopmentUi(window, viteUrl, {
        startRenderer: (url, signal) => createRendererStartupAttempt(window, url, signal),
        onWaiting: () => console.log('[Merak] Waiting for the first React commit; preserving the current navigation...'),
        onRetry: error => console.warn(`[Merak] Retrying development UI: ${error.message}`),
      })
      if (result === 'loaded') {
        console.log(`[Merak] Development UI loaded at ${viteUrl} (${Date.now() - loadStartedAt} ms)`)
      }
      if (result === 'failed') console.error('[Merak] Renderer failed; its diagnostic remains visible.')
    } catch (error) {
      console.error('[Merak] Development window failed to load:', error)
      if (!window.isDestroyed()) window.show()
    }
  } else {
    try {
      await window.loadFile(join(__dirname, '../dist/index.html'))
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      const html = `<html><body style="background:#1e1e2e;color:#cdd6f4;font-family:system-ui;padding:32px"><h2>Merak failed to load</h2><pre style="white-space:pre-wrap">${reason.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)}</pre></body></html>`
      if (!window.isDestroyed()) {
        await window.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
        window.show()
      }
    }
  }
}

// IPC 剪贴板（绕过浏览器权限，直接用 Electron clipboard 模块）
handleTrusted('clipboard:read', () => clipboard.readText())
handleTrusted('clipboard:write', (_e, text: string) => { clipboard.writeText(text) })

// Application-level UI state must not live under the Vite origin. Development
// ports can change (5178 -> 5179), and localStorage is isolated by port.
handleTrusted('app-state:get', async (_event, key: string) => {
  if (key !== 'projectPath') return null
  return (await readAppState())[key] ?? null
})
handleTrusted('app-state:set', async (_event, key: string, value: unknown) => {
  if (key !== 'projectPath') throw new Error(`Unsupported app-state key: ${key}`)
  const state = await readAppState()
  if (typeof value === 'string' && value.trim()) state[key] = value
  else delete state[key]
  await writeAppState(state)
})

// IPC 窗口控制
ipcMain.on('window:minimize', () => mainWindow?.minimize())
ipcMain.on('window:maximize', () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize()
  } else {
    mainWindow?.maximize()
  }
})
ipcMain.on('window:close', () => mainWindow?.close())
handleTrusted('window:isMaximized', () => mainWindow?.isMaximized())
handleTrusted('platform:info', () => ({
  platform: process.platform,
  arch: process.arch,
  version: app.getVersion(),
}))

// 注册文件系统 IPC
registerFsHandlers()

// 注册后端管理 IPC
registerBackendHandlers()

// 应用启动
app.whenReady().then(async () => {
  if (!ownsDesktopInstance) return
  createWindow()

  // 先启动 Draw.io 导出服务，端口确定后再启动 Python 后端
  try {
    await registerDrawioHandlers()
    process.env.MERAK_ELECTRON_API_PORT = String(getElectronApiPort())
  } catch (error) {
    process.env.MERAK_ELECTRON_API_PORT = '0'
    console.error('[Merak] Figure export helper failed to start:', error)
  }

  // 后端状态变化时通知渲染进程
  backendManager.onStatusChange((state) => {
    mainWindow?.webContents.send('backend:statusChange', state)
  })

  // Register the listener before startup so the first status is observable.
  backendManager.start().catch((err) => {
    console.error('[Merak] Backend start failed:', err)
  })

  await loadApp()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

// 退出前清理后端进程
app.on('before-quit', async (e) => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    e.preventDefault()
    mainWindow.close()
    return
  }
  if (backendManager.getState().status !== 'stopped') {
    e.preventDefault()
    await backendManager.stop()
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
    void loadApp().catch((error) => {
      console.error('[Merak] Window reload failed:', error)
      mainWindow?.show()
    })
  }
})
