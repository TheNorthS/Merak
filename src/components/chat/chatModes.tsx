import { Sparkles, FileText, Search, Image, BookOpen } from 'lucide-react'
import { type ChatMode, type ChatBackendRole, type ChatModeConfig } from './chatTypes'

export function chatRoleForMode(mode: ChatMode): ChatBackendRole {
  if (mode === 'review') return 'reviewer'
  if (mode === 'figure') return 'figure'
  if (mode === 'ask') return 'general'
  return 'executor'
}

export const CHAT_MODES: ChatModeConfig[] = [
  { id: 'ask', label: 'Ask', title: '解释、检索和讨论，不修改文件', placeholder: '询问论文、实验、文献或图表问题...', icon: Search },
  { id: 'edit', label: 'Edit', title: '精确修改当前研究产物文件', placeholder: '描述要如何修改当前研究产物...', icon: FileText },
  { id: 'review', label: 'Review', title: '审稿、代码审查和一致性检查', placeholder: '检查贡献、引用、实验或代码风险...', icon: BookOpen },
  { id: 'write', label: 'Write', title: '起草论文、实验说明、slides 或研究笔记', placeholder: '起草或续写科研内容...', icon: Sparkles },
  { id: 'figure', label: 'Figure', title: '生成或改进科研图表', placeholder: '描述要生成或修改的图表...', icon: Image },
]

export function getChatModeConfig(mode: ChatMode) {
  return CHAT_MODES.find(m => m.id === mode) ?? CHAT_MODES[1]
}

export const CHAT_INPUT_MIN_HEIGHT = 42

export const CHAT_INPUT_MAX_HEIGHT = 320

export const CHAT_RUN_INACTIVITY_TIMEOUT_MS = 45000

export const PROVIDER_LABELS: Record<string, string> = {
  'openai-api': 'GPT',
  'claude-api': 'Claude',
  'deepseek': 'DeepSeek',
  'glm': 'GLM',
  'qwen': 'Qwen',
  'gemini': 'Gemini',
}

export function shortLabel(provider: string) {
  return PROVIDER_LABELS[provider] ?? provider
}
