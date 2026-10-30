import { ChatPanelView } from './ChatPanelView'
import { appliedRevisionStatus } from './chatRevisionStatus'
import { useState, useRef, useEffect, useCallback } from 'react'
import { useWorkspaceStore } from '../../stores/workspace'
import { API_BASE } from '../../config'
import { type AgentStep, type ChangeProposal, type ChatMessage, type AttachedFile, type ChatConversation, type ChatHistoryState, type RuntimeModelState, type ResearchContext, type ChatMode } from './chatTypes'
import { chatRoleForMode, getChatModeConfig, CHAT_INPUT_MIN_HEIGHT, CHAT_INPUT_MAX_HEIGHT, CHAT_RUN_INACTIVITY_TIMEOUT_MS, shortLabel } from './chatModes'
import { MAX_CHAT_CONVERSATIONS, createChatConversation, createChatHistoryForProject, scopeChatHistoryToProject, titleFromMessages, loadChatHistory, saveChatHistory, normalizeAttachedFiles, normalizeChangeProposals, expirePendingProposals, updateProposalStatus, buildConversationContextPayload, loadProjectChatHistory, saveProjectChatHistory } from './chatHistory'
import { makeBackendContextKey, normalizePathKey, isResearchArtifactPath, getComposerSuggestions, getAttachableGroups, inferPromptMode, formatAgentStatus, formatChatError, refreshOpenFileFromDisk } from './chatArtifacts'

export function ChatPanel() {
  const initialChatHistoryRef = useRef<ChatHistoryState | null>(null)
  if (!initialChatHistoryRef.current) initialChatHistoryRef.current = createChatHistoryForProject()
  const initialConversation = initialChatHistoryRef.current.conversations.find(c => c.id === initialChatHistoryRef.current?.activeConversationId)
    ?? initialChatHistoryRef.current.conversations[0]

  const [chatHistory, setChatHistory] = useState<ChatHistoryState>(initialChatHistoryRef.current)
  const [messages, setMessages] = useState<ChatMessage[]>(initialConversation?.messages ?? [])
  const [input, setInput] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [currentStatus, setCurrentStatus] = useState('')
  const [runtimeModel, setRuntimeModel] = useState<RuntimeModelState | null>(null)
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>(initialConversation?.attachedFiles ?? [])
  const [researchCtx, setResearchCtx] = useState<ResearchContext | null>(null)
  const [ctxExpanded, setCtxExpanded] = useState(false)
  const [showFileMenu, setShowFileMenu] = useState(false)
  const [showSessionMenu, setShowSessionMenu] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState(initialConversation?.provider ?? '')           // '' = default
  const [availableProviders, setAvailableProviders] = useState<string[]>([])
  const [providerModels, setProviderModels] = useState<Record<string, string>>({})
  const [modelStrategy, setModelStrategy] = useState<Record<string, string>>({})

  const [mode, setMode] = useState<ChatMode>(initialConversation?.mode ?? 'ask')
  const [activeBackendSessionId, setActiveBackendSessionId] = useState(initialConversation?.backendSessionId ?? '')

  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const runningTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const historySaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const loadedHistoryProjectRef = useRef<string | null>(null)
  const historyHydratingRef = useRef(false)
  const chatHistoryRef = useRef(chatHistory)

  const projectPath = useWorkspaceStore(s => s.projectPath)
  const openFiles = useWorkspaceStore(s => s.openFiles)
  const activeFileIndex = useWorkspaceStore(s => s.activeFileIndex)
  const activeFile = activeFileIndex >= 0 ? openFiles[activeFileIndex] : null
  const activeArtifactFile = activeFile && isResearchArtifactPath(activeFile.path, projectPath) ? activeFile : null
  const attachmentGroups = getAttachableGroups(openFiles, attachedFiles, activeArtifactFile, projectPath)
  const attachableFileCount = attachmentGroups.reduce((total, group) => total + group.files.length, 0)
  const modeConfig = getChatModeConfig(mode)
  const activeConversationId = chatHistory.activeConversationId
  const activeConversation = chatHistory.conversations.find(c => c.id === activeConversationId) ?? chatHistory.conversations[0]
  const sortedConversations = [...chatHistory.conversations].sort((a, b) => b.updatedAt - a.updatedAt)
  const autoProvider = modelStrategy.executor || modelStrategy.general || availableProviders[0] || ''
  const autoProviderModel = autoProvider ? providerModels[autoProvider] : ''
  const runtimeProviderLabel = runtimeModel?.provider ? `Auto · ${shortLabel(runtimeModel.provider)}` : ''
  const runtimeProviderModel = runtimeModel?.model || (runtimeModel?.provider ? providerModels[runtimeModel.provider] : '')
  const autoProviderLabel = runtimeProviderLabel || (autoProvider ? `Auto · ${shortLabel(autoProvider)}` : 'Auto')
  const selectedProviderModel = selectedProvider ? providerModels[selectedProvider] : ''
  const modelSelectorPrimary = selectedProvider
    ? shortLabel(selectedProvider)
    : autoProvider
      ? autoProviderLabel
      : '未配置模型'
  const modelSelectorSecondary = selectedProvider
    ? selectedProviderModel
    : (runtimeProviderModel || autoProviderModel || '请在设置中配置并测试连接')
  const currentBackendContextKey = makeBackendContextKey(projectPath, mode, activeArtifactFile?.path)
  const activeConversationIdRef = useRef(activeConversationId)
  const activeConversationRef = useRef<ChatConversation | undefined>(activeConversation)
  const activeBackendSessionIdRef = useRef(activeBackendSessionId)
  const activeRequestIdRef = useRef('')
  const modeRef = useRef(mode)
  const selectedProviderRef = useRef(selectedProvider)
  const currentContextKeyRef = useRef(currentBackendContextKey)
  const lastModeRef = useRef(mode)
  const lastArtifactPathRef = useRef(normalizePathKey(activeArtifactFile?.path))

  const clearRunInactivityTimer = useCallback(() => {
    if (runningTimerRef.current) {
      clearTimeout(runningTimerRef.current)
      runningTimerRef.current = null
    }
  }, [])

  const armRunInactivityTimer = useCallback(() => {
    const requestId = activeRequestIdRef.current
    if (!requestId) return
    clearRunInactivityTimer()
    runningTimerRef.current = setTimeout(() => {
      if (requestId !== activeRequestIdRef.current) return
      runningTimerRef.current = null
      activeRequestIdRef.current = ''
      wsRef.current?.send(JSON.stringify({ type: 'cancel', session_id: activeBackendSessionIdRef.current }))
      setIsRunning(false)
      setCurrentStatus('Timeout')
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(), role: 'assistant',
        content: '响应超时：45 秒内没有收到模型或工具的新事件。\n\n本次后端任务已取消，已有输出已保留。可以直接重试、切换模型，或把问题拆短后再发送。',
        timestamp: Date.now(),
      }])
    }, CHAT_RUN_INACTIVITY_TIMEOUT_MS)
  }, [clearRunInactivityTimer])

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId
    activeConversationRef.current = activeConversation
  }, [activeConversationId, activeConversation])

  useEffect(() => {
    activeBackendSessionIdRef.current = activeBackendSessionId
  }, [activeBackendSessionId])

  useEffect(() => {
    modeRef.current = mode
    selectedProviderRef.current = selectedProvider
    currentContextKeyRef.current = currentBackendContextKey
  }, [currentBackendContextKey, mode, selectedProvider])

  useEffect(() => {
    const element = inputRef.current
    if (!element) return
    element.style.height = 'auto'
    const viewportLimit = Math.max(140, Math.floor(window.innerHeight * 0.4))
    const maxHeight = Math.min(CHAT_INPUT_MAX_HEIGHT, viewportLimit)
    const nextHeight = Math.min(element.scrollHeight, maxHeight)
    element.style.height = `${Math.max(nextHeight, CHAT_INPUT_MIN_HEIGHT)}px`
    element.style.overflowY = element.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [input])

  useEffect(() => {
    chatHistoryRef.current = chatHistory
    if (historyHydratingRef.current) return
    if (loadedHistoryProjectRef.current !== projectPath) return
    saveChatHistory(chatHistory, projectPath)

    if (!projectPath) return
    if (historySaveTimerRef.current) clearTimeout(historySaveTimerRef.current)
    historySaveTimerRef.current = setTimeout(() => {
      saveProjectChatHistory(projectPath, chatHistory).catch(() => {
        setCurrentStatus('History local only')
      })
    }, 500)
  }, [chatHistory, projectPath])

  useEffect(() => {
    if (historyHydratingRef.current) return
    setChatHistory(prev => ({
      ...prev,
      conversations: prev.conversations.map(conv => conv.id === activeConversationId
        ? {
            ...conv,
            messages,
            attachedFiles,
            mode,
            provider: selectedProvider,
            backendSessionId: activeBackendSessionId,
            backendContextKey: currentBackendContextKey,
            projectPath: projectPath || conv.projectPath,
            title: titleFromMessages(messages),
            updatedAt: Date.now(),
          }
        : conv),
    }))
  }, [activeConversationId, activeBackendSessionId, attachedFiles, messages, mode, projectPath, selectedProvider, currentBackendContextKey])

  const buildContextFiles = useCallback((_targetMode: ChatMode = mode) => {
    const files = new Map<string, AttachedFile>()
    if (activeArtifactFile) {
      files.set(normalizePathKey(activeArtifactFile.path), {
        path: activeArtifactFile.path,
        name: activeArtifactFile.name,
        source: 'current',
      })
    }
    for (const file of attachedFiles) {
      const source = file.source || 'explicit'
      if (source !== 'explicit') continue
      if (isResearchArtifactPath(file.path, projectPath)) {
        files.set(normalizePathKey(file.path), { ...file, source: 'explicit' })
      }
    }
    return Array.from(files.values())
  }, [activeArtifactFile, attachedFiles, mode, projectPath])

  const contextFiles = buildContextFiles()

  const resetBackendSession = useCallback((nextMode: ChatMode, contextKey: string) => {
    setActiveBackendSessionId('')
    activeBackendSessionIdRef.current = ''
    setRuntimeModel(null)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'new_session',
        role: chatRoleForMode(nextMode),
        conversation_id: activeConversationIdRef.current,
        project_path: projectPath || activeConversationRef.current?.projectPath || '.',
        provider: selectedProviderRef.current,
        context_key: contextKey,
      }))
    }
  }, [projectPath])

  useEffect(() => {
    const artifactKey = normalizePathKey(activeArtifactFile?.path)
    const modeChanged = lastModeRef.current !== mode
    const artifactChanged = lastArtifactPathRef.current !== artifactKey
    if (!modeChanged && !artifactChanged) return

    lastModeRef.current = mode
    lastArtifactPathRef.current = artifactKey
    if (historyHydratingRef.current) return
    setAttachedFiles(prev => prev.filter(file => (file.source || 'explicit') === 'explicit'))
    resetBackendSession(mode, makeBackendContextKey(projectPath, mode, activeArtifactFile?.path))
  }, [activeArtifactFile?.path, mode, projectPath, resetBackendSession])

  // ── Fetch available providers ─────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_BASE}/api/settings/models/strategy`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return
        const selectable = data.selectable_providers || []
        setAvailableProviders(selectable)
        setSelectedProvider(current => current && !selectable.includes(current) ? '' : current)
        setProviderModels(data.provider_models || {})
        setModelStrategy(data.strategy || {})
      })
      .catch(() => {})
  }, [])

  // ── WebSocket connection ──────────────────────────────────────────────────
  useEffect(() => {
    const wsUrl = API_BASE.replace('http', 'ws') + '/api/chat/ws'
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      const conversation = activeConversationRef.current
      if (conversation?.backendSessionId) {
        ws.send(JSON.stringify({
          type: 'select_session',
          session_id: conversation.backendSessionId,
          conversation_id: conversation.id,
          project_path: projectPath || conversation.projectPath || '.',
          provider: conversation.provider || selectedProviderRef.current,
          role: chatRoleForMode(conversation.mode || modeRef.current),
          context_key: currentContextKeyRef.current,
        }))
        return
      }
      ws.send(JSON.stringify({
        type: 'create_session',
        role: chatRoleForMode(conversation?.mode || modeRef.current),
        conversation_id: conversation?.id || activeConversationIdRef.current,
        project_path: projectPath || conversation?.projectPath || '.',
        provider: selectedProviderRef.current,
        context_key: currentContextKeyRef.current,
      }))
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      handleWsEvent(msg)
    }

    ws.onclose = () => setCurrentStatus('Disconnected')

    return () => ws.close()
  }, [])

  // ── Research context ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!projectPath) {
      setResearchCtx(null)
      setCtxExpanded(false)
      return
    }

    let cancelled = false
    setResearchCtx(null)
    fetch(`${API_BASE}/api/chat/context?project_path=${encodeURIComponent(projectPath)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!cancelled && data) setResearchCtx(data)
      })
      .catch(() => {})

    return () => {
      cancelled = true
    }
  }, [projectPath])

  // ── Project chat history ─────────────────────────────────────────────────
  useEffect(() => {
    if (historySaveTimerRef.current) {
      clearTimeout(historySaveTimerRef.current)
      historySaveTimerRef.current = null
    }
    clearRunInactivityTimer()

    const sessionToCancel = activeBackendSessionIdRef.current
    activeRequestIdRef.current = ''
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'cancel', session_id: sessionToCancel }))
    }

    const fallbackHistory = loadChatHistory(projectPath)
    const fallbackConversation = fallbackHistory.conversations[0]
    historyHydratingRef.current = true
    loadedHistoryProjectRef.current = null
    activeConversationIdRef.current = fallbackHistory.activeConversationId
    activeConversationRef.current = fallbackConversation
    activeBackendSessionIdRef.current = ''
    chatHistoryRef.current = fallbackHistory
    lastModeRef.current = 'ask'
    lastArtifactPathRef.current = ''

    setChatHistory(fallbackHistory)
    setMessages([])
    setInput('')
    setIsRunning(false)
    setRuntimeModel(null)
    setAttachedFiles([])
    setShowFileMenu(false)
    setShowSessionMenu(false)
    setMode('ask')
    setSelectedProvider('')
    setActiveBackendSessionId('')

    if (!projectPath) {
      historyHydratingRef.current = false
      setCurrentStatus('Ready')
      return
    }

    let cancelled = false
    setCurrentStatus('Loading history...')

    const applyHistory = (history: ChatHistoryState, status: string) => {
      const active = history.conversations.find(c => c.id === history.activeConversationId)
        ?? history.conversations[0]
      activeConversationIdRef.current = history.activeConversationId
      activeConversationRef.current = active
      activeBackendSessionIdRef.current = active?.backendSessionId || ''
      chatHistoryRef.current = history
      loadedHistoryProjectRef.current = projectPath

      setChatHistory(history)
      setMessages(active?.messages ?? [])
      setAttachedFiles(normalizeAttachedFiles(active?.attachedFiles))
      setMode(active?.mode ?? 'ask')
      setSelectedProvider(active?.provider ?? '')
      setActiveBackendSessionId(active?.backendSessionId ?? '')
      historyHydratingRef.current = false
      setCurrentStatus(status)

      if (wsRef.current?.readyState === WebSocket.OPEN && active?.backendSessionId) {
        wsRef.current.send(JSON.stringify({
          type: 'select_session',
          session_id: active.backendSessionId,
          conversation_id: active.id,
          project_path: projectPath,
          provider: active.provider || selectedProviderRef.current,
          role: chatRoleForMode(active.mode || 'ask'),
          context_key: makeBackendContextKey(projectPath, active.mode || 'ask', activeArtifactFile?.path),
        }))
      }
    }

    loadProjectChatHistory(projectPath)
      .then(remoteHistory => {
        if (cancelled) return
        applyHistory(scopeChatHistoryToProject(remoteHistory, projectPath) ?? fallbackHistory, 'Ready')
      })
      .catch(() => {
        if (cancelled) return
        applyHistory(loadChatHistory(projectPath), 'History local only')
      })

    return () => {
      cancelled = true
    }
  }, [projectPath])
  // ── Chat inject (from editor right-click) ─────────────────────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent<{ text: string }>).detail?.text
      if (!text) return
      setInput(text)
      setTimeout(() => {
        inputRef.current?.focus()
        const len = text.length
        inputRef.current?.setSelectionRange(len, len)
      }, 50)
    }
    window.addEventListener('merak-ide:chat-inject', handler)
    return () => window.removeEventListener('merak-ide:chat-inject', handler)
  }, [])

  // ── Scroll to bottom ──────────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── WS event handler ──────────────────────────────────────────────────────
  const handleWsEvent = useCallback((msg: { type: string; data: unknown; request_id?: string; conversation_id?: string }) => {
    if (msg.conversation_id && msg.conversation_id !== activeConversationIdRef.current) return
    if (msg.request_id && (!activeRequestIdRef.current || msg.request_id !== activeRequestIdRef.current)) return
    if (msg.request_id && msg.type.startsWith('agent_') && msg.type !== 'agent_done' && msg.type !== 'agent_error') {
      armRunInactivityTimer()
    }
    switch (msg.type) {
      case 'session_created':
      case 'session_selected':
        {
          const data = msg as { session_id?: string; conversation_id?: string; context_key?: string; recovered?: boolean; requested_session_id?: string }
          const conversationId = data.conversation_id || activeConversationIdRef.current
          const staleSessionId = data.recovered === false ? data.requested_session_id || '' : ''
          if (conversationId === activeConversationIdRef.current && staleSessionId) {
            setMessages(prev => expirePendingProposals(prev, staleSessionId))
          }
          if (conversationId === activeConversationIdRef.current && data.session_id) {
            setActiveBackendSessionId(data.session_id)
          }
          if (data.session_id) {
            setChatHistory(prev => ({
              ...prev,
              conversations: prev.conversations.map(conv => {
                if (conv.id !== conversationId) return conv
                const messages = staleSessionId ? expirePendingProposals(conv.messages || [], staleSessionId) : conv.messages
                return { ...conv, messages, backendSessionId: data.session_id, backendContextKey: data.context_key || conv.backendContextKey, updatedAt: Date.now() }
              }),
            }))
          }
        }
        setCurrentStatus('Ready')
        break
      case 'agent_status':
        {
          const data = msg.data as { provider?: string; model?: string; to?: string }
          if (data.provider || data.to) setRuntimeModel({ provider: data.provider || data.to || '', model: data.model || '' })
          setCurrentStatus(formatAgentStatus(msg.data))
        }
        break
      case 'agent_step':
        setMessages(prev => {
          const data = msg.data as AgentStep
          const step = { kind: data.kind, title: data.title || '处理步骤', detail: data.detail }
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant')
            return [...prev.slice(0, -1), { ...last, steps: [...(last.steps || []), step] }]
          return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: '', steps: [step], timestamp: Date.now() }]
        })
        break
      case 'agent_change_proposal':
        setMessages(prev => {
          const data = msg.data as ChangeProposal
          const proposal = normalizeChangeProposals([{
            ...data,
            sessionId: data.sessionId || activeBackendSessionIdRef.current,
            status: data.status || 'pending',
          }])[0]
          if (!proposal) return prev
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant')
            return [...prev.slice(0, -1), { ...last, changeProposals: [...(last.changeProposals || []), proposal] }]
          return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: '', changeProposals: [proposal], timestamp: Date.now() }]
        })
        break
      case 'agent_text':
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant')
            return [...prev.slice(0, -1), { ...last, content: last.content + (msg.data as string) }]
          return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: msg.data as string, timestamp: Date.now() }]
        })
        break
      case 'agent_tool_call':
        setMessages(prev => {
          const data = msg.data as { name: string; args: Record<string, unknown> }
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant')
            return [...prev.slice(0, -1), { ...last, toolCalls: [...(last.toolCalls || []), data] }]
          return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: '', toolCalls: [data], timestamp: Date.now() }]
        })
        break
      case 'agent_tool_result':
        setMessages(prev => {
          const data = msg.data as { name: string; success: boolean; output: string }
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant')
            return [...prev.slice(0, -1), { ...last, toolResults: [...(last.toolResults || []), data] }]
          return prev
        })
        {
          const toolName = (msg.data as { name?: string })?.name
          if (toolName === 'Write' || toolName === 'Edit')
            window.dispatchEvent(new Event('merak-ide:files-changed'))
        }
        break
      case 'agent_done':
        clearRunInactivityTimer()
        activeRequestIdRef.current = ''
        setIsRunning(false)
        setCurrentStatus('Ready')
        break
      case 'agent_error':
      case 'edit_error':
        clearRunInactivityTimer()
        activeRequestIdRef.current = ''
        setIsRunning(false)
        setCurrentStatus('Error')
        setMessages(prev => {
          const content = `错误：${formatChatError(msg.data)}`
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant' && last.content === content) return prev
          return [...prev, { id: crypto.randomUUID(), role: 'assistant', content, timestamp: Date.now() }]
        })
        break
      case 'file_attached':
        setCurrentStatus('Ready')
        break
      case 'provider_set':
        setCurrentStatus('Ready')
        break
      case 'change_applied':
      case 'change_rejected':
        {
          const data = msg.data as ChangeProposal
          setCurrentStatus(msg.type === 'change_applied' ? 'Change applied' : 'Change rejected')
          setMessages(prev => prev.map(message => ({
            ...message,
            changeProposals: message.changeProposals?.map(proposal => proposal.id === data.id ? { ...proposal, ...data } : proposal),
          })))
          if (msg.type === 'change_applied') {
            setCurrentStatus(appliedRevisionStatus(data.impact))
            if (data.impact?.affected_runs?.length) {
              window.dispatchEvent(new CustomEvent('merak-ide:research-changed', { detail: data.impact }))
            }
            refreshOpenFileFromDisk(data.path).catch(() => setCurrentStatus('Change applied; editor refresh failed'))
            window.dispatchEvent(new Event('merak-ide:files-changed'))
          }
        }
        break
      case 'agent_research_changed':
        setCurrentStatus(appliedRevisionStatus(msg.data as ChangeProposal['impact']))
        window.dispatchEvent(new Event('merak-ide:files-changed'))
        if ((msg.data as ChangeProposal['impact'])?.affected_runs?.length) window.dispatchEvent(new CustomEvent('merak-ide:research-changed', { detail: msg.data }))
        break
      case 'change_error':
        {
          const data = msg.data as { id?: string; error?: string }
          const error = data.error || '未知错误'
          const lower = error.toLowerCase()
          const nextStatus: ChangeProposal['status'] | null = lower.includes('not found') ? 'expired' : lower.includes('outside research artifacts') ? 'blocked' : null
          setCurrentStatus('Change error')
          if (data.id && nextStatus) {
            setMessages(prev => updateProposalStatus(prev, data.id || '', nextStatus))
          }
          setMessages(prev => [...prev, {
            id: crypto.randomUUID(), role: 'assistant',
            content: `错误：变更审批失败：${error}`, timestamp: Date.now(),
          }])
        }
        break
      case 'attach_error':
        setCurrentStatus('Ready')
        setMessages(prev => [...prev, {
          id: crypto.randomUUID(), role: 'assistant',
          content: `错误：${(msg as { error?: string }).error || '无法附加该文件'}`, timestamp: Date.now(),
        }])
        break
    }
  }, [armRunInactivityTimer, clearRunInactivityTimer])

  // ── Actions ───────────────────────────────────────────────────────────────
  const selectConversation = (conversation: ChatConversation) => {
    if (isRunning) return
    setChatHistory(prev => ({ ...prev, activeConversationId: conversation.id }))
    setMessages(conversation.messages || [])
    setAttachedFiles(conversation.attachedFiles || [])
    setMode(conversation.mode || 'ask')
    setSelectedProvider(conversation.provider || '')
    setActiveBackendSessionId(conversation.backendSessionId || '')
    setShowSessionMenu(false)
    setCurrentStatus('Ready')

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'select_session',
        session_id: conversation.backendSessionId || '',
        conversation_id: conversation.id,
        project_path: projectPath || conversation.projectPath || '.',
        provider: conversation.provider || selectedProviderRef.current,
        role: chatRoleForMode(conversation.mode || 'ask'),
        context_key: makeBackendContextKey(projectPath || conversation.projectPath || '.', conversation.mode || 'ask', activeArtifactFile?.path),
      }))
    }
  }

  const startNewSession = (providerOverride?: string) => {
    const provider = providerOverride ?? selectedProvider
    const conversation = createChatConversation(projectPath, provider, 'ask')
    setChatHistory(prev => ({
      activeConversationId: conversation.id,
      conversations: [conversation, ...prev.conversations].slice(0, MAX_CHAT_CONVERSATIONS),
    }))
    setMessages([])
    setAttachedFiles([])
    setMode('ask')
    setActiveBackendSessionId('')
    setShowSessionMenu(false)
    setCurrentStatus('Starting...')
    setRuntimeModel(null)

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'new_session',
        role: chatRoleForMode('ask'),
        conversation_id: conversation.id,
        project_path: projectPath || '.',
        provider,
        context_key: makeBackendContextKey(projectPath, 'ask', activeArtifactFile?.path),
      }))
    }
    if (projectPath) {
      fetch(`${API_BASE}/api/chat/context?project_path=${encodeURIComponent(projectPath)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) setResearchCtx(data) })
        .catch(() => {})
    }
  }

  const changeProvider = (providerName: string) => {
    setSelectedProvider(providerName)
    if (wsRef.current) {
      wsRef.current.send(JSON.stringify({ type: 'set_provider', provider: providerName }))
    }
    setCurrentStatus(providerName ? `使用 ${shortLabel(providerName)}` : autoProviderLabel)
  }

  const attachFile = (file: { path: string; name: string }) => {
    if (!isResearchArtifactPath(file.path, projectPath)) {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(), role: 'assistant',
        content: '错误：Chat 只能附加 paper、slides、experiments、figures、literature、ideas 中的研究产物文件。',
        timestamp: Date.now(),
      }])
      return
    }
    if (attachedFiles.some(f => normalizePathKey(f.path) === normalizePathKey(file.path))) return
    setAttachedFiles(prev => [...prev, { ...file, source: 'explicit' }])
    setShowFileMenu(false)
  }

  const detachFile = (path: string) => {
    const pathKey = normalizePathKey(path)
    setAttachedFiles(prev => prev.filter(f => normalizePathKey(f.path) !== pathKey))
  }

  const resolveChange = (proposal: ChangeProposal, approved: boolean) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setCurrentStatus('连接已断开，请刷新页面')
      return
    }
    const proposalSessionId = proposal.sessionId || activeBackendSessionIdRef.current
    if (!proposalSessionId) {
      setCurrentStatus('Change expired')
      setMessages(prev => updateProposalStatus(prev, proposal.id, 'expired'))
      return
    }
    setCurrentStatus(approved ? 'Applying change...' : 'Rejecting change...')
    wsRef.current.send(JSON.stringify({
      type: 'resolve_change',
      change_id: proposal.id,
      approved,
      session_id: proposalSessionId,
      conversation_id: activeConversationIdRef.current,
    }))
  }

  const sendMessage = (overrideInput?: string, overrideMode?: ChatMode) => {
    const text = (overrideInput ?? input).trim()
    if (!text || !wsRef.current || isRunning) return
    if (availableProviders.length === 0) {
      setCurrentStatus('请先在设置中配置模型并通过连接测试')
      return
    }
    if (historyHydratingRef.current) {
      setCurrentStatus('Loading history...')
      return
    }

    // WS 已断开时不发送，避免 send() 抛异常后 isRunning 永久卡死
    if (wsRef.current.readyState !== WebSocket.OPEN) {
      setCurrentStatus('连接已断开，请刷新页面')
      return
    }

    const messageMode = overrideMode ?? (mode === 'ask' ? inferPromptMode(text, mode) : mode)
    const contextKey = makeBackendContextKey(projectPath || activeConversation?.projectPath || '.', messageMode, activeArtifactFile?.path)
    const requestId = crypto.randomUUID()
    activeRequestIdRef.current = requestId

    if (!overrideMode && messageMode !== mode) setMode(messageMode)
    setMessages(prev => [...prev, {
      id: crypto.randomUUID(), role: 'user',
      content: text, timestamp: Date.now(),
    }])
    setIsRunning(true)
    setCurrentStatus('Thinking...')

    if (activeBackendSessionIdRef.current && activeConversation?.backendContextKey !== contextKey) {
      setActiveBackendSessionId('')
      activeBackendSessionIdRef.current = ''
    }
    if (!activeBackendSessionIdRef.current) {
      wsRef.current.send(JSON.stringify({
        type: 'new_session',
        role: chatRoleForMode(messageMode),
        conversation_id: activeConversationIdRef.current,
        project_path: projectPath || activeConversation?.projectPath || '.',
        provider: selectedProviderRef.current,
        context_key: contextKey,
      }))
    }

    // 使用无活动超时：只在长时间没有任何模型/工具事件时取消，流式输出中会自动续期。
    armRunInactivityTimer()

    wsRef.current.send(JSON.stringify({
      type: 'message',
      content: text,
      mode: messageMode,
      role: chatRoleForMode(messageMode),
      request_id: requestId,
      context_key: contextKey,
      conversation_id: activeConversationIdRef.current,
      project_path: projectPath || activeConversation?.projectPath || '.',
      context_files: buildContextFiles(messageMode),
      conversation_messages: buildConversationContextPayload(messages),
    }))
    if (!overrideInput) setInput('')
    inputRef.current?.focus()
  }

  const handleCancel = () => {
    clearRunInactivityTimer()
    activeRequestIdRef.current = ''
    wsRef.current?.send(JSON.stringify({ type: 'cancel', session_id: activeBackendSessionIdRef.current }))
    setIsRunning(false)
    setCurrentStatus('Cancelled')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }
  const composerSuggestions = getComposerSuggestions(mode, activeArtifactFile?.path, projectPath)
  const inferredMode = input.trim() && mode === 'ask' ? inferPromptMode(input, mode) : mode

  const retryLastMessage = () => {
    const lastUserMessage = [...messages].reverse().find(m => m.role === 'user' && m.content.trim())
    if (lastUserMessage) sendMessage(lastUserMessage.content, mode)
  }
  // ── Render ────────────────────────────────────────────────────────────────
  return <ChatPanelView model={{
    messages, input, setInput,
    isRunning, currentStatus, attachedFiles,
    researchCtx, ctxExpanded, setCtxExpanded,
    showFileMenu, setShowFileMenu, showSessionMenu,
    setShowSessionMenu, selectedProvider, availableProviders,
    providerModels, mode, setMode,
    messagesEndRef, inputRef, projectPath,
    activeFile, activeArtifactFile, attachmentGroups,
    attachableFileCount, modeConfig, activeConversationId,
    activeConversation, sortedConversations, autoProvider,
    autoProviderModel, modelSelectorPrimary, modelSelectorSecondary,
    contextFiles, selectConversation, startNewSession,
    changeProvider, attachFile, detachFile,
    resolveChange, sendMessage, handleCancel,
    handleKeyDown, composerSuggestions, inferredMode,
    retryLastMessage,
  }} />
}
