import type { BackendState } from '../../types/global'
import type { SessionAccess } from './sessionAccess'

/** Stage advancement follows backend readiness and session verification, never a timer. */
export function startupPresentation(access: SessionAccess, backend: BackendState | null, desktop: boolean) {
  const starting = desktop && (backend?.status === 'starting' || backend?.status === 'restarting')
  const failed = backend?.status === 'error' || (access.status === 'unavailable' && !starting)
  const stage = !desktop || backend?.status === 'ready' ? 2 : 1
  const title = failed ? '连接暂时中断' : stage === 2 ? '正在连接你的工作区' : '正在准备研究环境'
  const detail = backend?.status === 'error' ? '本地服务未能启动，请重新连接或重启本地服务。' : failed ? access.message : starting
    ? '本地服务正在启动，准备好后将自动进入。'
    : stage === 2 ? '正在确认连接，即将进入工作区。' : '正在唤醒本地服务，请稍候。'
  return { stage, failed, title, detail }
}
