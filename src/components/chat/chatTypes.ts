import type { OpenFile } from '../../stores/workspace'

import { Sparkles } from 'lucide-react'

export interface AgentStep {
  kind?: string
  title: string
  detail?: string
}

export interface ChangeProposal {
  id: string
  action: string
  path: string
  diff: string
  status: 'pending' | 'applied' | 'rejected' | 'blocked' | 'expired'
  sessionId?: string
  beforeLength?: number
  afterLength?: number
  impact?: { affected_phases?: string[]; affected_runs?: string[]; completed_runs?: string[]; revision_mode?: string }
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  steps?: AgentStep[]
  toolCalls?: Array<{ name: string; args: Record<string, unknown> }>
  toolResults?: Array<{ name: string; success: boolean; output: string }>
  changeProposals?: ChangeProposal[]
  timestamp: number
  imageUrl?: string
}

export interface AttachedFile {
  path: string
  name: string
  source?: 'explicit' | 'current'
}

export interface ChatConversation {
  id: string
  backendSessionId?: string
  backendContextKey?: string
  title: string
  messages: ChatMessage[]
  attachedFiles: AttachedFile[]
  mode: ChatMode
  provider: string
  projectPath: string
  createdAt: number
  updatedAt: number
}

export interface ChatHistoryState {
  activeConversationId: string
  conversations: ChatConversation[]
}

export interface RuntimeModelState {
  provider: string
  model: string
}

export interface ResearchContext {
  research_direction: string
  workflow_history: Array<{ status: string; nodes: string[] }>
  artifacts: Array<{ type: string; count: number; dir: string }>
  recent_entries: Array<{ key: string; content: string }>
}

export type ChatMode = 'ask' | 'edit' | 'review' | 'write' | 'figure'

export type ChatSuggestion = { label: string; prompt: string; mode: ChatMode }

export type ChatBackendRole = 'executor' | 'reviewer' | 'general' | 'figure'

export interface ChatModeConfig {
  id: ChatMode
  label: string
  title: string
  placeholder: string
  icon: typeof Sparkles
}

export type SuggestionContextKind = 'project' | 'paper' | 'slides' | 'code' | 'figure'

export interface AttachmentMenuFile extends AttachedFile {
  dir: string
  isCurrent: boolean
  isAttached: boolean
  isDirty: boolean
}

export interface AttachmentGroup {
  dir: string
  label: string
  files: AttachmentMenuFile[]
}

export interface ChatPanelViewModel {
  messages: ChatMessage[]
  input: string
  setInput: React.Dispatch<React.SetStateAction<string>>
  isRunning: boolean
  currentStatus: string
  attachedFiles: AttachedFile[]
  researchCtx: ResearchContext | null
  ctxExpanded: boolean
  setCtxExpanded: React.Dispatch<React.SetStateAction<boolean>>
  showFileMenu: boolean
  setShowFileMenu: React.Dispatch<React.SetStateAction<boolean>>
  showSessionMenu: boolean
  setShowSessionMenu: React.Dispatch<React.SetStateAction<boolean>>
  selectedProvider: string
  availableProviders: string[]
  providerModels: Record<string, string>
  mode: ChatMode
  setMode: React.Dispatch<React.SetStateAction<ChatMode>>
  messagesEndRef: React.RefObject<HTMLDivElement>
  inputRef: React.RefObject<HTMLTextAreaElement>
  projectPath: string | null
  activeFile: OpenFile | null
  activeArtifactFile: OpenFile | null
  attachmentGroups: AttachmentGroup[]
  attachableFileCount: number
  modeConfig: ChatModeConfig
  activeConversationId: string
  activeConversation: ChatConversation
  sortedConversations: ChatConversation[]
  autoProvider: string
  autoProviderModel: string
  modelSelectorPrimary: string
  modelSelectorSecondary: string
  contextFiles: AttachedFile[]
  selectConversation: (conversation: ChatConversation) => void
  startNewSession: (providerOverride?: string) => void
  changeProvider: (providerName: string) => void
  attachFile: (file: { path: string; name: string; }) => void
  detachFile: (path: string) => void
  resolveChange: (proposal: ChangeProposal, approved: boolean) => void
  sendMessage: (overrideInput?: string, overrideMode?: ChatMode) => void
  handleCancel: () => void
  handleKeyDown: (e: React.KeyboardEvent) => void
  composerSuggestions: ChatSuggestion[]
  inferredMode: ChatMode
  retryLastMessage: () => void
}
