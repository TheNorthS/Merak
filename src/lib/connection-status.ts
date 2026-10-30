import { API_BASE } from '../config'

export type VerificationState = {
  configured?: boolean
  tested: boolean
  verified: boolean
  stale: boolean
  tested_at?: string | null
  message?: string
}

export type IntegrationState = VerificationState & {
  label: string
}

export type SshServerConfig = {
  id: string
  name: string
  host: string
  port: number
  user: string
  auth: 'key' | 'password'
  keyPath: string
  password: string
  condaEnv: string
  workDir: string
  hostKeyFingerprint?: string
  verification?: VerificationState
}

export const SSH_SERVERS_STORAGE_KEY = 'merak-ide:sshServers'

export function readSshServers(): SshServerConfig[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(SSH_SERVERS_STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function writeSshServers(servers: SshServerConfig[]) {
  localStorage.setItem(SSH_SERVERS_STORAGE_KEY, JSON.stringify(servers))
  window.dispatchEvent(new Event('merak-ide:ssh-servers-changed'))
}

export async function syncSshServers(servers = readSshServers()): Promise<SshServerConfig[]> {
  const response = await fetch(`${API_BASE}/api/ssh/servers`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ servers }),
  })
  if (!response.ok) throw new Error(`SSH configuration sync failed (${response.status})`)
  const data = await response.json() as { verification?: Record<string, VerificationState> }
  const verification = data.verification || {}
  const merged = servers.map(server => ({
    ...server,
    verification: verification[server.id] || server.verification,
  }))
  writeSshServers(merged)
  return merged
}

export function verificationLabel(state?: Partial<VerificationState>, configured = true) {
  if (!configured || state?.configured === false) return '未配置'
  if (state?.stale) return '配置已变更'
  if (state?.verified) return '已验证'
  if (state?.tested) return '测试失败'
  return '待测试'
}
