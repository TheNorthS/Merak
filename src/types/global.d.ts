/**
 * 全局类型声明 — Electron preload 暴露的 API
 */
import type { RendererStartupNotice } from '@shared/renderer-startup'

export type BackendStatus = 'stopped' | 'starting' | 'ready' | 'error' | 'restarting'

export interface BackendState {
  status: BackendStatus
  port: number
  pid: number | null
  error: string | null
  restartCount: number
}

export interface MerakIDEAPI {
  startup: {
    notify: (notice: RendererStartupNotice) => void
  }
  window: {
    minimize: () => void
    maximize: () => void
    close: () => void
    isMaximized: () => Promise<boolean>
  }
  platform: {
    getInfo: () => Promise<{ platform: string; arch: string; version: string }>
  }
  appState: {
    get: (key: 'projectPath') => Promise<string | null>
    set: (key: 'projectPath', value: string | null) => Promise<void>
  }
  backend: {
    getStatus: () => Promise<BackendState>
    restart: () => Promise<void>
    getLogs: () => Promise<string[]>
    getPort: () => Promise<number>
    onStatusChange: (callback: (state: BackendState) => void) => () => void
  }
  ssh: {
    connect: (config: unknown) => Promise<string>
    disconnect: (id: string) => Promise<void>
    exec: (id: string, command: string) => Promise<string>
  }
  fs: {
    readDir: (path: string) => Promise<Array<{ name: string; path: string; isDirectory: boolean; size: number; modified: number }>>
    readFile: (path: string) => Promise<string>
    writeFile: (path: string, content: string) => Promise<void>
    stat: (path: string) => Promise<{ size: number; isDirectory: boolean; isFile: boolean; modified: number; created: number }>
    createFile: (path: string) => Promise<boolean>
    createDir: (path: string) => Promise<boolean>
    rename: (oldPath: string, newPath: string) => Promise<boolean>
    delete: (path: string) => Promise<boolean>
    move: (src: string, destDir: string) => Promise<boolean>
    openFolder: () => Promise<string | null>
    newProject: (name: string) => Promise<string | null>
    openFile: (filters?: Array<{ name: string; extensions: string[] }>) => Promise<string | null>
  }
}

declare global {
  interface Window {
    merakIDE: MerakIDEAPI
  }
}
