import { Send, Square, Sparkles, FileText, Loader2, Plus, RefreshCw, ChevronDown, ChevronRight, X, Wand2, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { getChatModeConfig, shortLabel } from './chatModes'
import { formatArtifactPath, ArtifactIcon } from './chatArtifacts'
import { ModeSelector, EmptyState, MessageBubble } from './chatMessageViews'
import type { ChatPanelViewModel } from './chatTypes'
import { ChatCloseButton } from './ChatCloseButton'

export function ChatPanelView({ model }: { model: ChatPanelViewModel }) {
  const {
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
  } = model
  return (
    <div className="merak-chat-panel h-full min-h-0 w-full min-w-0 max-w-full overflow-hidden flex flex-col bg-background">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="h-10 min-w-0 gap-2 px-4 flex items-center justify-between border-b border-border shrink-0">
        <div className="relative min-w-0 flex-1">
          <button
            type="button"
            onClick={() => setShowSessionMenu(v => !v)}
            className="flex w-full min-w-0 items-center gap-1.5 rounded px-1 py-0.5 text-left hover:bg-muted"
            title="切换会话"
          >
            <Sparkles size={13} className="shrink-0 text-foreground" />
            <span className="min-w-0 truncate text-xs font-semibold text-foreground">
              {activeConversation?.title || 'Copilot'}
            </span>
            <ChevronDown size={11} className="shrink-0 text-muted-foreground" />
          </button>
          {showSessionMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowSessionMenu(false)} />
              <div className="absolute left-0 top-full z-50 mt-1 w-64 overflow-hidden rounded-md border border-border bg-popover shadow-xl">
                <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
                  <span className="text-2xs font-medium text-muted-foreground">会话历史</span>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => startNewSession()}
                    disabled={isRunning}
                    className="h-6 px-1.5 text-2xs"
                  >
                    <Plus size={10} />
                    新建
                  </Button>
                </div>
                <div className="max-h-64 overflow-y-auto py-1">
                  {sortedConversations.map(conversation => (
                    <button
                      key={conversation.id}
                      type="button"
                      onClick={() => selectConversation(conversation)}
                      disabled={isRunning}
                      className={cn(
                        'w-full px-2 py-1.5 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50',
                        conversation.id === activeConversationId ? 'bg-accent/50' : ''
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-2xs font-medium text-foreground">{conversation.title}</span>
                        <span className="shrink-0 text-2xs text-muted-foreground">{getChatModeConfig(conversation.mode).label}</span>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-2xs text-muted-foreground">
                        <span className="truncate">{conversation.messages.length} 条消息</span>
                        <span>{new Date(conversation.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
        <div className="flex min-w-0 max-w-[85%] shrink-0 items-center gap-1">
          {/* Model selector: only providers with a successful current test are listed. */}
          <Select value={selectedProvider || '__auto__'} onValueChange={value => changeProvider(value === '__auto__' ? '' : value)}>
            <SelectTrigger className="h-9 w-36 min-w-0 gap-2 border-border bg-background px-2.5 py-1 text-left shadow-none" title="选择模型">
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="truncate text-[11px] font-medium text-foreground">{modelSelectorPrimary}</span>
                <span className="truncate font-mono text-[9px] text-muted-foreground">{modelSelectorSecondary}</span>
              </span>
            </SelectTrigger>
            <SelectContent className="min-w-[280px]">
              <SelectItem value="__auto__" className="py-2">
                <span className="flex min-w-0 flex-col">
                  <span className="font-medium">Auto · 策略路由</span>
                  <span className="truncate text-[10px] text-muted-foreground">
                    {autoProvider ? `${shortLabel(autoProvider)} · ${autoProviderModel || '自动选择模型'}` : '暂无已验证模型'}
                  </span>
                </span>
              </SelectItem>
              {availableProviders.map(provider => (
                <SelectItem key={provider} value={provider} className="py-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="h-2 w-2 shrink-0 rounded-full bg-green-500" />
                    <span className="flex min-w-0 flex-col">
                      <span className="font-medium">{shortLabel(provider)}</span>
                      <span className="truncate font-mono text-[10px] text-muted-foreground">{providerModels[provider] || provider}</span>
                    </span>
                  </span>
                </SelectItem>
              ))}
              {availableProviders.length === 0 && (
                <SelectItem value="__unavailable__" disabled className="py-2 text-muted-foreground">未配置或尚未通过连接测试</SelectItem>
              )}
            </SelectContent>
          </Select>
          <Badge
            variant="secondary"
            title={currentStatus || 'Ready'}
            className={cn(
              'block max-w-24 shrink truncate text-2xs px-1.5 py-0 font-normal border-transparent',
              isRunning ? 'bg-accent/50 text-foreground' : 'bg-muted text-muted-foreground'
            )}
          >
            {currentStatus || 'Ready'}
          </Badge>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => startNewSession()}
            disabled={isRunning}
            title="新开会话"
            className="text-muted-foreground hover:text-foreground"
          >
            <RefreshCw size={13} />
          </Button>
          <ChatCloseButton />
        </div>
      </div>

      <ModeSelector mode={mode} onModeChange={setMode} />

      {/* ── Research Context Strip ──────────────────────────────────────── */}
      {researchCtx && (researchCtx.research_direction || researchCtx.artifacts.length > 0) && (
        <div className="border-b border-border shrink-0">
          <button
            className="w-full px-3 py-1.5 flex items-center gap-1.5 hover:bg-muted/50 transition-colors text-left"
            onClick={() => setCtxExpanded(v => !v)}
          >
            {ctxExpanded ? <ChevronDown size={11} className="text-muted-foreground shrink-0" /> : <ChevronRight size={11} className="text-muted-foreground shrink-0" />}
            <span className="text-2xs text-muted-foreground truncate flex-1">
              {researchCtx.research_direction
                ? `研究: ${researchCtx.research_direction.slice(0, 40)}${researchCtx.research_direction.length > 40 ? '…' : ''}`
                : `产物: ${researchCtx.artifacts.map(a => `${a.type}(${a.count})`).join(' · ')}`
              }
            </span>
          </button>
          {ctxExpanded && (
            <div className="px-3 pb-2 space-y-1">
              {researchCtx.research_direction && (
                <p className="text-2xs text-muted-foreground leading-relaxed">
                  {researchCtx.research_direction}
                </p>
              )}
              {researchCtx.artifacts.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {researchCtx.artifacts.map(a => (
                    <span key={a.dir} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-muted text-2xs text-muted-foreground">
                      <ArtifactIcon type={a.dir} />
                      {a.type} ({a.count})
                    </span>
                  ))}
                </div>
              )}
              {researchCtx.workflow_history.length > 0 && (
                <div className="text-2xs text-muted-foreground">
                  最近: {researchCtx.workflow_history.slice(-2).map(r => (
                    <span key={r.nodes.join()} className="ml-1">
                      [{r.status}] {r.nodes.slice(0, 2).join('→')}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {(activeArtifactFile || attachedFiles.length > 0 || (activeFile && !activeArtifactFile)) && (
        <div className="px-3 py-1.5 border-b border-border shrink-0 flex items-center gap-1.5 overflow-hidden">
          <span className="text-2xs text-muted-foreground shrink-0">Context</span>
          {activeArtifactFile ? (
            <span className="inline-flex items-center gap-1 min-w-0 max-w-[55%] px-1.5 py-0.5 rounded bg-accent/40 text-2xs text-foreground" title={activeArtifactFile.path}>
              <FileText size={9} className="text-muted-foreground shrink-0" />
              <span className="truncate">{formatArtifactPath(activeArtifactFile.path, projectPath)}</span>
            </span>
          ) : activeFile ? (
            <span className="min-w-0 truncate text-2xs text-muted-foreground" title={activeFile.path}>
              当前文件不在科研产物范围
            </span>
          ) : null}
          {contextFiles.filter(f => f.path !== activeArtifactFile?.path).map(f => (
            <span key={f.path} className="inline-flex items-center gap-1 min-w-0 max-w-[38%] px-1.5 py-0.5 rounded bg-muted text-2xs text-muted-foreground" title={f.path}>
              <FileText size={9} className="shrink-0" />
              <span className="truncate">{formatArtifactPath(f.path, projectPath)}</span>
            </span>
          ))}
        </div>
      )}

      {/* ── Message List ───────────────────────────────────────────────── */}
      <div className="min-h-0 min-w-0 max-w-full flex-1 overflow-y-auto overflow-x-hidden">
        <div className="min-w-0 max-w-full overflow-hidden px-4 py-4 space-y-4">
          {messages.length === 0 && (
            <EmptyState activeFile={activeArtifactFile?.path} projectPath={projectPath} mode={mode} onSend={sendMessage} />
          )}

          {messages.map(msg => (
            <MessageBubble key={msg.id} message={msg} projectPath={projectPath} onRetry={retryLastMessage} onResolveChange={resolveChange} />
          ))}

          {isRunning && (
            <div className="flex items-center gap-2 text-2xs text-muted-foreground">
              <Loader2 size={11} className="animate-spin" />
              <span>{currentStatus}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ── Attached Files ──────────────────────────────────────────────── */}
      {attachedFiles.length > 0 && (
        <>
          <Separator className="bg-border-subtle" />
          <div className="px-3 py-1.5 flex flex-wrap gap-1 shrink-0">
            {attachedFiles.map(f => (
              <span key={f.path} className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-muted border border-border text-2xs text-foreground">
                <FileText size={10} className="text-muted-foreground" />
                <span className="truncate max-w-[140px]" title={f.path}>{formatArtifactPath(f.path, projectPath)}</span>
                <button onClick={() => detachFile(f.path)} className="ml-0.5 text-muted-foreground hover:text-foreground">
                  <X size={9} />
                </button>
              </span>
            ))}
          </div>
        </>
      )}

      {/* ── Input Area ─────────────────────────────────────────────────── */}
      <Separator className="bg-border-subtle" />
      <div className="px-4 py-3 shrink-0">
        {messages.length > 0 && !input.trim() && !isRunning && (
          <div className="mb-2 flex items-center gap-1.5 overflow-x-auto pb-0.5">
            <Wand2 size={11} className="shrink-0 text-muted-foreground" />
            {composerSuggestions.map(item => (
              <button
                key={item.label}
                type="button"
                onClick={() => sendMessage(item.prompt, item.mode)}
                className="h-6 shrink-0 rounded-md border border-border bg-background px-2 text-2xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
        {input.trim() && inferredMode !== mode && (
          <div className="mb-2 flex items-center gap-1.5 text-2xs text-muted-foreground">
            <Wand2 size={11} />
            <span>Auto mode:</span>
            <span className="rounded bg-accent px-1.5 py-0.5 text-foreground">{getChatModeConfig(inferredMode).label}</span>
          </div>
        )}
        <div className="min-w-0 max-w-full rounded-lg border border-border bg-muted focus-within:border-ring">
          <Textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={activeArtifactFile ? `${modeConfig.placeholder} ${activeArtifactFile.name}` : modeConfig.placeholder}
            rows={1}
            className="min-h-[42px] max-h-[180px] w-full max-w-full resize-none overflow-y-auto border-0 bg-transparent px-3 pb-1 pt-2 text-xs leading-relaxed text-foreground placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
          />

          {/* 附件 + 发送按钮 */}
          <div className="flex items-center justify-end gap-1 px-2 pb-2">
            {/* 附件选择器 */}
            <div className="relative">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => setShowFileMenu(v => !v)}
                className="text-muted-foreground hover:text-foreground w-6 h-6"
                title="附加文件"
              >
                <Plus size={12} />
              </Button>
              {showFileMenu && (
                <div className="absolute bottom-full right-0 z-50 mb-2 w-72 max-w-[calc(100vw-2rem)] overflow-hidden rounded-md border border-border bg-popover shadow-xl">
                  <div className="border-b border-border px-3 py-2">
                    <p className="text-2xs font-medium text-foreground">附加研究产物</p>
                    <p className="mt-0.5 text-2xs text-muted-foreground">
                      {attachableFileCount > 0 ? '从当前打开的研究文件中选择' : '没有可附加的打开文件'}
                    </p>
                  </div>
                  {attachableFileCount === 0 ? (
                    <p className="px-3 py-3 text-2xs leading-relaxed text-muted-foreground">
                      先打开 paper、slides、experiments、figures、literature 或 ideas 中的文件，再附加到会话。
                    </p>
                  ) : (
                    <div className="max-h-72 overflow-y-auto py-1">
                      {attachmentGroups.map(group => (
                        <div key={group.dir} className="py-1">
                          <div className="flex items-center gap-1.5 px-3 pb-1 pt-1 text-2xs font-medium text-muted-foreground">
                            <ArtifactIcon type={group.dir} />
                            <span>{group.label}</span>
                          </div>
                          {group.files.map(file => (
                            <button
                              key={file.path}
                              type="button"
                              disabled={file.isAttached}
                              onClick={() => attachFile({ path: file.path, name: file.name })}
                              className={cn(
                                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-2xs transition-colors',
                                file.isAttached ? 'cursor-default text-muted-foreground/60' : 'text-foreground hover:bg-accent'
                              )}
                              title={file.path}
                            >
                              <FileText size={11} className="shrink-0 text-muted-foreground" />
                              <span className="min-w-0 flex-1">
                                <span className="block truncate font-medium">
                                  {file.name}{file.isDirty ? ' *' : ''}
                                </span>
                                <span className="block truncate text-muted-foreground/70">
                                  {formatArtifactPath(file.path, projectPath)}
                                </span>
                              </span>
                              {file.isCurrent && <span className="shrink-0 rounded bg-accent px-1.5 py-0.5 text-[10px] text-foreground">当前</span>}
                              {file.isAttached ? <Check size={11} className="shrink-0 text-green-500" /> : <Plus size={11} className="shrink-0 text-muted-foreground" />}
                            </button>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 发送 / 停止 */}
            {isRunning ? (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={handleCancel}
                aria-label="停止回复"
                className="bg-red-500/20 text-red-400 hover:bg-red-500/30 hover:text-red-400 w-6 h-6"
              >
                <Square size={11} />
              </Button>
            ) : (
              <Button
                variant="default"
                size="icon-sm"
                onClick={() => sendMessage()}
                aria-label="发送消息"
                disabled={!input.trim() || availableProviders.length === 0}
                className="bg-primary text-primary-foreground hover:bg-primary/90 w-6 h-6"
              >
                <Send size={11} />
              </Button>
            )}
          </div>
        </div>

        {/* 关闭文件菜单的覆盖层 */}
        {showFileMenu && (
          <div className="fixed inset-0 z-40" onClick={() => setShowFileMenu(false)} />
        )}
      </div>
    </div>
  )
}
