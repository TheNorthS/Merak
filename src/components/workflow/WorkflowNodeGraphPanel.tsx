import { useEffect, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import {
  AlertTriangle, Cpu, Link2, RotateCcw, Server, Zap,
} from 'lucide-react'

import { API_BASE } from '../../config'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

import { NodeStatus } from './NodeStatus'
import type {
  SpecialistNodeProgress, WorkflowNode,
} from './workflowViewModels'


export function NodeGraphPanel({ nodes, setNodes, isRunning, hasProject, focusedNode, setFocusedNode, nodeSchema, nodeParams, setNodeParams, handleRunSingleNode, specialistNodes }: {
  nodes: WorkflowNode[]; setNodes: Dispatch<SetStateAction<WorkflowNode[]>>; isRunning: boolean;
  hasProject: boolean;
  focusedNode: string | null; setFocusedNode: (id: string | null) => void;
  nodeSchema: any; nodeParams: Record<string, any>; setNodeParams: Dispatch<SetStateAction<Record<string, any>>>;
  handleRunSingleNode: () => void;
  specialistNodes: SpecialistNodeProgress[];
}) {
  // 原子组定义 — 从后端 API 加载
  const [atomicGroups, setAtomicGroups] = useState<Record<string, string[]>>({ experiment: ['exp-design', 'exp-run'] })

  useEffect(() => {
    fetch(`${API_BASE}/api/merak/atomic-groups`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.groups) {
          const groups: Record<string, string[]> = {}
          for (const [key, val] of Object.entries(data.groups as Record<string, any>)) {
            groups[key] = val.node_ids
          }
          setAtomicGroups(groups)
        }
      })
      .catch(() => {})
  }, [])

  const toggle = (id: string) => {
    if (isRunning) return
    setNodes(prev => {
      const node = prev.find(n => n.id === id)
      if (!node) return prev
      const newSelected = !node.selected

      // 查找该节点是否属于原子组
      let affectedIds = [id]
      for (const [, members] of Object.entries(atomicGroups)) {
        if (members.includes(id)) {
          affectedIds = members // 整组一起切换
          break
        }
      }

      return prev.map(n => affectedIds.includes(n.id) ? { ...n, selected: newSelected } : n)
    })
  }

  const stages = [
    { label: 'Research & Discovery', ids: ['lit', 'idea', 'novelty'] },
    { label: 'Experiments', ids: ['exp-design', 'exp-run', 'results'] },
    { label: 'Figures & Writing', ids: ['narrative', 'figure', 'paper'] },
    { label: 'Review & Output', ids: ['review', 'audit', 'compile', 'ppt'] },
  ]

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Pipeline Nodes</h3>
        <Badge variant="secondary" className="text-2xs">
          {nodes.filter(n => n.selected).length}/{nodes.length} selected
        </Badge>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-3 space-y-3">
          {stages.map(stage => (
            <Card key={stage.label} className="bg-background border-border overflow-hidden">
              <CardHeader className="px-3 py-1.5 bg-card">
                <CardTitle className="text-2xs text-muted-foreground font-medium">
                  {stage.label}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                {stage.ids.map(id => {
                  const node = nodes.find(n => n.id === id)!
                  return (
                    <div
                      key={id}
                      className={cn(
                        'flex items-center gap-2.5 px-3 py-2 border-l-2 transition-all',
                        focusedNode === id && 'ring-1 ring-ring',
                        node.selected && node.status === 'idle' && 'border-l-foreground/60',
                        !node.selected && 'border-l-transparent opacity-50',
                        node.status === 'running' && 'border-l-foreground bg-accent',
                        node.status === 'completed' && 'border-l-green-500 bg-green-500/5',
                        node.status === 'failed' && 'border-l-red-500 bg-red-500/5',
                      )}
                    >
                      <Checkbox
                        checked={node.selected}
                        disabled={isRunning}
                        onCheckedChange={() => toggle(id)}
                        className="w-3.5 h-3.5 border-border data-[state=checked]:bg-primary data-[state=checked]:border-border"
                      />
                      <span className="text-muted-foreground shrink-0">{node.icon}</span>
                      <span
                        className="text-xs text-foreground flex-1 cursor-pointer hover:text-foreground"
                        onClick={() => setFocusedNode(focusedNode === id ? null : id)}
                      >
                        {node.name}
                      </span>
                      {Object.values(atomicGroups).some(g => g.includes(node.id)) && (
                        <Badge variant="outline" className="text-2xs text-blue-400 border-blue-400/30 px-1" title="Atomic group — must run together"><Link2 size={10} /></Badge>
                      )}
                      {node.executionKind && (
                        <span className="flex items-center gap-1 shrink-0">
                          {node.executionKind !== 'runtime_owned' && (
                            <span title={node.modelVerified
                              ? `已验证模型会话: /${node.ownerSkill || 'stage-owner'}`
                              : `等待模型执行证据: /${node.ownerSkill || 'stage-owner'}`}>
                              <Cpu
                                size={12}
                                className={node.modelVerified ? 'text-green-400' : 'text-muted-foreground/50'}
                              />
                            </span>
                          )}
                          {node.executionKind !== 'model_owned' && (
                            <span title={node.runtimeVerified
                              ? `已验证运行时服务: ${node.runtimeService || 'workflow runtime'}`
                              : `等待运行时执行证据: ${node.runtimeService || 'workflow runtime'}`}>
                              <Server
                                size={12}
                                className={node.runtimeVerified ? 'text-green-400' : 'text-muted-foreground/50'}
                              />
                            </span>
                          )}
                        </span>
                      )}
                      {node.validationLabel ? <span className="text-xs text-muted-foreground">{node.validationLabel}</span> : <NodeStatus status={node.status} />}
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          ))}
          {specialistNodes.length > 0 && (
            <Card className="bg-background border-border overflow-hidden">
              <CardHeader className="px-3 py-1.5 bg-card">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-2xs text-muted-foreground font-medium">
                    动态专家子节点
                  </CardTitle>
                  <Badge variant="outline" className="text-2xs px-1.5">
                    {specialistNodes.filter(item => ['completed', 'reused'].includes(item.status)).length}/{specialistNodes.length}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {specialistNodes.map(item => (
                  <div
                    key={item.id}
                    className={cn(
                      'flex items-start gap-2.5 px-3 py-2 border-l-2 border-t border-border/60 first:border-t-0',
                      item.status === 'running' && 'border-l-foreground bg-accent',
                      item.status === 'completed' && 'border-l-green-500 bg-green-500/5',
                      item.status === 'reused' && 'border-l-cyan-500 bg-cyan-500/5',
                      item.status === 'failed' && 'border-l-red-500 bg-red-500/5',
                      item.status === 'pending' && 'border-l-muted-foreground/30',
                    )}
                    title={item.artifact || undefined}
                  >
                    <span className="mt-0.5 shrink-0">
                      {item.status === 'reused'
                        ? <RotateCcw size={14} className="text-cyan-400" />
                        : <NodeStatus status={item.status} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-foreground truncate">{item.name}</div>
                      <div className="mt-0.5 flex items-center gap-1.5 min-w-0">
                        <Badge variant="secondary" className="text-2xs px-1 py-0 shrink-0">
                          {nodes.find(node => node.id === item.nodeId)?.name || item.nodeId}
                        </Badge>
                        <span className="text-2xs text-muted-foreground truncate">
                          /{item.skill || 'unknown'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </ScrollArea>

      {/* 聚焦节点的输入表单 */}
      {focusedNode && nodeSchema && (
        <div className="border-t border-border bg-card p-3 space-y-2 max-h-[40%] overflow-y-auto">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-foreground">
              {nodes.find(n => n.id === focusedNode)?.icon} {nodes.find(n => n.id === focusedNode)?.name} — 输入参数
            </span>
            <Button variant="ghost" size="sm" onClick={() => setFocusedNode(null)} className="text-2xs text-muted-foreground hover:text-foreground h-5 w-5 p-0">✕</Button>
          </div>
          {nodeSchema.atomic && (
            <p className="text-2xs text-yellow-400 bg-yellow-500/10 px-2 py-1 rounded flex items-center gap-1.5">
              <AlertTriangle size={11} className="shrink-0" />
              此节点为原子操作，执行后不可中断
            </p>
          )}
          {nodeSchema.fields.map((field: any) => (
            <div key={field.name} className="space-y-0.5">
              <Label className="text-2xs text-muted-foreground">
                {field.label} {field.required && <span className="text-red-400">*</span>}
              </Label>
              {field.type === 'textarea' ? (
                <Textarea
                  value={nodeParams[field.name] || ''}
                  onChange={e => setNodeParams(p => ({ ...p, [field.name]: e.target.value }))}
                  placeholder={field.placeholder}
                  rows={2}
                  className="bg-background border-border text-xs text-foreground placeholder:text-muted-foreground focus:border-border resize-y"
                />
              ) : field.type === 'select' ? (
                <Select
                  value={nodeParams[field.name] || field.default || ''}
                  onValueChange={v => setNodeParams(p => ({ ...p, [field.name]: v }))}
                >
                  <SelectTrigger className="bg-background border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {field.options?.map((o: string) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : field.type === 'multiselect' ? (
                <div className="grid grid-cols-1 gap-1 rounded border border-border bg-background p-2">
                  {field.options?.map((option: string) => {
                    const selectedValues = Array.isArray(nodeParams[field.name])
                      ? nodeParams[field.name].map(String)
                      : Array.isArray(field.default)
                        ? field.default.map(String)
                        : []
                    const checked = selectedValues.includes(option)
                    return (
                      <label key={option} className="flex items-center gap-2 text-xs text-foreground">
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(next) => setNodeParams(previous => {
                            const current = Array.isArray(previous[field.name])
                              ? previous[field.name].map(String)
                              : Array.isArray(field.default)
                                ? field.default.map(String)
                                : []
                            return {
                              ...previous,
                              [field.name]: next === true
                                ? Array.from(new Set([...current, option]))
                                : current.filter((item: string) => item !== option),
                            }
                          })}
                        />
                        {option}
                      </label>
                    )
                  })}
                </div>
              ) : (
                <Input
                  type={field.type === 'number' ? 'number' : 'text'}
                  value={nodeParams[field.name] ?? field.default ?? ''}
                  onChange={e => setNodeParams(p => ({ ...p, [field.name]: field.type === 'number' ? Number(e.target.value) : e.target.value }))}
                  placeholder={field.placeholder}
                  className="bg-background border-border text-xs text-foreground placeholder:text-muted-foreground focus:border-border"
                />
              )}
            </div>
          ))}
          <Button
            onClick={handleRunSingleNode}
            disabled={isRunning || !hasProject}
            title={!hasProject ? '请先打开研究项目' : '执行此节点'}
            className="w-full bg-primary text-primary-foreground text-xs hover:bg-primary/90 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            <Zap size={12} />
            {hasProject ? '执行此节点' : '请先打开项目'}
          </Button>
        </div>
      )}
    </div>
  )
}
