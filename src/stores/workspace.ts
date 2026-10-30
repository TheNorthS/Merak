import { create } from 'zustand'

const normalizePathKey = (path: string) => path.replace(/\\/g, '/').toLowerCase()

const readStoredProjectPath = () => {
  try {
    // Electron uses application-level IPC storage so a fallback Vite port does
    // not restore an unrelated origin-specific project.
    if (window.merakIDE?.appState) return null
    return localStorage.getItem('merak-ide:projectPath') || null
  } catch {
    return null
  }
}

export interface OpenFile {
  path: string
  name: string
  language: string
  content: string
  isDirty: boolean
  revision: number
  documentId: number
}

let nextDocumentId = 0

interface WorkspaceState {
  // 当前打开的项目路径
  projectPath: string | null
  setProjectPath: (path: string | null) => void
  hydrateProjectPath: () => Promise<void>

  // 侧边栏
  activeSidebarPanel: string | null
  setActiveSidebarPanel: (panel: string | null) => void

  // 打开的文件
  openFiles: OpenFile[]
  activeFileIndex: number
  openFile: (file: Omit<OpenFile, 'isDirty' | 'revision' | 'documentId'>) => void
  closeFile: (path: string) => void
  closeAllFiles: () => void
  closeOtherFiles: (path: string) => void
  closeFilesToLeft: (path: string) => void
  closeFilesToRight: (path: string) => void
  setActiveFile: (index: number) => void
  updateFileContent: (path: string, content: string) => void
  replaceFileContent: (path: string, content: string) => void
  markFileSaved: (snapshot: OpenFile) => void

  // Workflow 全屏模式
  workflowFullscreen: boolean
  setWorkflowFullscreen: (v: boolean) => void

  // Chat 右栏
  chatOpen: boolean
  setChatOpen: (v: boolean) => void

  // 主题
  theme: 'dark' | 'light'
  toggleTheme: () => void
}

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  projectPath: readStoredProjectPath(),
  setProjectPath: (path) => {
    const nextPath = path || null
    const currentPath = get().projectPath
    if (currentPath === nextPath) return
    if (get().openFiles.some(file => file.isDirty) && !window.confirm(
      '有未保存的修改。确定放弃修改并切换/关闭项目？取消后可以先保存文件。',
    )) return

    try {
      if (nextPath) localStorage.setItem('merak-ide:projectPath', nextPath)
      else localStorage.removeItem('merak-ide:projectPath')
    } catch {
      // Project switching must still work if storage is unavailable.
    }
    void window.merakIDE?.appState?.set('projectPath', nextPath).catch(() => {})

    set({
      projectPath: nextPath,
      openFiles: [],
      activeFileIndex: -1,
    })
  },
  hydrateProjectPath: async () => {
    if (!window.merakIDE?.appState) return
    const initialPath = get().projectPath
    try {
      const stored = await window.merakIDE.appState.get('projectPath')
      // Do not overwrite a project selected while the async read was pending.
      if (get().projectPath !== initialPath) return
      const nextPath = typeof stored === 'string' && stored.trim() ? stored : null
      set({ projectPath: nextPath, openFiles: [], activeFileIndex: -1 })
    } catch {
      // An unreadable app-state file should open with no project, never with a
      // stale project inherited from a Vite port.
    }
  },

  activeSidebarPanel: 'files',
  setActiveSidebarPanel: (panel) => {
    const current = get().activeSidebarPanel
    set({ activeSidebarPanel: current === panel ? null : panel })
  },

  openFiles: [],
  activeFileIndex: -1,

  openFile: (file) => {
    const { openFiles } = get()
    const fileKey = normalizePathKey(file.path)
    const existingIndex = openFiles.findIndex((f) => normalizePathKey(f.path) === fileKey)
    if (existingIndex >= 0) {
      set({
        activeFileIndex: existingIndex,
        openFiles: openFiles.map((f, index) =>
          index === existingIndex && !f.isDirty ? { ...f, ...file, isDirty: false } : f,
        ),
      })
    } else {
      set({
        openFiles: [...openFiles, { ...file, isDirty: false, revision: 0, documentId: ++nextDocumentId }],
        activeFileIndex: openFiles.length,
      })
    }
  },

  closeFile: (path) => {
    const { openFiles, activeFileIndex } = get()
    const pathKey = normalizePathKey(path)
    const closedIndex = openFiles.findIndex((f) => normalizePathKey(f.path) === pathKey)
    if (closedIndex < 0) return

    const newFiles = openFiles.filter((f) => normalizePathKey(f.path) !== pathKey)
    let newIndex = activeFileIndex
    if (closedIndex <= activeFileIndex) {
      newIndex = Math.max(0, activeFileIndex - 1)
    }
    if (newFiles.length === 0) newIndex = -1
    if (newIndex >= newFiles.length) newIndex = newFiles.length - 1
    set({ openFiles: newFiles, activeFileIndex: newIndex })
  },

  closeAllFiles: () => set({ openFiles: [], activeFileIndex: -1 }),

  closeOtherFiles: (path) => {
    const pathKey = normalizePathKey(path)
    const target = get().openFiles.find((file) => normalizePathKey(file.path) === pathKey)
    if (target) set({ openFiles: [target], activeFileIndex: 0 })
  },

  closeFilesToLeft: (path) => {
    const { openFiles, activeFileIndex } = get()
    const targetIndex = openFiles.findIndex((file) => normalizePathKey(file.path) === normalizePathKey(path))
    if (targetIndex <= 0) return
    const nextFiles = openFiles.slice(targetIndex)
    const nextActive = activeFileIndex >= targetIndex ? activeFileIndex - targetIndex : 0
    set({ openFiles: nextFiles, activeFileIndex: Math.min(nextActive, nextFiles.length - 1) })
  },

  closeFilesToRight: (path) => {
    const { openFiles, activeFileIndex } = get()
    const targetIndex = openFiles.findIndex((file) => normalizePathKey(file.path) === normalizePathKey(path))
    if (targetIndex < 0 || targetIndex >= openFiles.length - 1) return
    const nextFiles = openFiles.slice(0, targetIndex + 1)
    const nextActive = activeFileIndex <= targetIndex ? activeFileIndex : targetIndex
    set({ openFiles: nextFiles, activeFileIndex: Math.max(0, nextActive) })
  },
  setActiveFile: (index) => {
    const { openFiles } = get()
    set({ activeFileIndex: index >= 0 && index < openFiles.length ? index : -1 })
  },

  updateFileContent: (path, content) => {
    const { openFiles } = get()
    const pathKey = normalizePathKey(path)
    set({
      openFiles: openFiles.map((f) =>
        normalizePathKey(f.path) === pathKey ? { ...f, content, isDirty: true, revision: f.revision + 1 } : f,
      ),
    })
  },

  replaceFileContent: (path, content) => {
    const { openFiles } = get()
    const pathKey = normalizePathKey(path)
    set({
      openFiles: openFiles.map((f) =>
        normalizePathKey(f.path) === pathKey ? { ...f, content, isDirty: false, revision: f.revision + 1 } : f,
      ),
    })
  },

  markFileSaved: (snapshot) => set(state => ({
    openFiles: state.openFiles.map(file => (
      file.documentId === snapshot.documentId && file.revision === snapshot.revision
        ? { ...file, isDirty: false } : file
    )),
  })),

  theme: 'dark',
  toggleTheme: () =>
    set((s) => ({ theme: s.theme === 'dark' ? 'light' : 'dark' })),

  workflowFullscreen: false,
  setWorkflowFullscreen: (v) => set({ workflowFullscreen: v }),

  chatOpen: false,
  setChatOpen: (v) => set({ chatOpen: v }),
}))
