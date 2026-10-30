import React from 'react'
import { PlugZap, Loader2, CheckCircle2, CircleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { type IntegrationState, type VerificationState, verificationLabel } from '@/lib/connection-status'

export type SettingsFieldProps = {
  label: string
  value?: string
  field: string
  type?: React.HTMLInputTypeAttribute
  placeholder?: string
  onValueChange: (field: string, value: string) => void
}

export function SettingsField({ label, value, field, type = 'text', placeholder = '', onValueChange }: SettingsFieldProps) {
  const displayValue = value ?? ''
  const isMaskedSecret = type === 'password' && displayValue.includes('****')

  return (
    <div>
      <Label className="text-2xs text-muted-foreground mb-0.5">{label}</Label>
      <Input
        type={type}
        value={displayValue}
        onFocus={e => { if (isMaskedSecret) e.currentTarget.select() }}
        onChange={e => onValueChange(field, e.target.value)}
        placeholder={isMaskedSecret ? '已配置，直接输入新值可覆盖' : placeholder}
        className="h-7 px-2 py-1 bg-background border-border text-xs text-foreground placeholder:text-muted-foreground focus-visible:ring-ring font-mono"
      />
    </div>
  )
}

export type ProviderConnectionState = VerificationState & {
  configured?: boolean
  model?: string
}

export type IndependentReviewerState = Partial<VerificationState> & {
  configured?: boolean
  provider?: string
  model?: string
  executor_provider?: string
  executor_model?: string
  isolated?: boolean
  session_isolated?: boolean
  same_model_allowed?: boolean
  same_model?: boolean
  ready?: boolean
}

export function ConnectionStateBadge({ state, configured = true }: {
  state?: Partial<VerificationState>
  configured?: boolean
}) {
  const label = state ? verificationLabel(state, configured) : (configured ? '检查中' : '未配置')
  const verified = state?.verified === true
  const needsAttention = configured && !!state && !verified
  return (
    <Badge
      variant="outline"
      className={cn(
        'h-5 shrink-0 px-1.5 text-[10px] font-normal',
        verified && 'border-green-500/30 bg-green-500/10 text-green-500',
        needsAttention && 'border-yellow-500/30 bg-yellow-500/10 text-yellow-500',
        (!state || !configured) && 'border-border bg-muted text-muted-foreground',
      )}
    >
      {verified ? <CheckCircle2 size={11} /> : needsAttention ? <CircleAlert size={11} /> : null}
      <span className="ml-1">{label}</span>
    </Badge>
  )
}

export function ConnectionTestButton({ busy, disabled, onClick }: {
  busy?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      disabled={disabled || busy}
      onClick={onClick}
      className="h-7 shrink-0 gap-1.5 px-2 text-2xs"
    >
      {busy ? <Loader2 size={12} className="animate-spin" /> : <PlugZap size={12} />}
      {busy ? '测试中' : '测试连接'}
    </Button>
  )
}

export function ConnectionSectionHeader({ label, state, busy, onTest }: {
  label: string
  state?: IntegrationState
  busy?: boolean
  onTest: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-2xs font-medium text-foreground">{label}</span>
        <ConnectionStateBadge state={state} configured={state?.configured ?? false} />
      </div>
      <ConnectionTestButton busy={busy} onClick={onTest} />
    </div>
  )
}
