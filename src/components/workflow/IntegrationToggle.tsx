import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import {
  type IntegrationState,
  verificationLabel,
} from '@/lib/connection-status'


interface IntegrationToggleProps {
  id: string
  label: string
  checked: boolean
  onChange: (value: boolean) => void
  status?: IntegrationState
}

export function IntegrationToggle({
  id,
  label,
  checked,
  onChange,
  status,
}: IntegrationToggleProps) {
  const verified = status?.verified === true
  const stateLabel = status ? verificationLabel(status, status.configured) : '检查中'
  const unavailableReason = status?.configured
    ? '当前配置尚未通过连接测试，请先在设置中测试连接'
    : '该集成尚未配置，请先在设置中填写配置并测试连接'
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-1.5">
        <Label htmlFor={id} className={cn('truncate text-xs', !verified && 'text-muted-foreground')}>
          {label}
        </Label>
        <Badge
          variant="outline"
          className={cn(
            'h-5 shrink-0 px-1.5 text-[10px] font-normal',
            verified && 'border-green-500/30 bg-green-500/10 text-green-500',
            !verified && status?.configured && 'border-yellow-500/30 bg-yellow-500/10 text-yellow-500',
            !verified && !status?.configured && 'border-border bg-muted text-muted-foreground',
          )}
        >
          {stateLabel}
        </Badge>
      </div>
      <Switch
        id={id}
        checked={verified && checked}
        disabled={!verified}
        onCheckedChange={onChange}
        title={verified ? '该集成已验证，可用于下一次工作流' : unavailableReason}
      />
    </div>
  )
}
