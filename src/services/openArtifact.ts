import { API_BASE } from '../config'

/** Desktop exports open by an authenticated request; web previews keep their blob/session URL. */
export function openArtifact(path: string, url: string): void {
  if (!window.merakIDE) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  void fetch(`${API_BASE}/api/files/open-external`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }),
  }).then(async response => {
    if (!response.ok) throw new Error(`打开文件失败 (${response.status})`)
  }).catch(error => window.dispatchEvent(new CustomEvent('merak-ide:save-warning', { detail: String(error) })))
}
