import { contextBridge, ipcRenderer } from 'electron'
import { RENDERER_STARTUP_CHANNEL, type RendererStartupNotice } from '../shared/renderer-startup'

/**
 * Merak Preload — 安全暴露 IPC 通道给渲染进程
 */
contextBridge.exposeInMainWorld('merakIDE', {
  startup: {
    notify: (notice: RendererStartupNotice) => ipcRenderer.send(RENDERER_STARTUP_CHANNEL, notice),
  },

  // 窗口控制
  window: {
    minimize: () => ipcRenderer.send('window:minimize'),
    maximize: () => ipcRenderer.send('window:maximize'),
    close: () => ipcRenderer.send('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
  },

  // 平台信息
  platform: {
    getInfo: () => ipcRenderer.invoke('platform:info'),
  },

  appState: {
    get: (key: 'projectPath') => ipcRenderer.invoke('app-state:get', key),
    set: (key: 'projectPath', value: string | null) => ipcRenderer.invoke('app-state:set', key, value),
  },

  // 后端管理
  backend: {
    getStatus: () => ipcRenderer.invoke('backend:status'),
    restart: () => ipcRenderer.invoke('backend:restart'),
    getLogs: () => ipcRenderer.invoke('backend:logs'),
    getPort: () => ipcRenderer.invoke('backend:port'),
    onStatusChange: (callback: (state: any) => void) => {
      const handler = (_event: any, state: any) => callback(state)
      ipcRenderer.on('backend:statusChange', handler)
      // 返回 cleanup 函数
      return () => ipcRenderer.removeListener('backend:statusChange', handler)
    },
  },

  // SSH（Phase 2 扩展）
  ssh: {
    connect: (config: unknown) => ipcRenderer.invoke('ssh:connect', config),
    disconnect: (id: string) => ipcRenderer.invoke('ssh:disconnect', id),
    exec: (id: string, command: string) => ipcRenderer.invoke('ssh:exec', id, command),
  },

  // Draw.io 导出（保存 base64 数据到磁盘）
  drawio: {
    saveExport: (data: string, format: string, outputPath: string) =>
      ipcRenderer.invoke('drawio:save-export', { data, format, outputPath }),
  },

  // 剪贴板（IPC → Electron clipboard 模块，绕过浏览器权限）
  clipboard: {
    read: (): Promise<string> => ipcRenderer.invoke('clipboard:read'),
    write: (text: string): Promise<void> => ipcRenderer.invoke('clipboard:write', text),
  },

  // 本地文件系统
  fs: {
    readDir: (path: string) => ipcRenderer.invoke('fs:readDir', path),
    readFile: (path: string) => ipcRenderer.invoke('fs:readFile', path),
    writeFile: (path: string, content: string) => ipcRenderer.invoke('fs:writeFile', path, content),
    stat: (path: string) => ipcRenderer.invoke('fs:stat', path),
    createFile: (path: string) => ipcRenderer.invoke('fs:createFile', path),
    createDir: (path: string) => ipcRenderer.invoke('fs:createDir', path),
    rename: (oldPath: string, newPath: string) => ipcRenderer.invoke('fs:rename', oldPath, newPath),
    delete: (path: string) => ipcRenderer.invoke('fs:delete', path),
    move: (src: string, destDir: string) => ipcRenderer.invoke('fs:move', src, destDir),
    openFolder: () => ipcRenderer.invoke('fs:openFolder'),
    newProject: (name: string) => ipcRenderer.invoke('fs:newProject', name),
    openFile: (filters?: Array<{ name: string; extensions: string[] }>) => ipcRenderer.invoke('fs:openFile', filters),
  },
})
