import { API_BASE } from '../../config'
import { type ChangeProposal, type ChatMessage, type AttachedFile, type ChatConversation, type ChatHistoryState, type ChatMode } from './chatTypes'
import { normalizePathKey } from './chatArtifacts'

export const CHAT_HISTORY_KEY = 'merak-ide:research-chat-history:v1'

export const CHAT_HISTORY_KEY_PREFIX = 'merak-ide:research-chat-history:v2:'

export const MAX_CHAT_CONVERSATIONS = 24

export function createChatConversation(projectPath?: string | null, provider = '', mode: ChatMode = 'ask'): ChatConversation {
  const now = Date.now()
  return {
    id: crypto.randomUUID(),
    title: '新会话',
    messages: [],
    attachedFiles: [],
    mode,
    provider,
    projectPath: projectPath || '',
    createdAt: now,
    updatedAt: now,
  }
}

export function createChatHistoryForProject(projectPath?: string | null, provider = ''): ChatHistoryState {
  const conversation = createChatConversation(projectPath, provider, 'ask')
  return { activeConversationId: conversation.id, conversations: [conversation] }
}

export function isConversationForProject(conversation: ChatConversation, projectPath?: string | null) {
  const expected = normalizePathKey(projectPath)
  const actual = normalizePathKey(conversation.projectPath)
  return expected ? actual === expected : !actual
}

export function scopeChatHistoryToProject(state: ChatHistoryState | null, projectPath?: string | null): ChatHistoryState | null {
  if (!state) return null
  const conversations = state.conversations.filter(conversation => isConversationForProject(conversation, projectPath))
  if (conversations.length === 0) return null
  const activeConversationId = conversations.some(c => c.id === state.activeConversationId)
    ? state.activeConversationId
    : conversations[0].id
  return { activeConversationId, conversations }
}

export function titleFromMessages(messages: ChatMessage[]) {
  const firstUser = messages.find(m => m.role === 'user' && m.content.trim())
  if (!firstUser) return '新会话'
  const firstLine = firstUser.content.trim().split('\n')[0]
  return firstLine.length > 26 ? `${firstLine.slice(0, 26)}...` : firstLine
}

export function chatHistoryStorageKey(projectPath?: string | null) {
  const scope = normalizePathKey(projectPath) || '__no_project__'
  return CHAT_HISTORY_KEY_PREFIX + encodeURIComponent(scope)
}

export function loadChatHistory(projectPath?: string | null): ChatHistoryState {
  try {
    const keys = [chatHistoryStorageKey(projectPath), CHAT_HISTORY_KEY]
    for (const key of keys) {
      const raw = localStorage.getItem(key)
      if (!raw) continue
      const parsed = JSON.parse(raw) as ChatHistoryState
      const normalized = normalizeChatHistoryState(parsed)
      const scoped = scopeChatHistoryToProject(normalized, projectPath)
      if (scoped) return scoped
    }
  } catch {
    // Ignore corrupted local history and start clean.
  }
  return createChatHistoryForProject(projectPath)
}

export function saveChatHistory(state: ChatHistoryState, projectPath?: string | null) {
  try {
    localStorage.setItem(chatHistoryStorageKey(projectPath), JSON.stringify({
      activeConversationId: state.activeConversationId,
      conversations: state.conversations.slice(0, MAX_CHAT_CONVERSATIONS),
    }))
  } catch {
    // localStorage quota failures should not break chat input.
  }
}

export function normalizeAttachedFiles(files: AttachedFile[] | undefined): AttachedFile[] {
  if (!Array.isArray(files)) return []
  return files
    .filter(file => file && typeof file.path === 'string')
    .map(file => ({
      ...file,
      name: file.name || file.path.split(/[\\/]/).pop() || file.path,
      source: file.source || 'explicit',
    }))
}

export function normalizeProposalStatus(status: unknown): ChangeProposal['status'] {
  if (status === 'applied' || status === 'rejected' || status === 'blocked' || status === 'expired') return status
  return 'pending'
}

export function normalizeChangeProposals(proposals: unknown): ChangeProposal[] {
  if (!Array.isArray(proposals)) return []
  return proposals
    .filter(proposal => proposal && typeof proposal === 'object')
    .map(raw => {
      const proposal = raw as Partial<ChangeProposal>
      const sessionId = typeof proposal.sessionId === 'string' ? proposal.sessionId : ''
      const status = normalizeProposalStatus(proposal.status)
      return {
        id: String(proposal.id || ''),
        sessionId,
        action: String(proposal.action || 'edit'),
        path: String(proposal.path || ''),
        diff: String(proposal.diff || ''),
        status: status === 'pending' && !sessionId ? 'expired' : status,
        beforeLength: typeof proposal.beforeLength === 'number' ? proposal.beforeLength : undefined,
        afterLength: typeof proposal.afterLength === 'number' ? proposal.afterLength : undefined,
      }
    })
    .filter(proposal => proposal.id && proposal.path)
}

export function normalizeMessages(messages: unknown): ChatMessage[] {
  if (!Array.isArray(messages)) return []
  return messages
    .filter(message => message && typeof message === 'object')
    .map(raw => {
      const message = raw as Partial<ChatMessage>
      return {
        ...message,
        id: String(message.id || crypto.randomUUID()),
        role: message.role === 'user' ? 'user' : 'assistant',
        content: String(message.content || ''),
        timestamp: typeof message.timestamp === 'number' ? message.timestamp : Date.now(),
        changeProposals: normalizeChangeProposals(message.changeProposals),
      } as ChatMessage
    })
}

export function expirePendingProposals(messages: ChatMessage[], sessionId?: string): ChatMessage[] {
  return messages.map(message => {
    const proposals = message.changeProposals
    if (!proposals?.length) return message
    let changed = false
    const nextProposals = proposals.map(proposal => {
      const matchesSession = !sessionId || !proposal.sessionId || proposal.sessionId === sessionId
      if (proposal.status === 'pending' && matchesSession) {
        changed = true
        return { ...proposal, status: 'expired' as const }
      }
      return proposal
    })
    return changed ? { ...message, changeProposals: nextProposals } : message
  })
}

export function updateProposalStatus(messages: ChatMessage[], changeId: string, status: ChangeProposal['status']): ChatMessage[] {
  return messages.map(message => {
    const proposals = message.changeProposals
    if (!proposals?.length) return message
    let changed = false
    const nextProposals = proposals.map(proposal => {
      if (proposal.id === changeId) {
        changed = true
        return { ...proposal, status }
      }
      return proposal
    })
    return changed ? { ...message, changeProposals: nextProposals } : message
  })
}

export function buildConversationContextPayload(messages: ChatMessage[]) {
  return messages.slice(-18).map(message => ({
    role: message.role,
    content: message.content.slice(0, 8000),
    timestamp: message.timestamp,
    changeProposals: (message.changeProposals || []).slice(0, 8).map(proposal => ({
      path: proposal.path,
      action: proposal.action,
      status: proposal.status,
    })),
  }))
}

export function normalizeChatHistoryState(data: unknown): ChatHistoryState | null {
  const parsed = data as Partial<ChatHistoryState> | null
  if (!parsed || !Array.isArray(parsed.conversations) || parsed.conversations.length === 0) return null
  const conversations = parsed.conversations
    .filter(c => c && typeof c.id === 'string')
    .slice(0, MAX_CHAT_CONVERSATIONS)
    .map(c => ({
      ...c,
      title: c.title || titleFromMessages(c.messages || []),
      messages: normalizeMessages(c.messages),
      attachedFiles: normalizeAttachedFiles(c.attachedFiles),
      mode: c.mode || 'ask',
      provider: c.provider || '',
      projectPath: c.projectPath || '',
      createdAt: c.createdAt || Date.now(),
      updatedAt: c.updatedAt || Date.now(),
    }))
  if (conversations.length === 0) return null
  const activeConversationId = conversations.some(c => c.id === parsed.activeConversationId)
    ? parsed.activeConversationId || conversations[0].id
    : conversations[0].id
  return { activeConversationId, conversations }
}

export async function loadProjectChatHistory(projectPath: string): Promise<ChatHistoryState | null> {
  const res = await fetch(`${API_BASE}/api/chat/history?project_path=${encodeURIComponent(projectPath)}`)
  if (!res.ok) throw new Error(`Load chat history failed: ${res.status}`)
  const history = normalizeChatHistoryState(await res.json())
  if (!history) return null
  return {
    ...history,
    conversations: history.conversations.map(conversation => ({
      ...conversation,
      projectPath,
    })),
  }
}

export async function saveProjectChatHistory(projectPath: string, state: ChatHistoryState) {
  const res = await fetch(`${API_BASE}/api/chat/history`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_path: projectPath,
      activeConversationId: state.activeConversationId,
      conversations: state.conversations.slice(0, MAX_CHAT_CONVERSATIONS),
    }),
  })
  if (!res.ok) throw new Error(`Save chat history failed: ${res.status}`)
}
