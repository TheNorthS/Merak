import { useState, useRef, type ReactNode, type FormEvent } from 'react'
import { API_BASE } from '../../config'
import { useSessionAccess } from './useSessionAccess'
import { StartupScreen } from './StartupScreen'

/** Native requests carry a desktop capability; web sessions use an HttpOnly cookie. */
export function SessionGate({ children }: { children: ReactNode }) {
  const desktop = Boolean(window.merakIDE) || window.location.protocol === 'file:'
  const { access, publish, retry, restart } = useSessionAccess(desktop)
  const ready = access.status === 'ready'
  const admitted = useRef(false)
  if (ready) admitted.current = true
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = async (event: FormEvent) => {
    event.preventDefault()
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!response.ok) throw new Error('登录失败，请检查用户名和密码。')
      setPassword('')
      await retry()
    } catch (error) { publish({ status: 'login', message: error instanceof Error ? error.message : '连接失败' }) }
  }
  return <>{admitted.current && <div className={ready ? 'h-full' : 'hidden'}>{children}</div>}
    {!ready && <div className="h-screen grid place-items-center bg-background text-foreground">
    {!desktop && access.status === 'login' ? <form onSubmit={login} className="flex flex-col gap-4 w-80">
      <p role="status">{access.message}</p>
      <label>用户名<input className="w-full border p-2 bg-background" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label>
      <label>密码<input className="w-full border p-2 bg-background" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
      <button className="border p-2" type="submit">登录</button>
    </form> : <StartupScreen access={access} desktop={desktop} retry={retry} restart={restart} />}
  </div>}</>
}
