import React, { useState, useEffect } from 'react'
import { PlugZap, Loader2, CheckCircle2, CircleAlert } from 'lucide-react'
import { API_BASE } from '../../config'
import { useWorkspaceStore } from '../../stores/workspace'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { type IntegrationState, type VerificationState } from '@/lib/connection-status'
import { SettingsField, ConnectionSectionHeader } from './settingsFields'
import { MetaOptimizePanel } from './integrationTools'

export function IntegrationsTab({ models, setModels, onSave, saving }: {
  models: Record<string, any>;
  setModels: React.Dispatch<React.SetStateAction<any>>;
  onSave: () => void;
  saving: boolean;
}) {
  type ActionStatus = { ok: boolean; message: string }
  type OverleafProjectStatus = {
    project_id: string
    local_path: string
    branch: string
    linked: boolean
    credentials_available: boolean
    verified: boolean
    main_document?: string
    last_sync?: string | null
    last_error?: string
  }
  const projectPath = useWorkspaceStore(state => state.projectPath)
  const [overleafId, setOverleafId] = useState('')
  const [overleafEmail, setOverleafEmail] = useState('')
  const [overleafToken, setOverleafToken] = useState('')
  const [overleafStatus, setOverleafStatus] = useState<ActionStatus | null>(null)
  const [overleafProjects, setOverleafProjects] = useState<OverleafProjectStatus[]>([])
  const [overleafBusy, setOverleafBusy] = useState('')
  const [feishuWebhook, setFeishuWebhook] = useState('')
  const [slackWebhook, setSlackWebhook] = useState('')
  const [emailHost, setEmailHost] = useState('')
  const [emailPort, setEmailPort] = useState('465')
  const [emailSender, setEmailSender] = useState('')
  const [emailPassword, setEmailPassword] = useState('')
  const [emailRecipients, setEmailRecipients] = useState('')
  const [notifyConfigured, setNotifyConfigured] = useState({ feishu: false, slack: false, email: false })
  const [notifyEnabled, setNotifyEnabled] = useState({ feishu: false, slack: false, email: false })
  const [notifyVerification, setNotifyVerification] = useState<Record<string, VerificationState>>({})
  const [notifyStatus, setNotifyStatus] = useState<ActionStatus | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<Record<string, IntegrationState>>({})
  const [testingService, setTestingService] = useState('')
  const [connectionResult, setConnectionResult] = useState<{ service: string; ok: boolean; message: string } | null>(null)

  const responseError = (data: any, fallback: string) => {
    const detail = data?.detail
    if (typeof detail === 'string') return detail
    if (detail?.errors) return Object.entries(detail.errors).map(([key, value]) => key + ': ' + String(value)).join('; ')
    if (data?.message) return String(data.message)
    return fallback
  }

  const normalizePath = (value: string) => value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()

  const loadOverleafProjects = async () => {
    const response = await fetch(API_BASE + '/api/overleaf/projects')
    if (!response.ok) throw new Error('Overleaf project list failed (HTTP ' + response.status + ')')
    const data = await response.json()
    const projects = Array.isArray(data) ? data as OverleafProjectStatus[] : []
    setOverleafProjects(projects)
    const expected = projectPath ? normalizePath(projectPath + '/paper') : ''
    const match = projects.find(item => normalizePath(item.local_path) === expected)
    setOverleafId(match?.project_id || '')
    return projects
  }

  const loadNotificationConfig = async () => {
    const response = await fetch(API_BASE + '/api/notify/config')
    if (!response.ok) throw new Error('Notification config failed (HTTP ' + response.status + ')')
    const data = await response.json()
    const enabled = Array.isArray(data.enabled_channels) ? data.enabled_channels : []
    const verification = data.verification && typeof data.verification === 'object' ? data.verification : {}
    setNotifyVerification(verification)
    setNotifyConfigured({
      feishu: data.feishu_webhook === true,
      slack: data.slack_webhook === true,
      email: data.email_configured === true,
    })
    setNotifyEnabled({
      feishu: enabled.includes('feishu') && verification.feishu?.verified === true,
      slack: enabled.includes('slack') && verification.slack?.verified === true,
      email: enabled.includes('email') && verification.email?.verified === true,
    })
    setEmailHost(String(data.email_smtp_host || ''))
    setEmailPort(String(data.email_smtp_port || 465))
    setEmailSender(String(data.email_sender || ''))
    setEmailRecipients(Array.isArray(data.email_recipients) ? data.email_recipients.join(', ') : '')
  }

  const loadConnectionStatus = async () => {
    const response = await fetch(`${API_BASE}/api/settings/integration-status`)
    if (!response.ok) throw new Error(`Integration status request failed (${response.status})`)
    const data = await response.json()
    setConnectionStatus(data)
    return data
  }

  useEffect(() => {
    loadConnectionStatus().catch(() => {})
    const refresh = () => { loadConnectionStatus().catch(() => {}) }
    window.addEventListener('merak-ide:connection-status-changed', refresh)
    return () => window.removeEventListener('merak-ide:connection-status-changed', refresh)
  }, [])

  useEffect(() => {
    loadOverleafProjects().catch(error => {
      setOverleafStatus({ ok: false, message: error instanceof Error ? error.message : 'Overleaf 配置读取失败' })
    })
  }, [projectPath])

  useEffect(() => {
    loadNotificationConfig().catch(error => {
      setNotifyStatus({ ok: false, message: error instanceof Error ? error.message : '通知配置读取失败' })
    })
  }, [])

  const testIntegration = async (service: string) => {
    setTestingService(service)
    setConnectionResult(null)
    try {
      const saveResponse = await fetch(`${API_BASE}/api/settings/models`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(models),
      })
      if (!saveResponse.ok) throw new Error(`保存失败（HTTP ${saveResponse.status}）`)
      const response = await fetch(`${API_BASE}/api/settings/integrations/${service}/test`, { method: 'POST' })
      const data = await response.json()
      await loadConnectionStatus()
      window.dispatchEvent(new Event('merak-ide:connection-status-changed'))
      setConnectionResult({ service, ok: data.success === true, message: data.success ? (data.message || '连接成功') : (data.error || '连接测试失败') })
    } catch (error) {
      setConnectionResult({ service, ok: false, message: error instanceof Error ? error.message : '连接失败' })
    } finally {
      setTestingService('')
    }
  }

  const updateModelField = (field: string, value: string) => {
    setModels((prev: any) => ({ ...prev, [field]: value }))
    const service = field.startsWith('vastai_') ? 'vastai'
      : field.startsWith('modal_') ? 'modal'
        : field.startsWith('gemini_') ? 'gemini'
          : field.startsWith('gpt_image_') ? 'gpt_image'
            : field.startsWith('nano_banana_') ? 'nano_banana'
              : field.startsWith('exa_') ? 'exa'
                : field.startsWith('serpapi_') || field.startsWith('epo_ops_') ? 'patent'
                : field.startsWith('zotero_') ? 'zotero'
                  : field.startsWith('obsidian_') ? 'obsidian'
                    : ''
    if (service) {
      setConnectionStatus(prev => prev[service]
        ? { ...prev, [service]: { ...prev[service], verified: false, tested: false, stale: true } }
        : prev)
    }
  }

  const linkOverleaf = async () => {
    if (!projectPath) {
      setOverleafStatus({ ok: false, message: '请先打开研究项目' })
      return
    }
    if (!overleafId.trim() || !overleafToken.trim()) {
      setOverleafStatus({ ok: false, message: 'Project ID 和 token 必填' })
      return
    }
    setOverleafBusy('link')
    try {
      const response = await fetch(API_BASE + '/api/overleaf/link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: overleafId.trim(),
          local_path: projectPath,
          email: overleafEmail.trim(),
          token: overleafToken,
        }),
      })
      const data = await response.json()
      if (!response.ok || data.success !== true) throw new Error(responseError(data, 'Overleaf 关联失败'))
      setOverleafToken('')
      setOverleafStatus({ ok: true, message: data.message })
      await loadOverleafProjects()
      window.dispatchEvent(new Event('merak-ide:overleaf-changed'))
    } catch (error) {
      setOverleafStatus({ ok: false, message: error instanceof Error ? error.message : 'Overleaf 关联失败' })
    } finally {
      setOverleafBusy('')
    }
  }

  const syncOverleaf = async () => {
    setOverleafBusy('sync')
    try {
      const response = await fetch(API_BASE + '/api/overleaf/sync/' + encodeURIComponent(overleafId), { method: 'POST' })
      const data = await response.json()
      if (!response.ok || data.success !== true) {
        const conflicts = Array.isArray(data.conflicts) && data.conflicts.length ? ' 冲突: ' + data.conflicts.join(', ') : ''
        throw new Error(responseError(data, 'Overleaf 同步失败') + conflicts)
      }
      setOverleafStatus({ ok: true, message: data.message })
      await loadOverleafProjects()
    } catch (error) {
      setOverleafStatus({ ok: false, message: error instanceof Error ? error.message : 'Overleaf 同步失败' })
    } finally {
      setOverleafBusy('')
    }
  }

  const testOverleaf = async () => {
    setOverleafBusy('test')
    try {
      const response = await fetch(API_BASE + '/api/overleaf/test/' + encodeURIComponent(overleafId), { method: 'POST' })
      const data = await response.json()
      await loadOverleafProjects()
      if (!response.ok || data.success !== true) throw new Error(responseError(data, 'Overleaf 连接测试失败'))
      setOverleafStatus({ ok: true, message: data.message })
    } catch (error) {
      setOverleafStatus({ ok: false, message: error instanceof Error ? error.message : 'Overleaf 连接测试失败' })
    } finally {
      setOverleafBusy('')
    }
  }

  const saveNotificationConfig = async (showResult = true) => {
    const payload: Record<string, unknown> = {
      email_smtp_host: emailHost,
      email_smtp_port: Math.max(1, Number(emailPort) || 465),
      email_sender: emailSender,
      email_recipients: emailRecipients.split(',').map(item => item.trim()).filter(Boolean),
      enabled_channels: Object.entries(notifyEnabled).filter(([, enabled]) => enabled).map(([channel]) => channel),
    }
    if (feishuWebhook.trim()) payload.feishu_webhook = feishuWebhook.trim()
    if (slackWebhook.trim()) payload.slack_webhook = slackWebhook.trim()
    if (emailPassword) payload.email_password = emailPassword
    const response = await fetch(API_BASE + '/api/notify/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(responseError(data, '通知配置保存失败'))
    setFeishuWebhook('')
    setSlackWebhook('')
    setEmailPassword('')
    await loadNotificationConfig()
    if (showResult) setNotifyStatus({ ok: true, message: '通知配置已持久化' })
    return true
  }

  const saveNotifications = async () => {
    try {
      await saveNotificationConfig(true)
    } catch (error) {
      setNotifyStatus({ ok: false, message: error instanceof Error ? error.message : '通知配置保存失败' })
    }
  }

  const testNotification = async (channel: 'feishu' | 'slack' | 'email') => {
    setTestingService('notify-' + channel)
    try {
      await saveNotificationConfig(false)
      const response = await fetch(API_BASE + '/api/notify/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, message: 'Test notification from Merak' }),
      })
      const data = await response.json()
      if (!response.ok || data.success !== true) throw new Error(responseError(data, '通知投递失败'))
      await loadNotificationConfig()
      setNotifyStatus({ ok: true, message: channel + ' 已实际投递并收到成功响应' })
    } catch (error) {
      setNotifyStatus({ ok: false, message: error instanceof Error ? error.message : '通知投递失败' })
    } finally {
      setTestingService('')
    }
  }

  const invalidateNotification = (channel: 'feishu' | 'slack' | 'email') => {
    setNotifyEnabled(current => ({ ...current, [channel]: false }))
    setNotifyVerification(current => ({
      ...current,
      [channel]: {
        ...(current[channel] || {}),
        tested: false,
        verified: false,
        stale: true,
        message: '配置已变更，需要重新测试',
      },
    }))
  }

  const selectedOverleaf = overleafProjects.find(item => item.project_id === overleafId)

  return (
    <>
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

      {/* GPU 云服务 */}
      <Card className="border-border bg-card">
        <CardContent className="p-3 space-y-2">
          <span className="text-xs font-semibold text-foreground">GPU 云服务</span>
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Vast.ai" state={connectionStatus.vastai} busy={testingService === 'vastai'} onTest={() => testIntegration('vastai')} />
            <SettingsField onValueChange={updateModelField} label="API Key" value={models.vastai_api_key || ''} field="vastai_api_key" type="password" placeholder="从 vast.ai 获取" />
          </div>
          <Separator />
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Modal" state={connectionStatus.modal} busy={testingService === 'modal'} onTest={() => testIntegration('modal')} />
            <SettingsField onValueChange={updateModelField} label="Token ID" value={models.modal_token_id || ''} field="modal_token_id" type="password" placeholder="MODAL_TOKEN_ID" />
            <SettingsField onValueChange={updateModelField} label="Token Secret" value={models.modal_token_secret || ''} field="modal_token_secret" type="password" placeholder="MODAL_TOKEN_SECRET" />
          </div>
        </CardContent>
      </Card>

      {/* 搜索增强 & 图片生成 */}
      <Card className="border-border bg-card">
        <CardContent className="p-3 space-y-2">
          <span className="text-xs font-semibold text-foreground">AI 服务</span>
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Gemini（搜索增强）" state={connectionStatus.gemini} busy={testingService === 'gemini'} onTest={() => testIntegration('gemini')} />
            <SettingsField onValueChange={updateModelField} label="API Key" value={models.gemini_api_key || ''} field="gemini_api_key" type="password" placeholder="从 Google AI Studio 获取" />
            <SettingsField onValueChange={updateModelField} label="Base URL" value={models.gemini_base_url || ''} field="gemini_base_url" placeholder="https://generativelanguage.googleapis.com/v1beta/openai（留空默认）" />
            <p className="text-2xs text-muted-foreground">用于文献搜索时的 Google Search grounding</p>
          </div>
          <Separator />
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="GPT Image（图片生成）" state={connectionStatus.gpt_image} busy={testingService === 'gpt_image'} onTest={() => testIntegration('gpt_image')} />
            <SettingsField onValueChange={updateModelField} label="API Key" value={models.gpt_image_api_key || ''} field="gpt_image_api_key" type="password" placeholder="OpenAI API Key（留空则复用执行器 key）" />
            <SettingsField onValueChange={updateModelField} label="Base URL" value={models.gpt_image_base_url || ''} field="gpt_image_base_url" placeholder="https://api.openai.com/v1（留空默认）" />
          </div>
          <Separator />
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Exa（语义检索）" state={connectionStatus.exa} busy={testingService === 'exa'} onTest={() => testIntegration('exa')} />
            <SettingsField onValueChange={updateModelField} label="API Key" value={models.exa_api_key || ''} field="exa_api_key" type="password" placeholder="从 exa.ai 获取" />
          </div>
          <Separator />
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="专利先前技术检索" state={connectionStatus.patent} busy={testingService === 'patent'} onTest={() => testIntegration('patent')} />
            <SettingsField onValueChange={updateModelField} label="SerpAPI Key" value={models.serpapi_api_key || ''} field="serpapi_api_key" type="password" placeholder="Google Patents（与 EPO 二选一）" />
            <SettingsField onValueChange={updateModelField} label="EPO OPS Key" value={models.epo_ops_key || ''} field="epo_ops_key" type="password" placeholder="Espacenet OPS consumer key" />
            <SettingsField onValueChange={updateModelField} label="EPO OPS Secret" value={models.epo_ops_secret || ''} field="epo_ops_secret" type="password" placeholder="Espacenet OPS consumer secret" />
          </div>
          <Separator />
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Nano Banana（图片生成）" state={connectionStatus.nano_banana} busy={testingService === 'nano_banana'} onTest={() => testIntegration('nano_banana')} />
            <SettingsField onValueChange={updateModelField} label="API Key" value={models.nano_banana_api_key || ''} field="nano_banana_api_key" type="password" placeholder="Google AI API Key" />
          </div>
        </CardContent>
      </Card>

      {/* 文献 & 笔记 */}
      <Card className="border-border bg-card">
        <CardContent className="p-3 space-y-2">
          <span className="text-xs font-semibold text-foreground">知识库</span>
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Zotero（文献库）" state={connectionStatus.zotero} busy={testingService === 'zotero'} onTest={() => testIntegration('zotero')} />
            <SettingsField onValueChange={updateModelField} label="API Key" value={models.zotero_api_key || ''} field="zotero_api_key" type="password" placeholder="从 zotero.org/settings/keys 获取" />
            <SettingsField onValueChange={updateModelField} label="User ID" value={models.zotero_user_id || ''} field="zotero_user_id" placeholder="Zotero 用户 ID（数字）" />
          </div>
          <Separator />
          <div className="space-y-1.5">
            <ConnectionSectionHeader label="Obsidian（笔记库）" state={connectionStatus.obsidian} busy={testingService === 'obsidian'} onTest={() => testIntegration('obsidian')} />
            <SettingsField onValueChange={updateModelField} label="Vault 路径" value={models.obsidian_vault_path || ''} field="obsidian_vault_path" placeholder="如 C:\Users\xxx\Documents\Obsidian\MyVault" />
          </div>
        </CardContent>
      </Card>

      {/* 保存按钮 */}
      <Button
        onClick={onSave}
        disabled={saving}
        className="w-full bg-primary text-primary-foreground text-xs hover:bg-primary/90 disabled:opacity-50"
      >
        {saving ? 'Saving...' : '保存集成配置'}
      </Button>

      <Separator />

      {/* Overleaf */}
      <Card className="border-border bg-card">
        <CardContent className="space-y-2 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-foreground">Overleaf 同步</span>
            <Badge variant="outline" className={cn(
              'text-[10px]',
              selectedOverleaf?.verified
                ? 'border-green-500/30 bg-green-500/10 text-green-500'
                : 'border-border text-muted-foreground',
            )}>
              {selectedOverleaf?.verified ? '已验证' : selectedOverleaf ? '待测试' : '未关联'}
            </Badge>
          </div>
          <Input placeholder="Overleaf Project ID" value={overleafId} onChange={event => setOverleafId(event.target.value)} className="h-8 bg-muted border-border text-xs" />
          <Input placeholder="Git commit email（可选）" value={overleafEmail} onChange={event => setOverleafEmail(event.target.value)} className="h-8 bg-muted border-border text-xs" />
          <Input
            placeholder={selectedOverleaf?.credentials_available ? 'Token 已加密保存；输入新值可重新关联' : 'Overleaf Token'}
            type="password"
            value={overleafToken}
            onChange={event => setOverleafToken(event.target.value)}
            className="h-8 bg-muted border-border text-xs"
          />
          {selectedOverleaf && (
            <div className="rounded-md border border-border bg-muted/40 px-2 py-1.5 font-mono text-[10px] text-muted-foreground">
              <div className="truncate" title={selectedOverleaf.local_path}>{selectedOverleaf.local_path}</div>
              <div>{selectedOverleaf.branch}{selectedOverleaf.last_sync ? ' · ' + new Date(selectedOverleaf.last_sync).toLocaleString() : ''}</div>
              <div>Main: {selectedOverleaf.main_document || 'paper/main.tex'}</div>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={linkOverleaf} disabled={Boolean(overleafBusy)} className="text-2xs">
              {overleafBusy === 'link' && <Loader2 size={12} className="mr-1 animate-spin" />}关联并测试
            </Button>
            <Button size="sm" variant="secondary" onClick={testOverleaf} disabled={!selectedOverleaf || Boolean(overleafBusy)} className="text-2xs">
              {overleafBusy === 'test' && <Loader2 size={12} className="mr-1 animate-spin" />}测试连接
            </Button>
            <Button size="sm" variant="secondary" onClick={syncOverleaf} disabled={!selectedOverleaf || Boolean(overleafBusy)} className="text-2xs">
              {overleafBusy === 'sync' && <Loader2 size={12} className="mr-1 animate-spin" />}立即同步
            </Button>
          </div>
          {overleafStatus && (
            <div className={cn(
              'flex items-start gap-1.5 rounded-md border px-2 py-1.5 text-2xs',
              overleafStatus.ok
                ? 'border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400'
                : 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400',
            )}>
              {overleafStatus.ok ? <CheckCircle2 size={12} className="mt-0.5 shrink-0" /> : <CircleAlert size={12} className="mt-0.5 shrink-0" />}
              <span className="break-words">{overleafStatus.message}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Separator />

      {/* 通知 */}
      <Card className="border-border bg-card">
        <CardContent className="space-y-3 p-3">
          <span className="text-xs font-semibold text-foreground">通知</span>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="notify-feishu" className="text-xs">飞书</Label>
                <Badge variant="outline" className="text-[10px]">{notifyVerification.feishu?.verified ? '已验证' : notifyConfigured.feishu ? '待测试' : '未配置'}</Badge>
              </div>
              <Switch id="notify-feishu" checked={notifyVerification.feishu?.verified ? notifyEnabled.feishu : false} disabled={!notifyVerification.feishu?.verified} onCheckedChange={value => setNotifyEnabled(current => ({ ...current, feishu: value }))} />
            </div>
            <Input
              placeholder={notifyConfigured.feishu ? 'Webhook 已保存；留空保留' : 'Feishu Webhook URL'}
              type="password"
              value={feishuWebhook}
              onChange={event => {
                setFeishuWebhook(event.target.value)
                invalidateNotification('feishu')
              }}
              className="h-8 bg-muted border-border text-xs"
            />
            <Button size="sm" variant="secondary" disabled={(!notifyConfigured.feishu && !feishuWebhook.trim()) || testingService.startsWith('notify-')} onClick={() => testNotification('feishu')} className="text-2xs">
              {testingService === 'notify-feishu' ? <Loader2 size={12} className="mr-1 animate-spin" /> : <PlugZap size={12} className="mr-1" />}测试飞书
            </Button>
          </div>
          <Separator />
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="notify-slack" className="text-xs">Slack</Label>
                <Badge variant="outline" className="text-[10px]">{notifyVerification.slack?.verified ? '已验证' : notifyConfigured.slack ? '待测试' : '未配置'}</Badge>
              </div>
              <Switch id="notify-slack" checked={notifyVerification.slack?.verified ? notifyEnabled.slack : false} disabled={!notifyVerification.slack?.verified} onCheckedChange={value => setNotifyEnabled(current => ({ ...current, slack: value }))} />
            </div>
            <Input
              placeholder={notifyConfigured.slack ? 'Webhook 已保存；留空保留' : 'Slack Webhook URL'}
              type="password"
              value={slackWebhook}
              onChange={event => {
                setSlackWebhook(event.target.value)
                invalidateNotification('slack')
              }}
              className="h-8 bg-muted border-border text-xs"
            />
            <Button size="sm" variant="secondary" disabled={(!notifyConfigured.slack && !slackWebhook.trim()) || testingService.startsWith('notify-')} onClick={() => testNotification('slack')} className="text-2xs">
              {testingService === 'notify-slack' ? <Loader2 size={12} className="mr-1 animate-spin" /> : <PlugZap size={12} className="mr-1" />}测试 Slack
            </Button>
          </div>
          <Separator />
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="notify-email" className="text-xs">Email</Label>
                <Badge variant="outline" className="text-[10px]">{notifyVerification.email?.verified ? '已验证' : notifyConfigured.email ? '待测试' : '未配置'}</Badge>
              </div>
              <Switch
                id="notify-email"
                checked={notifyVerification.email?.verified ? notifyEnabled.email : false}
                disabled={!notifyVerification.email?.verified}
                onCheckedChange={value => setNotifyEnabled(current => ({ ...current, email: value }))}
              />
            </div>
            <div className="grid grid-cols-[1fr_72px] gap-2">
              <Input placeholder="SMTP Host" value={emailHost} onChange={event => { setEmailHost(event.target.value); invalidateNotification('email') }} className="h-8 bg-muted border-border text-xs" />
              <Input placeholder="Port" inputMode="numeric" value={emailPort} onChange={event => { setEmailPort(event.target.value); invalidateNotification('email') }} className="h-8 bg-muted border-border text-xs" />
            </div>
            <Input placeholder="Sender email" value={emailSender} onChange={event => { setEmailSender(event.target.value); invalidateNotification('email') }} className="h-8 bg-muted border-border text-xs" />
            <Input placeholder={notifyConfigured.email ? 'SMTP 密码已保存；留空保留' : 'SMTP password'} type="password" value={emailPassword} onChange={event => { setEmailPassword(event.target.value); invalidateNotification('email') }} className="h-8 bg-muted border-border text-xs" />
            <Input placeholder="Recipients, comma separated" value={emailRecipients} onChange={event => { setEmailRecipients(event.target.value); invalidateNotification('email') }} className="h-8 bg-muted border-border text-xs" />
            <Button size="sm" variant="secondary" disabled={(!notifyConfigured.email && !(emailHost && emailSender && emailPassword && emailRecipients)) || testingService.startsWith('notify-')} onClick={() => testNotification('email')} className="text-2xs">
              {testingService === 'notify-email' ? <Loader2 size={12} className="mr-1 animate-spin" /> : <PlugZap size={12} className="mr-1" />}测试邮件
            </Button>
          </div>
          <Button size="sm" onClick={saveNotifications} disabled={testingService.startsWith('notify-')} className="w-full text-2xs">保存通知配置</Button>
          {notifyStatus && (
            <div className={cn(
              'flex items-start gap-1.5 rounded-md border px-2 py-1.5 text-2xs',
              notifyStatus.ok
                ? 'border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400'
                : 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400',
            )}>
              {notifyStatus.ok ? <CheckCircle2 size={12} className="mt-0.5 shrink-0" /> : <CircleAlert size={12} className="mt-0.5 shrink-0" />}
              <span className="break-words">{notifyStatus.message}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Separator />

      {/* Meta-Optimize */}
      <div className="space-y-2">
        <Label className="text-xs text-muted-foreground font-semibold">自进化优化</Label>
        <MetaOptimizePanel />
      </div>
    </>
  )
}
