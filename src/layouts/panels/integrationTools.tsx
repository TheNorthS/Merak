import { useState, useEffect } from 'react'
import { Trash2, CheckCircle2, CircleAlert, Server } from 'lucide-react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { type SshServerConfig, type VerificationState, readSshServers, syncSshServers, writeSshServers } from '@/lib/connection-status'
import { ConnectionStateBadge, ConnectionTestButton } from './settingsFields'
import { useMetaOptimize } from './useMetaOptimize'

export function MetaOptimizePanel() {
  const projectPath = useWorkspaceStore(s => s.projectPath)
  const { mutations, error, busy, handleAction } = useMetaOptimize(projectPath)

  if (mutations.length === 0) {
    return <p className="text-2xs text-muted-foreground">{error || (projectPath ? '当前没有优化提案。启用自进化优化后，Agent 会根据工作流反馈提出可审阅的修改。' : '请先打开研究项目。')}</p>
  }

  return (
    <div className="space-y-1.5">
      {error && <p role="alert" className="text-2xs text-red-400">{error}</p>}
      {mutations.map(m => (
        <Card key={m.id} className="border-border bg-background">
          <CardContent className="p-2 text-2xs">
            <div className="flex items-center justify-between">
              <span className="text-foreground font-mono">/{m.skill_name}</span>
              <Badge
                variant="outline"
                className={cn(
                  'text-2xs',
                  m.status === 'pending' && 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
                  m.status === 'applied' && 'bg-green-500/20 text-green-400 border-green-500/30',
                  m.status !== 'pending' && m.status !== 'applied' && 'bg-gray-500/20 text-muted-foreground border-gray-500/30'
                )}
              >
                {m.status}
              </Badge>
            </div>
            <p className="text-muted-foreground mt-0.5">{m.description?.slice(0, 80)}</p>
            <details className="mt-1"><summary>查看技能修改</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap">{m.diff}</pre></details>
            {m.status === 'pending' && (
              <div className="flex gap-1 mt-1.5">
                <Button size="sm" disabled={busy} onClick={() => handleAction(m.id, 'approve')} className="h-5 px-2 text-2xs bg-green-600 text-white hover:bg-green-700">Approve</Button>
                <Button size="sm" disabled={busy} variant="destructive" onClick={() => handleAction(m.id, 'reject')} className="h-5 px-2 text-2xs">Reject</Button>
              </div>
            )}
            {m.status === 'applied' && (
              <Button size="sm" disabled={busy} onClick={() => handleAction(m.id, 'rollback')} className="mt-1.5 h-5 px-2 text-2xs bg-yellow-600 text-white hover:bg-yellow-700">Rollback</Button>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

export function SshConfigSection() {
  const [servers, setServers] = useState<SshServerConfig[]>(readSshServers)
  const [adding, setAdding] = useState(false)
  const [testingServerId, setTestingServerId] = useState('')
  const [connectionResult, setConnectionResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [form, setForm] = useState({
    name: '', host: '', port: '22', user: 'root', auth: 'key' as 'key' | 'password',
    keyPath: '~/.ssh/id_rsa', password: '', condaEnv: '', workDir: '~',
  })

  useEffect(() => {
    let active = true
    syncSshServers()
      .then(synced => { if (active) setServers(synced) })
      .catch(error => {
        if (active) setConnectionResult({ ok: false, message: error instanceof Error ? error.message : 'SSH 配置同步失败' })
      })
    return () => { active = false }
  }, [])

  const save = async (list: SshServerConfig[]) => {
    setServers(list)
    writeSshServers(list)
    try {
      const synced = await syncSshServers(list)
      setServers(synced)
    } catch (error) {
      setConnectionResult({ ok: false, message: error instanceof Error ? error.message : 'SSH 配置同步失败' })
    }
  }

  const handleAdd = () => {
    if (!form.name.trim() || !form.host.trim() || !form.user.trim()) return
    const newServer: SshServerConfig = {
      id: `ssh_${Date.now()}`,
      name: form.name.trim(),
      host: form.host.trim(),
      port: Number(form.port) || 22,
      user: form.user.trim(),
      auth: form.auth,
      keyPath: form.auth === 'key' ? form.keyPath : '',
      password: form.auth === 'password' ? form.password : '',
      condaEnv: form.condaEnv,
      workDir: form.workDir || '~',
      hostKeyFingerprint: '',
      verification: { tested: false, verified: false, stale: false, message: '尚未测试连接' },
    }
    void save([...servers, newServer])
    setForm({ name: '', host: '', port: '22', user: 'root', auth: 'key', keyPath: '~/.ssh/id_rsa', password: '', condaEnv: '', workDir: '~' })
    setAdding(false)
    setConnectionResult({ ok: true, message: '服务器已保存，请测试连接后再用于远程实验' })
  }

  const handleRemove = (serverId: string) => {
    void save(servers.filter(server => server.id !== serverId))
  }

  const handleTest = async (server: SshServerConfig) => {
    setTestingServerId(server.id)
    setConnectionResult(null)
    try {
      await syncSshServers(servers)
      const response = await fetch(`${API_BASE}/api/ssh/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(server),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || `连接测试失败（HTTP ${response.status}）`)
      const updated = servers.map(item => item.id === server.id
        ? {
            ...item,
            hostKeyFingerprint: String(data.host_key_fingerprint || item.hostKeyFingerprint || ''),
            verification: data.verification as VerificationState,
          }
        : item)
      writeSshServers(updated)
      const synced = await syncSshServers(updated)
      setServers(synced)
      window.dispatchEvent(new Event('merak-ide:connection-status-changed'))
      setConnectionResult({
        ok: data.success === true,
        message: data.success ? (data.message || `已连接 ${server.host}`) : (data.error || '连接测试失败'),
      })
    } catch (error) {
      setConnectionResult({ ok: false, message: error instanceof Error ? error.message : '后端不可达' })
    } finally {
      setTestingServerId('')
    }
  }

  return (
    <div className="space-y-2.5">
      {connectionResult && (
        <div className={cn(
          'flex items-start gap-2 rounded-md border px-2.5 py-2 text-2xs leading-4',
          connectionResult.ok
            ? 'border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400'
            : 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400',
        )}>
          {connectionResult.ok ? <CheckCircle2 size={13} className="mt-0.5 shrink-0" /> : <CircleAlert size={13} className="mt-0.5 shrink-0" />}
          <span className="min-w-0 break-words">{connectionResult.message}</span>
        </div>
      )}

      {servers.length === 0 && !adding && (
        <div className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-3 text-center">
          <Server size={18} className="mx-auto mb-1.5 text-muted-foreground" />
          <p className="text-xs font-medium text-foreground">未配置 SSH 服务器</p>
          <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">添加并通过连接测试后，才可选作远程实验目标。</p>
        </div>
      )}

      {servers.map(server => (
        <div key={server.id} className="rounded-md border border-border bg-background p-2.5">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-start gap-2">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
                <Server size={14} className="text-muted-foreground" />
              </div>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-xs font-medium text-foreground">{server.name}</span>
                  <ConnectionStateBadge state={server.verification} configured />
                </div>
                <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                  {server.user}@{server.host}:{server.port}
                </p>
                {server.hostKeyFingerprint && (
                  <p className="mt-0.5 truncate font-mono text-[9px] text-muted-foreground" title={server.hostKeyFingerprint}>
                    Host key {server.hostKeyFingerprint}
                  </p>
                )}
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={() => handleRemove(server.id)}
              className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
              title="删除服务器"
            >
              <Trash2 size={13} />
            </Button>
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 border-t border-border/70 pt-2">
            <p className="min-w-0 truncate text-[10px] text-muted-foreground">
              {server.verification?.message || '尚未测试连接'}
            </p>
            <ConnectionTestButton
              busy={testingServerId === server.id}
              disabled={!!testingServerId && testingServerId !== server.id}
              onClick={() => handleTest(server)}
            />
          </div>
        </div>
      ))}

      {adding ? (
        <div className="space-y-2 rounded-md border border-border bg-card p-2.5">
          <div className="flex items-center gap-2 text-xs font-medium text-foreground">
            <Server size={14} />添加 SSH 服务器
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <Input value={form.name} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} placeholder="名称，如 Lab A100" className="h-8 text-xs" />
            <Input value={form.host} onChange={event => setForm(current => ({ ...current, host: event.target.value }))} placeholder="主机 IP 或域名" className="h-8 text-xs" />
            <Input value={form.port} onChange={event => setForm(current => ({ ...current, port: event.target.value }))} placeholder="端口" className="h-8 text-xs" />
            <Input value={form.user} onChange={event => setForm(current => ({ ...current, user: event.target.value }))} placeholder="用户名" className="h-8 text-xs" />
          </div>
          <div className="flex items-center gap-2">
            <Label className="text-2xs text-muted-foreground">认证方式</Label>
            <Select value={form.auth} onValueChange={value => setForm(current => ({ ...current, auth: value as 'key' | 'password' }))}>
              <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="key">SSH Key</SelectItem>
                <SelectItem value="password">Password</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {form.auth === 'key' ? (
            <Input value={form.keyPath} onChange={event => setForm(current => ({ ...current, keyPath: event.target.value }))} placeholder="密钥路径：~/.ssh/id_rsa" className="h-8 text-xs" />
          ) : (
            <Input type="password" value={form.password} onChange={event => setForm(current => ({ ...current, password: event.target.value }))} placeholder="SSH 密码" className="h-8 text-xs" />
          )}
          <div className="grid grid-cols-2 gap-1.5">
            <Input value={form.condaEnv} onChange={event => setForm(current => ({ ...current, condaEnv: event.target.value }))} placeholder="Conda 环境（可选）" className="h-8 text-xs" />
            <Input value={form.workDir} onChange={event => setForm(current => ({ ...current, workDir: event.target.value }))} placeholder="工作目录：~" className="h-8 text-xs" />
          </div>
          <div className="flex justify-end gap-1.5">
            <Button type="button" size="xs" variant="ghost" onClick={() => setAdding(false)}>取消</Button>
            <Button type="button" size="xs" onClick={handleAdd} disabled={!form.name.trim() || !form.host.trim() || !form.user.trim()}>保存服务器</Button>
          </div>
        </div>
      ) : (
        <Button variant="outline" size="sm" onClick={() => setAdding(true)} className="w-full text-xs">
          添加 SSH 服务器
        </Button>
      )}
    </div>
  )
}
