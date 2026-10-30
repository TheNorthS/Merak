import { FileText, Folder, CircleCheck, CircleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { verificationLabel } from '@/lib/connection-status'
import { IntegrationToggle } from './IntegrationToggle'
import { type WorkflowConfig, MAX_AUTONOMOUS_REVISION_ROUNDS, MAX_RESEARCH_LOOP_CYCLES, normalizeResearchLoopCycles, normalizeRevisionRounds } from './workflowTypes'
import type { ConfigPanelModel } from './ConfigPanel'

export function ConfigPanelSecondary({ model }: { model: ConfigPanelModel }) {
  const { config, onUpdate, integrationStatus, compileNodeSelected, experimentExecutionEnabled, overleafProjects, sshServers, verifiedSshServers, sourceOptions, toggleLiteratureSource, isSourceConfigured } = model
  return <>
{/* Research Strategy */}<Card className="bg-background border-border">
          <CardHeader className="px-3 py-2">
            <CardTitle className="text-xs text-muted-foreground">研究策略控制</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">检索起始年</Label>
                <Input
                  type="number"
                  value={config.literatureYearFrom}
                  min={1900}
                  max={config.literatureYearTo}
                  onChange={e => onUpdate({ literatureYearFrom: Number(e.target.value) })}
                  className="h-7 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">检索截止年</Label>
                <Input
                  type="number"
                  value={config.literatureYearTo}
                  min={config.literatureYearFrom}
                  max={new Date().getFullYear()}
                  onChange={e => onUpdate({ literatureYearTo: Number(e.target.value) })}
                  className="h-7 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">主综述论文数</Label>
                <Input
                  type="number"
                  value={config.literatureMaxPapers}
                  min={5}
                  max={80}
                  onChange={e => onUpdate({
                    literatureMaxPapers: Math.max(5, Math.min(80, Number(e.target.value) || 35)),
                  })}
                  className="h-7 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">新颖性窗口</Label>
                <Input
                  type="number"
                  value={config.noveltyWindowYears}
                  min={1}
                  max={10}
                  onChange={e => onUpdate({ noveltyWindowYears: Number(e.target.value) })}
                  className="h-7 text-xs"
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-2xs text-muted-foreground">证据策略</Label>
              <Select value={config.evidencePolicy} onValueChange={v => onUpdate({ evidencePolicy: v as WorkflowConfig['evidencePolicy'] })}>
                <SelectTrigger className="bg-background border-border text-xs text-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="recent_balanced">Recent balanced</SelectItem>
                  <SelectItem value="frontier_first">Frontier first</SelectItem>
                  <SelectItem value="classic_balanced">Classic balanced</SelectItem>
                  <SelectItem value="systematic">Systematic review</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label className="text-2xs text-muted-foreground">文献来源</Label>
              <div className="grid grid-cols-2 gap-1.5">
                {sourceOptions.map(source => {
                  const sourceConfigured = isSourceConfigured(source.id)
                  return (
                    <label key={source.id} className={cn('flex items-center gap-1.5 text-xs', sourceConfigured ? 'text-muted-foreground' : 'text-muted-foreground/50')}>
                      <Checkbox
                        checked={sourceConfigured && config.literatureSources.includes(source.id)}
                        disabled={!sourceConfigured}
                        onCheckedChange={v => { if (sourceConfigured) toggleLiteratureSource(source.id, v === true) }}
                        className="w-3.5 h-3.5"
                      />
                      <span>{source.label}{!sourceConfigured ? '（未配置）' : ''}</span>
                    </label>
                  )
                })}
              </div>
            </div>

            <div className="space-y-2">
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">会议/期刊/领域过滤</Label>
                <Input
                  value={config.literatureVenues}
                  onChange={e => onUpdate({ literatureVenues: e.target.value })}
                  placeholder="如: NeurIPS, ICLR, IEEE TBME, clinical EEG"
                  className="h-7 text-xs"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-2xs text-muted-foreground">必须包含</Label>
                  <Input
                    value={config.includeKeywords}
                    onChange={e => onUpdate({ includeKeywords: e.target.value })}
                    placeholder="montage, foundation model"
                    className="h-7 text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-2xs text-muted-foreground">排除主题</Label>
                  <Input
                    value={config.excludeKeywords}
                    onChange={e => onUpdate({ excludeKeywords: e.target.value })}
                    placeholder="survey only, non-EEG"
                    className="h-7 text-xs"
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">检索种子论文</Label>
                <Textarea
                  value={config.seedPapers}
                  onChange={e => onUpdate({ seedPapers: e.target.value })}
                  placeholder="进入文献检索和新颖性检查；每行一个标题、DOI、arXiv ID 或本地路径"
                  rows={2}
                  className="text-xs resize-y"
                />
              </div>
              {config.enablePatentSearch && (
                <div className="space-y-1.5 border-t border-border/70 pt-2">
                  <Label className="text-2xs text-muted-foreground">专利检索范围</Label>
                  <div className="grid grid-cols-3 gap-2">
                    <Input
                      type="number"
                      value={config.patentDateFrom}
                      min={1800}
                      max={config.patentDateTo}
                      onChange={e => onUpdate({ patentDateFrom: Number(e.target.value) })}
                      className="h-7 text-xs"
                      title="申请起始年"
                    />
                    <Input
                      type="number"
                      value={config.patentDateTo}
                      min={config.patentDateFrom}
                      max={new Date().getFullYear()}
                      onChange={e => onUpdate({ patentDateTo: Number(e.target.value) })}
                      className="h-7 text-xs"
                      title="申请截止年"
                    />
                    <Input
                      type="number"
                      value={config.patentMaxResults}
                      min={1}
                      max={50}
                      onChange={e => onUpdate({ patentMaxResults: Math.max(1, Math.min(50, Number(e.target.value) || 15)) })}
                      className="h-7 text-xs"
                      title="最多专利数"
                    />
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>{/* Reference evidence for paper + code innovation mode */}{(config.researchMode === 'paper_code_innovation' || (experimentExecutionEnabled && config.gpu === 'remote')) && (
        <Card className="bg-background border-border">
          <CardContent className="p-3 space-y-3">
            {config.researchMode === 'paper_code_innovation' && (<>
            <div className="space-y-1">
              <Label className="text-2xs text-muted-foreground">Reference Paper (PDF/TeX) *</Label>
              <div className="flex gap-1">
                <div className="flex-1 min-w-0 space-y-1">
                  <Input
                    value={config.refPaper}
                    onChange={e => onUpdate({ refPaper: e.target.value })}
                    placeholder="选择本地 PDF、TeX 文件或 TeX 项目中的主文件"
                    className="bg-background border-border text-xs text-foreground placeholder:text-muted-foreground focus:border-border"
                  />
                  <p className="text-2xs text-muted-foreground">系统会抽取论文主张并与代码实际实现逐项核对，不把参考论文当作正确答案。</p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    const path = await window.merakIDE?.fs.openFile([
                      { name: 'Paper', extensions: ['pdf', 'tex'] },
                      { name: 'All Files', extensions: ['*'] },
                    ])
                    if (path) onUpdate({ refPaper: path })
                  }}
                  className="bg-accent text-xs text-muted-foreground hover:text-foreground"
                  title="Browse files"
                >
                  <FileText size={14} />
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    const path = await window.merakIDE?.fs.openFolder()
                    if (path) onUpdate({ refPaper: path })
                  }}
                  className="bg-accent text-xs text-muted-foreground hover:text-foreground"
                  title="选择 TeX 项目目录"
                >
                  <Folder size={14} />
                </Button>
              </div>
            </div>

            {/* Code Dir — folder picker */}
            <div className="space-y-1">
              <Label className="text-2xs text-muted-foreground">Reference Code Directory *</Label>
              <div className="flex gap-1">
                <Input
                  value={config.baseRepo}
                  onChange={e => onUpdate({ baseRepo: e.target.value })}
                  placeholder="选择已检出的本地代码仓库"
                  className="flex-1 min-w-0 bg-background border-border text-xs text-foreground placeholder:text-muted-foreground focus:border-border"
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    const path = await window.merakIDE?.fs.openFolder()
                    if (path) onUpdate({ baseRepo: path })
                  }}
                  className="bg-accent text-xs text-muted-foreground hover:text-foreground"
                  title="Browse folder"
                >
                  <Folder size={14} />
                </Button>
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-2xs text-muted-foreground">期望创新方向或约束（可选）</Label>
              <Textarea
                value={config.innovationFocus}
                onChange={e => onUpdate({ innovationFocus: e.target.value })}
                placeholder="例如：保持原训练预算，重点改进跨域泛化；不得增加推理延迟超过 10%"
                rows={3}
                className="text-xs resize-y"
              />
            </div>

            </>)}

            {/* SSH server selection is restricted to current, tested configurations. */}
            {experimentExecutionEnabled && config.gpu === 'remote' && (
              <div className="space-y-1.5 rounded-md border border-border bg-muted/30 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <Label className="text-2xs text-muted-foreground">SSH 服务器</Label>
                  <Badge variant="outline" className="h-5 px-1.5 text-[10px] font-normal text-green-500 border-green-500/30">
                    {verifiedSshServers.length} 台已验证
                  </Badge>
                </div>
                <Select
                  value={verifiedSshServers.some(server => server.id === config.sshServer) ? config.sshServer : undefined}
                  onValueChange={value => onUpdate({ sshServer: value })}
                  disabled={verifiedSshServers.length === 0}
                >
                  <SelectTrigger className="h-9 bg-background border-border text-xs">
                    <SelectValue placeholder={sshServers.length === 0 ? '未配置 SSH 服务器' : '选择已通过测试的服务器'} />
                  </SelectTrigger>
                  <SelectContent>
                    {sshServers.length === 0 ? (
                      <SelectItem value="__unconfigured" disabled>未配置 SSH 服务器</SelectItem>
                    ) : sshServers.map(server => (
                      <SelectItem key={server.id} value={server.id} disabled={!server.verification?.verified}>
                        <span className="flex min-w-0 items-center gap-2">
                          {server.verification?.verified
                            ? <CircleCheck size={13} className="text-green-500" />
                            : <CircleAlert size={13} className="text-yellow-500" />}
                          <span className="truncate">{server.name}（{server.user}@{server.host}）</span>
                          {!server.verification?.verified && (
                            <span className="shrink-0 text-muted-foreground">{verificationLabel(server.verification)}</span>
                          )}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {verifiedSshServers.length === 0 && (
                  <p className="text-[10px] leading-4 text-muted-foreground">
                    请先在设置的 SSH 服务器区域完成配置并通过连接测试。
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
        )}{/* Toggles — all MERAK options */}<Card className="bg-background border-border">
          <CardHeader className="px-3 py-2">
            <CardTitle className="text-2xs text-muted-foreground">流水线选项</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0 space-y-3">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-proceed" className="text-xs text-muted-foreground">自动继续</Label>
              <Switch id="auto-proceed" checked={config.autoProceed} onCheckedChange={v => onUpdate({ autoProceed: v })} />
            </div>
            <div className="space-y-2 rounded border border-border/70 bg-card/40 p-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="human-checkpoint" className="text-xs text-muted-foreground">人工检查点</Label>
                <Switch id="human-checkpoint" checked={config.humanCheckpoint} onCheckedChange={v => onUpdate({ humanCheckpoint: v })} />
              </div>
              <p className="text-[10px] leading-4 text-muted-foreground">
                仅在选定的关键决策点暂停一次；重试或断点恢复不会重复询问。未操作时按等待时长自动继续。
                科研质量修订和实验异常由独立规则处理。
              </p>
              {config.humanCheckpoint && (
                <div className="space-y-2 rounded border border-border/60 bg-background/50 p-2">
                  <Label className="text-2xs text-muted-foreground">暂停位置</Label>
                  {[
                    { id: 'exp-design', label: 'Idea 确认', disabled: false },
                    { id: 'exp-run', label: '实验执行前', disabled: !experimentExecutionEnabled },
                    { id: 'paper', label: '论文撰写前', disabled: false },
                  ].map(item => (
                    <div key={item.id} className="flex items-center gap-2">
                      <Checkbox
                        id={'checkpoint-' + item.id}
                        checked={!item.disabled && config.humanCheckpointNodes.includes(item.id)}
                        disabled={item.disabled}
                        onCheckedChange={checked => {
                          const next = checked === true
                            ? Array.from(new Set([...config.humanCheckpointNodes, item.id]))
                            : config.humanCheckpointNodes.filter(nodeId => nodeId !== item.id)
                          onUpdate({ humanCheckpointNodes: next })
                        }}
                      />
                      <Label
                        htmlFor={'checkpoint-' + item.id}
                        className={cn('text-xs font-normal', item.disabled && 'text-muted-foreground')}
                      >
                        {item.label}{item.disabled ? '（未执行实验）' : ''}
                      </Label>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2 rounded border border-border/70 bg-card/40 p-2">
              <div>
                <Label className="text-xs text-muted-foreground">自动修订、恢复与反馈策略</Label>
                <p className="text-[10px] leading-4 text-muted-foreground">
                  节点修订预算用于单次质量循环；返工与恢复上限用于新的有限周期；反馈时长只作用于人工检查点。
                </p>
              </div>
              <div className="flex items-center justify-between gap-3 rounded border border-border/60 bg-muted/20 p-2">
                <div>
                  <Label htmlFor="max-revision-rounds" className="text-2xs text-muted-foreground">自动修订轮次上限</Label>
                  <p className="text-[10px] leading-4 text-muted-foreground">
                    可设置 1–12 轮；传输重试不计入科研修订轮数。
                  </p>
                </div>
                <Select
                  value={String(normalizeRevisionRounds(config.maxRevisionRounds))}
                  onValueChange={value => onUpdate({ maxRevisionRounds: normalizeRevisionRounds(value) })}
                >
                  <SelectTrigger id="max-revision-rounds" className="h-7 w-20 shrink-0 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: MAX_AUTONOMOUS_REVISION_ROUNDS }, (_, index) => index + 1).map(rounds => (
                      <SelectItem key={rounds} value={String(rounds)}>{rounds} 轮</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between gap-3 rounded border border-border/60 bg-muted/20 p-2">
                <div>
                  <Label htmlFor="max-research-loop-cycles" className="text-2xs text-muted-foreground">科研返工与平台恢复上限</Label>
                  <p className="text-[10px] leading-4 text-muted-foreground">
                    审稿发现上游问题或平台产物修复未闭环时开启新周期；每个节点仍使用自己的修订预算。
                  </p>
                </div>
                <Select
                  value={String(normalizeResearchLoopCycles(config.maxResearchLoopCycles))}
                  onValueChange={value => onUpdate({ maxResearchLoopCycles: normalizeResearchLoopCycles(value) })}
                >
                  <SelectTrigger id="max-research-loop-cycles" className="h-7 w-20 shrink-0 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: MAX_RESEARCH_LOOP_CYCLES }, (_, index) => index + 1).map(cycles => (
                      <SelectItem key={cycles} value={String(cycles)}>{cycles} 次</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="checkpoint-timeout" className="text-2xs text-muted-foreground">人工反馈等待时长</Label>
                <Select
                  value={String(config.checkpointTimeoutSeconds)}
                  disabled={!config.humanCheckpoint}
                  onValueChange={value => onUpdate({ checkpointTimeoutSeconds: Number(value) })}
                >
                  <SelectTrigger id="checkpoint-timeout" className="h-7 w-28 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="60">1 分钟</SelectItem>
                    <SelectItem value="120">2 分钟</SelectItem>
                    <SelectItem value="300">5 分钟</SelectItem>
                    <SelectItem value="600">10 分钟</SelectItem>
                    <SelectItem value="1800">30 分钟</SelectItem>
                    <SelectItem value="3600">60 分钟</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="code-review" className="text-xs text-muted-foreground">代码审查</Label>
              <Switch id="code-review" checked={config.codeReview} onCheckedChange={v => onUpdate({ codeReview: v })} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="compact" className="text-xs text-muted-foreground">精简模式</Label>
              <Switch id="compact" checked={config.compact} onCheckedChange={v => onUpdate({ compact: v })} />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="wandb" className={cn('text-xs', experimentExecutionEnabled ? 'text-muted-foreground' : 'text-muted-foreground/50')}>W&B 日志</Label>
              <Switch
                id="wandb"
                checked={experimentExecutionEnabled && config.wandb}
                disabled={!experimentExecutionEnabled}
                onCheckedChange={v => onUpdate({ wandb: v })}
              />
            </div>
          </CardContent>
        </Card>{/* 集成服务 */}<Card>
          <CardHeader className="py-2 px-3">
            <CardTitle className="text-xs">集成服务</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 px-3 pb-3">
            <IntegrationToggle
              id="gemini"
              label="Gemini 搜索"
              checked={config.enableGemini}
              onChange={value => onUpdate({
                enableGemini: value,
                literatureSources: value
                  ? config.literatureSources
                  : config.literatureSources.filter(source => source !== 'gemini'),
              })}
              status={integrationStatus.gemini}
            />
            <IntegrationToggle id="gpt-image" label="GPT Image" checked={config.enableGptImage} onChange={v => onUpdate({ enableGptImage: v })} status={integrationStatus.gpt_image} />
            <IntegrationToggle
              id="zotero"
              label="Zotero"
              checked={config.enableZotero}
              onChange={value => onUpdate({
                enableZotero: value,
                literatureSources: value
                  ? Array.from(new Set([...config.literatureSources, 'zotero']))
                  : config.literatureSources.filter(source => source !== 'zotero'),
              })}
              status={integrationStatus.zotero}
            />
            <IntegrationToggle
              id="obsidian"
              label="Obsidian"
              checked={config.enableObsidian}
              onChange={value => onUpdate({
                enableObsidian: value,
                literatureSources: value
                  ? Array.from(new Set([...config.literatureSources, 'obsidian']))
                  : config.literatureSources.filter(source => source !== 'obsidian'),
              })}
              status={integrationStatus.obsidian}
            />
            <div className="space-y-1.5 border-t border-border/70 pt-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5">
                  <Label htmlFor="overleaf-sync" className={cn('truncate text-xs', overleafProjects.length && compileNodeSelected ? 'text-foreground' : 'text-muted-foreground')}>Overleaf 编译后同步</Label>
                  <Badge variant="outline" className={cn(
                    'h-5 shrink-0 px-1.5 text-[10px] font-normal',
                    overleafProjects.length && compileNodeSelected
                      ? 'border-green-500/30 bg-green-500/10 text-green-500'
                      : 'border-border bg-muted text-muted-foreground',
                  )}>
                    {!compileNodeSelected ? '需编译节点' : overleafProjects.length ? '已关联' : '未关联'}
                  </Badge>
                </div>
                <Switch
                  id="overleaf-sync"
                  checked={overleafProjects.length && compileNodeSelected ? config.enableOverleafSync : false}
                  disabled={!overleafProjects.length || !compileNodeSelected}
                  onCheckedChange={value => onUpdate({
                    enableOverleafSync: value,
                    overleafProjectId: value
                      ? config.overleafProjectId || overleafProjects[0]?.project_id || ''
                      : config.overleafProjectId,
                  })}
                />
              </div>
              {config.enableOverleafSync && overleafProjects.length > 0 && (
                <Select value={config.overleafProjectId} onValueChange={value => onUpdate({ overleafProjectId: value })}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="选择 Overleaf 项目" /></SelectTrigger>
                  <SelectContent>
                    {overleafProjects.map(project => (
                      <SelectItem key={project.project_id} value={project.project_id}>
                        {project.project_id} · {project.branch}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <IntegrationToggle id="patent" label="专利先前技术检索" checked={config.enablePatentSearch} onChange={v => onUpdate({ enablePatentSearch: v })} status={integrationStatus.patent} />
            <div className="flex items-center justify-between gap-2 border-t border-border/70 pt-2">
              <div className="min-w-0">
                <Label htmlFor="meta-optimization" className="text-xs text-foreground">自进化优化</Label>
                <p className="text-[10px] leading-4 text-muted-foreground">只生成待审批 skill 提案，不自动修改或绕过审计</p>
              </div>
              <Switch id="meta-optimization" checked={config.enableMetaOptimization} onCheckedChange={v => onUpdate({ enableMetaOptimization: v })} />
            </div>
          </CardContent>
        </Card>
  </>
}
