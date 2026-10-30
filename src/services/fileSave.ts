import { API_BASE } from '../config'
import { useWorkspaceStore, type OpenFile } from '../stores/workspace'

const pendingWrites = new Map<string, Promise<void>>()
const key = (path: string) => path.replace(/\\/g, '/').toLowerCase()

/** Confirm only the exact document revision written; serialize writes per path. */
export async function saveFile(path: string): Promise<void> {
  const snapshot = useWorkspaceStore.getState().openFiles.find(file => key(file.path) === key(path))
  if (!snapshot?.isDirty) return
  const identity = key(path)
  const previous = pendingWrites.get(identity) ?? Promise.resolve()
  const current = previous.catch(() => {}).then(() => writeSnapshot(snapshot))
  pendingWrites.set(identity, current)
  try {
    await current
  } finally {
    if (pendingWrites.get(identity) === current) pendingWrites.delete(identity)
  }
}

async function writeSnapshot(snapshot: OpenFile): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/files/write`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: snapshot.path, content: snapshot.content }),
    })
  } catch (error) {
    if (!window.merakIDE?.fs?.writeFile) throw error
    await window.merakIDE.fs.writeFile(snapshot.path, snapshot.content)
    useWorkspaceStore.getState().markFileSaved(snapshot)
    window.dispatchEvent(new Event('merak-ide:files-changed'))
    return
  }
  if (!response.ok) throw new Error(`保存失败 (${response.status}): ${await response.text()}`)
  const payload = await response.json() as { figure_refresh?: { success: boolean; error?: string } }
  useWorkspaceStore.getState().markFileSaved(snapshot)
  window.dispatchEvent(new Event('merak-ide:files-changed'))
  if (payload.figure_refresh?.success === false) {
    window.dispatchEvent(new CustomEvent('merak-ide:save-warning', {
      detail: payload.figure_refresh.error || '文件已保存，但预览更新失败。',
    }))
  }
}

/** Compilation can consume only a saved revision, never a moving editor buffer. */
export async function saveForCompilation(path: string): Promise<void> {
  await saveFile(path)
  if (useWorkspaceStore.getState().openFiles.some(file => key(file.path) === key(path) && file.isDirty)) {
    throw new Error('保存期间文件已被继续编辑，请保存最新内容后再编译。')
  }
}
