import { useState, useEffect } from 'react'
import { ShieldCheck } from 'lucide-react'
import { API_BASE } from '../../config'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { verificationLabel } from '@/lib/connection-status'
import { SettingsField, type ProviderConnectionState, type IndependentReviewerState, ConnectionStateBadge, ConnectionTestButton } from './settingsFields'
import { IntegrationsTab } from './IntegrationsTab'
import { SshConfigSection } from './integrationTools'

export function SettingsPanel() {
  const [models, setModels] = useState({
    // OpenAI-compatible chat/review model
    openai_api_key: '', openai_base_url: '', openai_model: 'gpt-4o', openai_transport: 'stream',
    anthropic_api_key: '', anthropic_base_url: '', anthropic_model: '',
    deepseek_api_key: '', deepseek_base_url: '', deepseek_model: 'deepseek-chat',
    glm_api_key: '', glm_base_url: '', glm_model: 'glm-4-plus',
    qwen_api_key: '', qwen_base_url: '', qwen_model: 'qwen-max',
    gemini_api_key: '', gemini_base_url: '', gemini_model: 'gemini-2.0-flash',
    // GPU 云服务
    vastai_api_key: '',
    modal_token_id: '',
    modal_token_secret: '',
    // 集成服务
    gpt_image_api_key: '',
    gpt_image_base_url: '',
    nano_banana_api_key: '',
    exa_api_key: '',
    serpapi_api_key: '',
    epo_ops_key: '',
    epo_ops_secret: '',
    zotero_api_key: '',
    zotero_user_id: '',
    obsidian_vault_path: '',
  })
  const [saving, setSaving] = useState(false)
  const [strategy, setStrategy] = useState<{executor: string, reviewer: string}>({ executor: 'openai-api', reviewer: 'openai-api' })
  const [availableProviders, setAvailableProviders] = useState<string[]>([])
  const [providerModels, setProviderModels] = useState<Record<string, string>>({})
  const [providerContexts, setProviderContexts] = useState<Record<string, number>>({})
  const [selectableProviders, setSelectableProviders] = useState<string[]>([])
  const [providerStatus, setProviderStatus] = useState<Record<string, ProviderConnectionState>>({})
  const [independentReviewer, setIndependentReviewer] = useState<IndependentReviewerState>({})
  const [testingProvider, setTestingProvider] = useState('')
  const [testResult, setTestResult] = useState<{provider: string, ok: boolean, msg: string} | null>(null)

  useEffect(() => {
    if (!testResult) return
    const timer = setTimeout(() => setTestResult(null), 8000)
    return () => clearTimeout(timer)
  }, [testResult])

  const [editorFontSize, setEditorFontSize] = useState(() => Number(localStorage.getItem('merak-ide:editorFontSize') || '14'))
  const [chatFontSize, setChatFontSize] = useState(() => Number(localStorage.getItem('merak-ide:chatFontSize') || '13'))
  const [theme, setTheme] = useState(() => localStorage.getItem('merak-ide:theme') || 'dark')

  const applyProviderData = (data: any) => {
    if (data.strategy) setStrategy(data.strategy)
    if (data.available_providers) setAvailableProviders(data.available_providers)
    if (data.selectable_providers) setSelectableProviders(data.selectable_providers)
    if (data.provider_models) setProviderModels(data.provider_models)
    if (data.provider_contexts) setProviderContexts(data.provider_contexts)
    if (data.provider_status) setProviderStatus(data.provider_status)
    if (data.independent_reviewer) setIndependentReviewer(data.independent_reviewer)
  }

  const refreshProviderState = async () => {
    const response = await fetch(`${API_BASE}/api/settings/models/strategy`)
    if (!response.ok) throw new Error(`Model strategy request failed (${response.status})`)
    const data = await response.json()
    applyProviderData(data)
    return data
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/settings/models`).then(r => r.json()).then(data => {
      setModels(prev => ({ ...prev, ...data }))
    }).catch(() => {})
    refreshProviderState().catch(() => {})
  }, [])

  const persistModels = async () => {
    const response = await fetch(`${API_BASE}/api/settings/models`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(models),
    })
    if (!response.ok) throw new Error(`保存失败（HTTP ${response.status}）`)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await persistModels()
      await refreshProviderState()
      window.dispatchEvent(new Event('merak-ide:connection-status-changed'))
      setTestResult({ provider: '', ok: true, msg: '配置已保存；发生变更的连接需要重新测试' })
    } catch (error) {
      setTestResult({ provider: '', ok: false, msg: error instanceof Error ? error.message : '保存失败' })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async (provider: string) => {
    setTestingProvider(provider)
    setTestResult(null)
    try {
      await persistModels()
      const response = await fetch(`${API_BASE}/api/settings/models/test?provider=${provider}`, { method: 'POST' })
      const data = await response.json()
      await refreshProviderState()
      window.dispatchEvent(new Event('merak-ide:connection-status-changed'))
      setTestResult({ provider, ok: data.success === true, msg: data.success ? `连接成功：${data.model || data.response || provider}` : (data.error || '连接测试失败') })
    } catch (error) {
      setTestResult({ provider, ok: false, msg: error instanceof Error ? error.message : '连接失败' })
    } finally {
      setTestingProvider('')
    }
  }

  const handleStrategyChange = async (role: 'executor' | 'reviewer', provider: string) => {
    const response = await fetch(`${API_BASE}/api/settings/models/strategy`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [role]: provider }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      setTestResult({ provider, ok: false, msg: data.detail || '该模型尚未通过连接测试' })
      await refreshProviderState().catch(() => {})
      return
    }
    setStrategy(prev => ({ ...prev, [role]: provider }))
  }

  const handleIndependentReviewerTest = async () => {
    setTestingProvider('independent-reviewer')
    setTestResult(null)
    try {
      const response = await fetch(`${API_BASE}/api/settings/models/reviewer/test`, { method: 'POST' })
      const data = await response.json()
      await refreshProviderState()
      setTestResult({
        provider: data.status?.provider || independentReviewer.provider || 'reviewer-api',
        ok: data.success === true,
        msg: data.success ? (data.message || `连接成功：${data.model || '独立审查 API'}`) : (data.error || '连接测试失败'),
      })
    } catch (error) {
      setTestResult({
        provider: independentReviewer.provider || 'reviewer-api',
        ok: false,
        msg: error instanceof Error ? error.message : '连接失败',
      })
    } finally {
      setTestingProvider('')
    }
  }
  const saveGeneralSetting = (key: string, value: string) => {
    localStorage.setItem(`merak-ide:${key}`, value)
    window.dispatchEvent(new CustomEvent('merak-ide:settings-changed', { detail: { key, value } }))
  }

  const updateModelField = (field: string, value: string) => {
    setModels((prev: any) => ({ ...prev, [field]: value }))
    const prefix = field.split('_')[0]
    const providerName = prefix === 'openai'
      ? 'openai-api'
      : prefix === 'anthropic'
        ? 'claude-api'
        : ['deepseek', 'glm', 'qwen', 'gemini'].includes(prefix)
          ? prefix
          : ''
    if (providerName) {
      setProviderStatus(prev => prev[providerName]
        ? { ...prev, [providerName]: { ...prev[providerName], verified: false, tested: false, stale: true } }
        : prev)
      setSelectableProviders(prev => prev.filter(name => name !== providerName))
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-border">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">设置</h3>
      </div>

      <Tabs defaultValue="models" className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 pt-2">
          <TabsList className="h-7 bg-muted">
            <TabsTrigger value="models" className="text-2xs px-2 py-0.5 data-[state=active]:bg-accent data-[state=active]:text-foreground">模型</TabsTrigger>
            <TabsTrigger value="general" className="text-2xs px-2 py-0.5 data-[state=active]:bg-accent data-[state=active]:text-foreground">通用</TabsTrigger>
            <TabsTrigger value="integrations" className="text-2xs px-2 py-0.5 data-[state=active]:bg-accent data-[state=active]:text-foreground">集成</TabsTrigger>
          </TabsList>
        </div>

        {/* 检测/测试结果提示（固定顶部，不随滚动） */}
        {testResult && (
          <div className={cn('mx-3 mt-2 px-3 py-2 rounded text-xs shrink-0', testResult.ok ? 'bg-green-500/10 text-green-500 border border-green-500/30' : 'bg-red-500/10 text-red-500 border border-red-500/30')}>
            {testResult.provider && <span className="font-medium">[{testResult.provider}] </span>}
            {testResult.msg}
            <button onClick={() => setTestResult(null)} className="ml-2 opacity-60 hover:opacity-100">✕</button>
          </div>
        )}

        <ScrollArea className="flex-1">
          <div className="p-3 space-y-4">
            <TabsContent value="models" className="mt-0 space-y-4">
              {/* OpenAI / ChatGPT API */}
              <Card className="border-border bg-card">
                <CardContent className="p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex min-w-0 items-center gap-2"><span className="truncate text-xs font-semibold text-foreground">OpenAI API</span><ConnectionStateBadge state={providerStatus['openai-api']} configured={availableProviders.includes('openai-api')} /></div>
                    <ConnectionTestButton busy={testingProvider === 'openai'} onClick={() => handleTest('openai')} />
                  </div>
                  <div className="space-y-1.5">
                    <SettingsField onValueChange={updateModelField} label="API Key" value={models.openai_api_key} field="openai_api_key" type="password" placeholder="sk-..." />
                    <SettingsField onValueChange={updateModelField} label="Base URL" value={models.openai_base_url} field="openai_base_url" placeholder="https://api.openai.com/v1（兼容代理填此处）" />
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">模型</Label>
                      <Input value={models.openai_model || ''} onChange={e => updateModelField('openai_model', e.target.value)} placeholder="gpt-4o" className="h-7 text-xs font-mono" />
                    </div>
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">响应方式</Label>
                      <Select value={models.openai_transport || 'stream'} onValueChange={value => updateModelField('openai_transport', value)}>
                        <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="stream">流式：逐步显示响应</SelectItem>
                          <SelectItem value="non_stream">非流式：等待完整响应</SelectItem>
                        </SelectContent>
                      </Select>
                      <p className="text-2xs text-muted-foreground">代理频繁中断流时可选非流式；仍使用当前模型与相同超时预算。</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
              {/* Claude API */}
              <Card className="border-border bg-card">
                <CardContent className="p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex min-w-0 items-center gap-2"><span className="truncate text-xs font-semibold text-foreground">Claude API</span><ConnectionStateBadge state={providerStatus['claude-api']} configured={availableProviders.includes('claude-api')} /></div>
                    <ConnectionTestButton busy={testingProvider === 'anthropic'} onClick={() => handleTest('anthropic')} />
                  </div>
                  <div className="space-y-1.5">
                    <SettingsField onValueChange={updateModelField} label="API Key" value={models.anthropic_api_key} field="anthropic_api_key" type="password" placeholder="sk-ant-..." />
                    <SettingsField onValueChange={updateModelField} label="Base URL" value={models.anthropic_base_url} field="anthropic_base_url" placeholder="https://api.anthropic.com（留空默认）" />
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">模型</Label>
                      <Input value={models.anthropic_model || ''} onChange={e => updateModelField('anthropic_model', e.target.value)} placeholder="claude-sonnet-4-6" className="h-7 text-xs font-mono" />
                    </div>
                  </div>
                </CardContent>
              </Card>
              {/* Other models (collapsible) */}
              <details className="group">
                <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">其他模型（可选）</summary>
                <div className="mt-2 space-y-3">
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2"><div className="flex min-w-0 items-center gap-2"><span className="text-xs font-medium text-foreground">DeepSeek</span><ConnectionStateBadge state={providerStatus.deepseek} configured={availableProviders.includes('deepseek')} /></div><ConnectionTestButton busy={testingProvider === 'deepseek'} onClick={() => handleTest('deepseek')} /></div>
                    <SettingsField onValueChange={updateModelField} label="API Key" value={models.deepseek_api_key} field="deepseek_api_key" type="password" placeholder="sk-..." />
                    <SettingsField onValueChange={updateModelField} label="Base URL" value={models.deepseek_base_url} field="deepseek_base_url" placeholder="https://api.deepseek.com/v1" />
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">Model</Label>
                      <Input
                        value={models.deepseek_model || ''}
                        onChange={e => updateModelField('deepseek_model', e.target.value)}
                        placeholder="deepseek-chat / deepseek-reasoner / custom-model"
                        list="deepseek-model-options"
                        className="h-7 text-xs font-mono"
                      />
                      <datalist id="deepseek-model-options">
                        <option value="deepseek-chat" />
                        <option value="deepseek-coder" />
                        <option value="deepseek-reasoner" />
                      </datalist>
                    </div>
                  </div>
                  <Separator />
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2"><div className="flex min-w-0 items-center gap-2"><span className="text-xs font-medium text-foreground">GLM（智谱）</span><ConnectionStateBadge state={providerStatus.glm} configured={availableProviders.includes('glm')} /></div><ConnectionTestButton busy={testingProvider === 'glm'} onClick={() => handleTest('glm')} /></div>
                    <SettingsField onValueChange={updateModelField} label="API Key" value={models.glm_api_key} field="glm_api_key" type="password" />
                    <SettingsField onValueChange={updateModelField} label="Base URL" value={models.glm_base_url} field="glm_base_url" placeholder="https://open.bigmodel.cn/api/paas/v4" />
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">Model</Label>
                      <Input
                        value={models.glm_model || ''}
                        onChange={e => updateModelField('glm_model', e.target.value)}
                        placeholder="glm-4-plus / glm-4-flash / custom-model"
                        list="glm-model-options"
                        className="h-7 text-xs font-mono"
                      />
                      <datalist id="glm-model-options">
                        <option value="glm-4-plus" />
                        <option value="glm-4" />
                        <option value="glm-4-flash" />
                      </datalist>
                    </div>
                  </div>
                  <Separator />
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2"><div className="flex min-w-0 items-center gap-2"><span className="text-xs font-medium text-foreground">Qwen（通义）</span><ConnectionStateBadge state={providerStatus.qwen} configured={availableProviders.includes('qwen')} /></div><ConnectionTestButton busy={testingProvider === 'qwen'} onClick={() => handleTest('qwen')} /></div>
                    <SettingsField onValueChange={updateModelField} label="API Key" value={models.qwen_api_key} field="qwen_api_key" type="password" />
                    <SettingsField onValueChange={updateModelField} label="Base URL" value={models.qwen_base_url} field="qwen_base_url" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">Model</Label>
                      <Input
                        value={models.qwen_model || ''}
                        onChange={e => updateModelField('qwen_model', e.target.value)}
                        placeholder="qwen-max / qwen-plus / custom-model"
                        list="qwen-model-options"
                        className="h-7 text-xs font-mono"
                      />
                      <datalist id="qwen-model-options">
                        <option value="qwen-max" />
                        <option value="qwen-plus" />
                        <option value="qwen-turbo" />
                        <option value="qwen-coder-plus" />
                      </datalist>
                    </div>
                  </div>
                  <Separator />
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-2"><div className="flex min-w-0 items-center gap-2"><span className="text-xs font-medium text-foreground">Gemini</span><ConnectionStateBadge state={providerStatus.gemini} configured={availableProviders.includes('gemini')} /></div><ConnectionTestButton busy={testingProvider === 'gemini'} onClick={() => handleTest('gemini')} /></div>
                    <SettingsField onValueChange={updateModelField} label="API Key" value={models.gemini_api_key} field="gemini_api_key" type="password" />
                    <SettingsField onValueChange={updateModelField} label="Base URL" value={models.gemini_base_url} field="gemini_base_url" placeholder="https://generativelanguage.googleapis.com/v1beta/openai" />
                    <div>
                      <Label className="text-2xs text-muted-foreground mb-0.5">Model</Label>
                      <Input
                        value={models.gemini_model || ''}
                        onChange={e => updateModelField('gemini_model', e.target.value)}
                        placeholder="gemini-2.0-flash / gemini-2.5-pro / custom-model"
                        list="gemini-model-options"
                        className="h-7 text-xs font-mono"
                      />
                      <datalist id="gemini-model-options">
                        <option value="gemini-2.0-flash" />
                        <option value="gemini-2.5-pro" />
                        <option value="gemini-2.5-flash" />
                      </datalist>
                    </div>
                  </div>
                </div>
              </details>

              {/* Model Strategy */}
              <Card className="border-border bg-card">
                <CardContent className="space-y-3 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                        <ShieldCheck size={14} />
                        模型策略
                      </div>
                      <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
                        只有当前配置通过连接测试的模型才能承担执行或审查任务。
                      </p>
                    </div>
                    <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px] font-normal">
                      {selectableProviders.length}/{availableProviders.length} 可用
                    </Badge>
                  </div>

                  {availableProviders.length === 0 && (
                    <p className="rounded-md border border-dashed border-border bg-muted/30 px-2.5 py-2 text-2xs text-muted-foreground">
                      暂无已配置模型。模型策略仍保留在此处，保存至少一个 Provider 后即可测试。
                    </p>
                  )}
                  {availableProviders.length > 0 && selectableProviders.length === 0 && (
                    <p className="rounded-md border border-yellow-500/30 bg-yellow-500/10 px-2.5 py-2 text-2xs text-yellow-600 dark:text-yellow-400">
                      已填写模型配置，但尚无模型通过连接测试。
                    </p>
                  )}

                  <div className="space-y-2.5">
                    {(['executor', 'reviewer'] as const).map(role => (
                      <div key={role} className="space-y-1">
                        <div className="flex items-center justify-between gap-2">
                          <Label className="text-2xs font-medium text-foreground">
                            {role === 'executor' ? 'Executor · 执行模型' : 'Reviewer · 审查模型'}
                          </Label>
                          <span className="text-[10px] text-muted-foreground">
                            {role === 'executor' ? '工具调用与产物生成' : '独立审查与风险检查'}
                          </span>
                        </div>
                        <Select
                          value={selectableProviders.includes(strategy[role]) ? strategy[role] : undefined}
                          disabled={selectableProviders.length === 0}
                          onValueChange={value => handleStrategyChange(role, value)}
                        >
                          <SelectTrigger className="h-10 bg-background border-border px-2.5 text-xs text-foreground">
                            <SelectValue placeholder={availableProviders.length === 0 ? '未配置模型' : '请先测试连接'} />
                          </SelectTrigger>
                          <SelectContent className="min-w-[260px]">
                            {availableProviders.map(provider => {
                              const verified = selectableProviders.includes(provider)
                              return (
                                <SelectItem key={provider} value={provider} disabled={!verified} className="py-2">
                                  <span className="flex min-w-0 items-center gap-2">
                                    <span className={cn('h-2 w-2 shrink-0 rounded-full', verified ? 'bg-green-500' : 'bg-muted-foreground/40')} />
                                    <span className="flex min-w-0 flex-col">
                                      <span className="truncate font-medium">{provider}</span>
                                      <span className="truncate text-[10px] text-muted-foreground">
                                        {providerModels[provider] || '未指定模型'} · {providerContexts[provider] ? String(providerContexts[provider] / 1_000_000) + 'M context · ' : ''}{verified ? '已验证' : verificationLabel(providerStatus[provider], true)}
                                      </span>
                                    </span>
                                  </span>
                                </SelectItem>
                              )
                            })}
                          </SelectContent>
                        </Select>
                      </div>
                    ))}
                  </div>

                  <Separator />
                  <div className="space-y-2 rounded-md border border-border bg-muted/20 p-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="truncate text-xs font-medium text-foreground">
                            审稿 API 模型
                          </span>
                          <Badge
                            variant="outline"
                            className={cn(
                              'h-5 shrink-0 px-1.5 text-[10px] font-normal',
                              independentReviewer.session_isolated ?? independentReviewer.isolated
                                ? 'border-green-500/30 bg-green-500/10 text-green-500'
                                : 'border-yellow-500/30 bg-yellow-500/10 text-yellow-500',
                            )}
                          >
                            {(independentReviewer.session_isolated ?? independentReviewer.isolated) ? '独立会话' : '未就绪'}
                          </Badge>
                          <ConnectionStateBadge
                            state={independentReviewer}
                            configured={independentReviewer.configured === true}
                          />
                        </div>
                        <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
                          Reviewer 可与 Executor 使用同一模型；每轮均创建新的冷启动、无工具、只读会话，执行论文评审、科学审计与 proof-checker。
                        </p>
                      </div>
                      <ConnectionTestButton
                        busy={testingProvider === 'independent-reviewer'}
                        disabled={independentReviewer.configured !== true}
                        onClick={handleIndependentReviewerTest}
                      />
                    </div>
                    <div className="truncate rounded bg-background px-2 py-1.5 font-mono text-[10px] text-muted-foreground">
                      {independentReviewer.configured
                        ? `${independentReviewer.provider || 'reviewer-api'} · ${independentReviewer.model || '模型身份待确认'}`
                        : '尚未配置可用的审查模型 API'}
                    </div>
                    {independentReviewer.configured && independentReviewer.same_model && (
                      <p className="text-[10px] leading-4 text-green-600 dark:text-green-400">
                        当前与 Executor 使用同一模型；审稿仍通过不共享执行上下文的独立冷启动会话完成。
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
              <Button
                onClick={handleSave}
                disabled={saving}
                className="w-full bg-primary text-primary-foreground text-xs hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? 'Saving...' : '保存配置'}
              </Button>

            </TabsContent>

            <TabsContent value="general" className="mt-0 space-y-4">
              {/* Theme */}
              <div>
                <Label className="text-xs text-muted-foreground mb-1.5">Theme</Label>
                <Select
                  value={theme}
                  onValueChange={(val) => { setTheme(val); saveGeneralSetting('theme', val) }}
                >
                  <SelectTrigger className="h-8 bg-muted border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="dark">Dark (Catppuccin Mocha)</SelectItem>
                    <SelectItem value="light">Light</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Editor Font Size */}
              <div>
                <Label className="text-xs text-muted-foreground mb-1.5">Editor Font Size: {editorFontSize}px</Label>
                <input
                  type="range"
                  min={10}
                  max={24}
                  value={editorFontSize}
                  onChange={e => { const v = Number(e.target.value); setEditorFontSize(v); saveGeneralSetting('editorFontSize', String(v)) }}
                  className="w-full accent-foreground"
                />
                <div className="flex justify-between text-2xs text-muted-foreground">
                  <span>10</span><span>24</span>
                </div>
              </div>

              {/* Chat Font Size */}
              <div>
                <Label className="text-xs text-muted-foreground mb-1.5">Chat Font Size: {chatFontSize}px</Label>
                <input
                  type="range"
                  min={10}
                  max={22}
                  value={chatFontSize}
                  onChange={e => { const v = Number(e.target.value); setChatFontSize(v); saveGeneralSetting('chatFontSize', String(v)) }}
                  className="w-full accent-foreground"
                />
                <div className="flex justify-between text-2xs text-muted-foreground">
                  <span>10</span><span>22</span>
                </div>
              </div>

              {/* Keyboard Shortcuts */}
              <Card className="border-border bg-card">
                <CardContent className="p-2">
                  <span className="text-2xs text-muted-foreground block mb-1">Keyboard Shortcuts</span>
                  <div className="space-y-0.5 text-2xs text-muted-foreground font-mono">
                    <div className="flex justify-between"><span>Command Palette</span><span>Ctrl+Shift+P</span></div>
                    <div className="flex justify-between"><span>Toggle Sidebar</span><span>Ctrl+B</span></div>
                    <div className="flex justify-between"><span>Save File</span><span>Ctrl+S</span></div>
                  </div>
                </CardContent>
              </Card>

              {/* SSH Servers */}
              <Separator />
              <div>
                <Label className="text-xs text-muted-foreground mb-2">SSH 服务器（远程实验）</Label>
                <SshConfigSection />
              </div>

              <Separator />
              <div>
                <p className="text-xs text-muted-foreground">Merak v0.1.2</p>
                <p className="text-2xs text-muted-foreground mt-1">Copyright © 2026 NorthS Team</p>
                <p className="text-2xs text-muted-foreground mt-1">Research workflows, experiments and scientific writing</p>
              </div>
            </TabsContent>

            <TabsContent value="integrations" className="mt-0 space-y-4">
              <IntegrationsTab models={models} setModels={setModels} onSave={handleSave} saving={saving} />
            </TabsContent>
          </div>
        </ScrollArea>
      </Tabs>
    </div>
  )
}
