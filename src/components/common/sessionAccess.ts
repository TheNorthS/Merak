export interface SessionAccess {
  status: 'checking' | 'ready' | 'login' | 'unavailable'
  message: string
}

export function pendingSessionAccess(desktop: boolean): SessionAccess {
  return { status: 'checking', message: desktop ? '正在启动本地服务…' : '正在连接研究工作区…' }
}

/** A missing desktop capability is a connection failure, never a password prompt. */
export async function requestSessionAccess(
  desktop: boolean, endpoint: string, signal: AbortSignal, request = fetch,
): Promise<SessionAccess> {
  try {
    const response = await request(endpoint, { credentials: 'include', signal })
    if (response.ok) return { status: 'ready', message: '' }
    if (response.status === 401 && !desktop) return { status: 'login', message: '请登录以访问研究工作区。' }
    return { status: 'unavailable', message: desktop
      ? '本地服务暂时无法连接，正在自动重试。你也可以重启本地服务。'
      : `无法访问研究工作区（HTTP ${response.status}），正在自动重试。` }
  } catch {
    return { status: 'unavailable', message: desktop
      ? '正在等待本地服务启动，连接恢复后会自动进入工作区。'
      : '暂时无法连接后端，正在自动重试。' }
  }
}
