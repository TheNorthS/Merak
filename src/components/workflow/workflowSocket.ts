import { API_BASE } from '../../config'
import { decodeWorkflowMessage } from './workflowMessages'
import { handleCoreWorkflowEvent } from './workflowEventCore'
import { handleExperimentWorkflowEvent } from './workflowEventExperiment'
import { handleTerminalWorkflowEvent } from './workflowEventTerminal'
import type { WorkflowSocketContext } from './workflowContext'
export type { WorkflowSocketContext } from './workflowContext'

export function createWorkflowSocketConnector(contextProvider: () => WorkflowSocketContext) {
  const connectWs = () => {
    const context = contextProvider()
    const { wsRef, allowWsReconnectRef, wsReconnectAttemptRef, addLog,
      recoverWorkflowDisplayLogs, recoverExperimentRuntime, currentRunIdRef,
      pausedRunIdRef, wsReconnectTimerRef } = context
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) return
    allowWsReconnectRef.current = true
    const ws = new WebSocket(API_BASE.replace('http', 'ws') + '/ws/workflow')
    wsRef.current = ws
    ws.onopen = () => {
      wsReconnectAttemptRef.current = 0
      addLog('System', '已连接实时状态推送', 'info')
      recoverWorkflowDisplayLogs().catch(() => {})
      recoverExperimentRuntime().catch(() => {})
    }
    ws.onerror = () => addLog('System', 'WebSocket 连接失败', 'error')
    ws.onclose = () => {
      if (wsRef.current !== ws) return
      addLog('System', '实时连接已断开', 'info')
      wsRef.current = null
      if (allowWsReconnectRef.current && (currentRunIdRef.current || pausedRunIdRef.current)) {
        const delay = Math.min(15000, 1000 * (2 ** wsReconnectAttemptRef.current))
        wsReconnectAttemptRef.current += 1
        wsReconnectTimerRef.current = setTimeout(() => {
          wsReconnectTimerRef.current = null
          connectWs()
        }, delay)
      }
    }
    ws.onmessage = event => {
      try {
        const msg = decodeWorkflowMessage(String(event.data))
        const eventRunId = msg.run_id ? String(msg.run_id) : ''
        const activeRunId = currentRunIdRef.current || pausedRunIdRef.current
        if (eventRunId && activeRunId && eventRunId !== activeRunId) return
        if (eventRunId && !activeRunId && msg.type !== 'runs_status' && msg.type !== 'user_question') return
        const fresh = { ...contextProvider(), eventRunId }
        if (handleCoreWorkflowEvent(msg, fresh)) return
        if (handleExperimentWorkflowEvent(msg, fresh)) return
        handleTerminalWorkflowEvent(msg, fresh)
      } catch (error) {
        console.error('Failed to parse workflow WebSocket message', error)
        addLog('System', '收到无法解析的工作流状态消息，已忽略该条消息。', 'warn')
      }
    }
  }
  return connectWs
}
