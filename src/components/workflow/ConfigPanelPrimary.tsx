import { useEffect, useState } from 'react'
import { XCircle, FileText, Folder, AlertTriangle, BookOpen, Sparkles, Server, Cpu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { verificationLabel } from '@/lib/connection-status'
import { type WorkflowConfig } from './workflowTypes'
import type { ConfigPanelModel } from './ConfigPanel'

export function ConfigPanelPrimary({ model }: { model: ConfigPanelModel }) {
  const { config, onUpdate, integrationStatus, experimentNodeSelected, venuePageLimits, experimentExecutionEnabled, submissionAssurance, importedEvidenceMode, workflowProjectPath, inputFileError, addWorkflowInput, sshServers, verifiedSshServers } = model
  const [targetPagesDraft, setTargetPagesDraft] = useState(String(config.targetPages))
  const [targetPageToleranceDraft, setTargetPageToleranceDraft] = useState(String(config.targetPageTolerance))

  useEffect(() => {
    setTargetPagesDraft(String(config.targetPages))
  }, [config.targetPages])

  useEffect(() => {
    setTargetPageToleranceDraft(String(config.targetPageTolerance))
  }, [config.targetPageTolerance])

  return <>
{/* 研究方向 */}<Card className="bg-background border-border">
          <CardHeader className="px-3 py-2">
            <CardTitle className="text-xs text-muted-foreground">研究方向 *</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0">
            <Textarea
              value={config.researchDirection}
              onChange={e => onUpdate({ researchDirection: e.target.value })}
              placeholder="描述你的研究问题和目标..."
              rows={4}
              className="bg-background border-border text-xs text-foreground placeholder:text-muted-foreground focus:border-border resize-none"
            />
          </CardContent>
        </Card><Card className="bg-background border-border">
          <CardHeader className="px-3 py-2">
            <CardTitle className="text-xs text-muted-foreground">科研任务模式</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 pt-0 space-y-2">
            <div className="grid min-w-0 grid-cols-2 gap-1 rounded-md border border-border bg-muted p-1" role="radiogroup" aria-label="科研任务模式">
              <button
                type="button"
                role="radio"
                aria-checked={config.researchMode === 'from_scratch'}
                onClick={() => onUpdate({ researchMode: 'from_scratch', refPaper: '', baseRepo: '', innovationFocus: '' })}
                className={cn(
                  'flex min-h-10 min-w-0 items-center justify-center gap-1.5 rounded-sm border px-2 py-1.5 text-xs font-medium leading-4 transition-[color,background-color,border-color,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
                  config.researchMode === 'from_scratch'
                    ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                    : 'border-transparent text-muted-foreground hover:border-border hover:bg-accent hover:text-accent-foreground',
                )}
              >
                <BookOpen size={14} className="shrink-0" aria-hidden="true" />
                <span className="min-w-0 whitespace-normal break-words text-center">从研究问题开始</span>
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={config.researchMode === 'paper_code_innovation'}
                onClick={() => onUpdate({ researchMode: 'paper_code_innovation' })}
                className={cn(
                  'flex min-h-10 min-w-0 items-center justify-center gap-1.5 rounded-sm border px-2 py-1.5 text-xs font-medium leading-4 transition-[color,background-color,border-color,box-shadow] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
                  config.researchMode === 'paper_code_innovation'
                    ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                    : 'border-transparent text-muted-foreground hover:border-border hover:bg-accent hover:text-accent-foreground',
                )}
              >
                <Sparkles size={14} className="shrink-0" aria-hidden="true" />
                <span className="min-w-0 whitespace-normal break-words text-center">基于论文 + 代码创新</span>
              </button>
            </div>
            <p className="text-[10px] leading-4 text-muted-foreground">
              {config.researchMode === 'paper_code_innovation'
                ? '先审计论文主张与代码实况，再复现基线、定义创新增量并做受控验证。'
                : '从文献检索、Idea 发现和新颖性筛查开始建立研究证据链。'}
            </p>
          </CardContent>
        </Card><Card className="bg-background border-border">
          <CardHeader className="px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-xs text-muted-foreground">本次运行采用的已有材料（可选）</CardTitle>
              <Button
                variant="outline"
                size="sm"
                onClick={addWorkflowInput}
                disabled={!workflowProjectPath}
                className="h-7 px-2 text-[11px]"
                title={!workflowProjectPath ? '请先打开研究项目' : '选择项目文件'}
              >
                <FileText size={13} />
                选择项目文件
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2 px-3 pb-3 pt-0">
            <p className="text-[10px] leading-4 text-muted-foreground">
              从当前项目中选择已有论文、笔记、配置或结果作为本次运行的权威输入。系统会记录内容哈希，
              不会要求节点把它们重写；它们仍需经过引用、证据和质量检查，不会被自动视为可信结论。
            </p>
            {!workflowProjectPath && (
              <p className="text-[10px] leading-4 text-amber-300">
                打开项目后才能选择项目内的已有材料。
              </p>
            )}
            {config.inputFiles.length > 0 && (
              <div className="space-y-1">
                {config.inputFiles.map(path => {
                  const normalizedRoot = (workflowProjectPath || '').replace(/\\/g, '/').replace(/\/+$/, '')
                  const normalizedPath = path.replace(/\\/g, '/')
                  const label = normalizedRoot && normalizedPath.toLowerCase().startsWith((normalizedRoot + '/').toLowerCase())
                    ? normalizedPath.slice(normalizedRoot.length + 1)
                    : normalizedPath
                  return (
                    <div key={path} className="flex min-w-0 items-center gap-2 rounded border border-border bg-muted/20 px-2 py-1.5">
                      <FileText size={12} className="shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-foreground" title={path}>{label}</span>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => onUpdate({ inputFiles: config.inputFiles.filter(item => item !== path) })}
                        className="h-6 w-6 shrink-0 text-muted-foreground hover:text-destructive"
                        title="移除输入文件"
                      >
                        <XCircle size={13} />
                      </Button>
                    </div>
                  )
                })}
              </div>
            )}
            {inputFileError && (
              <p className="text-[10px] leading-4 text-destructive" role="alert">{inputFileError}</p>
            )}
          </CardContent>
        </Card>{/* Effort & Assurance */}<Card className="bg-background border-border">
          <CardContent className="p-3 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">Effort</Label>
                <Select value={config.effort} onValueChange={v => onUpdate({ effort: v as any })}>
                  <SelectTrigger className="bg-background border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="lite">Lite</SelectItem>
                    <SelectItem value="balanced">Balanced</SelectItem>
                    <SelectItem value="max">Max</SelectItem>
                    <SelectItem value="beast">Beast</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">Assurance</Label>
                <Select value={config.assurance} onValueChange={v => onUpdate({ assurance: v as any })}>
                  <SelectTrigger className="bg-background border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="draft">Draft</SelectItem>
                    <SelectItem value="polished">Polished</SelectItem>
                    <SelectItem value="conference-ready">Conference-ready</SelectItem>
                    <SelectItem value="submission">Submission</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-2xs text-muted-foreground">交付目标</Label>
              <Select value={config.deliveryGoal} onValueChange={value => onUpdate({ deliveryGoal: value as typeof config.deliveryGoal })}>
                <SelectTrigger className="bg-background border-border text-xs text-foreground"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="reviewable_draft">可审查草稿：保留科学问题与证据缺口</SelectItem>
                  <SelectItem value="submission_candidate">投稿候选：须通过科学审稿与审计</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-2xs text-muted-foreground">科研深度门禁</Label>
              <Select value={config.researchQualityMode} onValueChange={v => onUpdate({ researchQualityMode: v as WorkflowConfig['researchQualityMode'] })}>
                <SelectTrigger className="bg-background border-border text-xs text-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="rigorous">Rigorous - claim/evidence/证伪完整性检查</SelectItem>
                  <SelectItem value="standard">Standard - 基础结构与证据检查</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[10px] leading-4 text-muted-foreground">
                Rigorous 会阻止只有文件、没有科学假设与证据设计的节点通过。
              </p>
            </div>

            {/* Domain, study design, venue, and execution target */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">研究领域</Label>
                <Select value={config.researchFamily} onValueChange={value => onUpdate({ researchFamily: value as WorkflowConfig['researchFamily'] })}>
                  <SelectTrigger className="bg-background border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">自动识别（推荐）</SelectItem>
                    <SelectItem value="machine_learning">机器学习 / 深度学习</SelectItem>
                    <SelectItem value="computer_systems">计算机系统 / 软件 / 安全 / HCI</SelectItem>
                    <SelectItem value="computational_biology">生信 / 计算生物学</SelectItem>
                    <SelectItem value="clinical_biomedical">临床 / 生物医学</SelectItem>
                    <SelectItem value="experimental_natural_science">实验自然科学</SelectItem>
                    <SelectItem value="social_behavioral">社会 / 行为科学</SelectItem>
                    <SelectItem value="engineering_systems">工程 / 控制 / 机器人</SelectItem>
                    <SelectItem value="theoretical_formal">数学 / 理论 / 形式化</SelectItem>
                    <SelectItem value="qualitative_humanities">定性 / 人文 / 混合研究</SelectItem>
                    <SelectItem value="generic_quantitative">通用定量研究</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">研究设计</Label>
                <Select value={config.studyArchetype} onValueChange={value => onUpdate({ studyArchetype: value as WorkflowConfig['studyArchetype'] })}>
                  <SelectTrigger className="bg-background border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">自动识别（推荐）</SelectItem>
                    <SelectItem value="algorithm_benchmark">算法与基准实验</SelectItem>
                    <SelectItem value="systems_testbed">系统测试床</SelectItem>
                    <SelectItem value="observational_cohort">观察性 / 队列研究</SelectItem>
                    <SelectItem value="diagnostic_prognostic">诊断 / 预后研究</SelectItem>
                    <SelectItem value="intervention_trial">干预 / 随机试验</SelectItem>
                    <SelectItem value="omics_discovery">组学发现研究</SelectItem>
                    <SelectItem value="controlled_experiment">受控实验</SelectItem>
                    <SelectItem value="simulation_modeling">仿真与数值建模</SelectItem>
                    <SelectItem value="formal_theory">形式理论 / 证明</SelectItem>
                    <SelectItem value="qualitative_mixed">定性 / 混合方法</SelectItem>
                    <SelectItem value="generic_empirical">通用实证研究</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <p className="col-span-2 text-[10px] leading-4 text-muted-foreground">
                自动识别会结合研究问题、选定 Idea、实验计划和投稿目标；手动选择会锁定后续图表、统计和写作契约。
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3">
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">目标期刊 / 会议</Label>
                <Input
                  value={config.venue}
                  list="merak-venue-suggestions"
                  placeholder="如 Nature Methods、Bioinformatics、ICLR、IEEE TSE"
                  className="bg-background border-border text-xs text-foreground"
                  onChange={event => onUpdate({ venue: event.target.value })}
                  onBlur={event => {
                    const venue = event.target.value.trim() || 'Unspecified'
                    onUpdate({ venue, targetPages: venuePageLimits[venue] || config.targetPages })
                  }}
                />
                <datalist id="merak-venue-suggestions">
                  {[
                    'ICLR', 'NeurIPS', 'ICML', 'CVPR', 'ACL', 'AAAI',
                    'Nature', 'Nature Methods', 'Nature Biotechnology',
                    'Science', 'Cell', 'Bioinformatics', 'Genome Biology',
                    'JAMA', 'The Lancet', 'IEEE TPAMI', 'IEEE TSE',
                    'ACM CHI', 'USENIX Security', 'ICSE', 'Physical Review Letters',
                  ].map(venue => <option key={venue} value={venue} />)}
                </datalist>
                <div className="pt-1 space-y-1">
                  <Label className="text-2xs text-muted-foreground">
                    官方 TeX 模板（可选）
                  </Label>
                  <div className="space-y-1">
                    <Input
                      value={config.venueTemplatePath}
                      placeholder="选择 .tex/.cls/.sty/.zip 或模板目录"
                      className="h-8 w-full min-w-0 bg-background border-border text-xs text-foreground"
                      onChange={event => onUpdate({ venueTemplatePath: event.target.value })}
                    />
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        type="button"
                        variant="secondary"
                        size="icon"
                        className="h-7 w-7 shrink-0"
                        title="选择模板文件"
                        onClick={async () => {
                          const path = await window.merakIDE?.fs.openFile([
                            { name: 'LaTeX template', extensions: ['tex', 'cls', 'sty', 'zip'] },
                            { name: 'All files', extensions: ['*'] },
                          ])
                          if (path) onUpdate({ venueTemplatePath: path })
                        }}
                      >
                        <FileText size={13} />
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        size="icon"
                        className="h-7 w-7 shrink-0"
                        title="选择模板目录"
                        onClick={async () => {
                          const path = await window.merakIDE?.fs.openFolder()
                          if (path) onUpdate({ venueTemplatePath: path })
                        }}
                      >
                        <Folder size={13} />
                      </Button>
                      {config.venueTemplatePath && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 shrink-0 text-muted-foreground"
                          title="清除自定义模板"
                          onClick={() => onUpdate({ venueTemplatePath: '' })}
                        >
                          <XCircle size={13} />
                        </Button>
                      )}
                    </div>
                  </div>
                  <p className="text-[10px] leading-4 text-muted-foreground">
                    提供后将以该模板的 document class、前导区和依赖资产为准；留空时按投稿目标与研究领域自动选择。
                  </p>
                </div>
              </div>

            </div>
            <div className="grid grid-cols-2 gap-3 border-t border-border/70 pt-3">
              <div className="space-y-1">
                <Label htmlFor="workflow-target-pages" className="text-2xs text-muted-foreground">建议 PDF 页数</Label>
                <Input
                  id="workflow-target-pages"
                  type="number"
                  value={targetPagesDraft}
                  min={4}
                  max={50}
                  step={1}
                  aria-label="建议 PDF 页数"
                  onChange={event => {
                    const draft = event.target.value
                    setTargetPagesDraft(draft)
                    if (!draft.trim()) return
                    const value = Number(draft)
                    if (Number.isFinite(value)) onUpdate({ targetPages: value })
                  }}
                  onBlur={() => {
                    const parsed = Number(targetPagesDraft)
                    const value = targetPagesDraft.trim() && Number.isFinite(parsed)
                      ? Math.max(4, Math.min(50, Math.round(parsed)))
                      : 9
                    setTargetPagesDraft(String(value))
                    onUpdate({ targetPages: value })
                  }}
                  className="h-7 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="workflow-page-tolerance" className="text-2xs text-muted-foreground">建议浮动（页）</Label>
                <Input
                  id="workflow-page-tolerance"
                  type="number"
                  value={targetPageToleranceDraft}
                  min={0}
                  max={5}
                  step={1}
                  aria-label="建议页数浮动"
                  onChange={event => {
                    const draft = event.target.value
                    setTargetPageToleranceDraft(draft)
                    if (!draft.trim()) return
                    const value = Number(draft)
                    if (Number.isFinite(value)) onUpdate({ targetPageTolerance: value })
                  }}
                  onBlur={() => {
                    const parsed = Number(targetPageToleranceDraft)
                    const value = targetPageToleranceDraft.trim() && Number.isFinite(parsed)
                      ? Math.max(0, Math.min(5, Math.round(parsed)))
                      : 0
                    setTargetPageToleranceDraft(String(value))
                    onUpdate({ targetPageTolerance: value })
                  }}
                  className="h-7 text-xs"
                />
              </div>
              <p className="col-span-2 text-[10px] leading-4 text-muted-foreground">
                页数仅用于写作规划。偏离建议范围会记录提醒，但不会阻断论文或通过改字号、边距、虚构结果强行凑页数。
              </p>
            </div>

            {/* 实验运行控制 */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-2xs text-muted-foreground">运行真实实验</Label>
                <Switch
                  id="run-experiment"
                  checked={config.runExperiment}
                  onCheckedChange={value => onUpdate(value
                    ? {
                        runExperiment: true,
                        nonExperimentEvidenceMode: 'design_only',
                        gpu: config.gpu === 'none' ? 'local' : config.gpu,
                      }
                    : {
                        runExperiment: false,
                        nonExperimentEvidenceMode: 'design_only',
                        gpu: 'none',
                        sshServer: '',
                        gpuInfo: '',
                        wandb: false,
                      }
                  )}
                />
              </div>
              {!experimentExecutionEnabled && (
                <p className="text-2xs text-muted-foreground">
                  {!experimentNodeSelected ? '实验部署节点未选择，当前流程不会执行真实实验' : '生成并检查代码，但不实际运行训练'}
                </p>
              )}
              <div className="space-y-1.5 rounded-md border border-border/70 bg-muted/30 p-2">
                <div>
                  <Label className="text-2xs text-muted-foreground">无真实实验结果轨道</Label>
                  {config.runExperiment && (
                    <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
                      当前正在使用真实实验；选择下方任一轨道会自动关闭真实实验和 GPU 配置。
                    </p>
                  )}
                </div>
                <Select
                  value={config.runExperiment ? 'run_experiment' : config.nonExperimentEvidenceMode}
                  onValueChange={value => onUpdate({
                    runExperiment: false,
                    nonExperimentEvidenceMode: value as WorkflowConfig['nonExperimentEvidenceMode'],
                    gpu: 'none',
                    sshServer: '',
                    gpuInfo: '',
                    wandb: false,
                  })}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {config.runExperiment && (
                      <SelectItem value="run_experiment" disabled>运行真实实验（当前）</SelectItem>
                    )}
                    <SelectItem value="design_only" disabled={submissionAssurance}>仅研究设计</SelectItem>
                    <SelectItem value="synthetic_preview">生成完整仿真研究论文</SelectItem>
                    <SelectItem value="existing_results">使用已有真实结果</SelectItem>
                    <SelectItem value="secondary_analysis">公开结果二次分析</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[10px] leading-4 text-muted-foreground">
                  {!config.runExperiment && config.nonExperimentEvidenceMode === 'synthetic_preview'
                    ? '深度学习研究会生成完整仿真指标、主对比与消融表、鲁棒性/敏感性表、训练或收敛曲线及结果分析图，并完成全文写作、审稿和编译；标题、摘要、科学章节和图表按完整论文正常呈现，仅在结论之后、参考文献之前保留一段统一说明，不加水印或重复警示。'
                    : !config.runExperiment && config.nonExperimentEvidenceMode === 'existing_results'
                      ? '仅接纳有运行事件和哈希证明的现有指标文件。'
                      : !config.runExperiment && config.nonExperimentEvidenceMode === 'secondary_analysis'
                        ? '要求公开来源、引用和文件哈希齐全；缺少来源时不会升级为科研证据。'
                        : config.runExperiment
                          ? '该选项当前未启用；真实实验完成后只接纳可追溯的运行结果。'
                          : '只生成方法、研究设置和结果 schema，不生成定量结论。'}
                </p>
                {submissionAssurance && !config.runExperiment && config.nonExperimentEvidenceMode === 'synthetic_preview' && (
                  <div className="flex gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-2.5 py-2 text-[10px] leading-4 text-amber-700 dark:text-amber-300">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      投稿级设置会生成完整仿真研究论文；平台仍将仿真证据与真实运行证据隔离，不会自动授予 submission-ready 状态。
                    </span>
                  </div>
                )}
                {submissionAssurance && !config.runExperiment && config.nonExperimentEvidenceMode === 'design_only' && (
                  <div className="flex gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-2.5 py-2 text-[10px] leading-4 text-amber-700 dark:text-amber-300">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      投稿级设置不能只使用研究设计。请选择完整仿真结果稿、可验证结果导入，或运行真实实验。
                    </span>
                  </div>
                )}
              </div>
              <div className="space-y-1.5 rounded-md border border-border/70 bg-muted/20 p-2">
                <Label className="text-2xs text-muted-foreground">科研插图自动规划</Label>
                <p className="text-[10px] leading-4 text-muted-foreground">
                  系统会逐图读取方法合同、实现代码和实验语义：定量图使用 Matplotlib，简单评估流程使用 Mermaid，结构化模型图使用 FigureSpec，复杂多分支架构使用 Draw.io；不再要求用户选择统一绘图模式。
                </p>
                {!experimentExecutionEnabled && !importedEvidenceMode && (
                  <p className="text-[10px] leading-4 text-amber-600 dark:text-amber-400">
                    {!config.runExperiment && config.nonExperimentEvidenceMode === 'synthetic_preview'
                      ? '当前为仿真研究轨道：Phase 2a 生成完整定量图表，Experimental Setup 仅披露一次基准来源，图题和表题保持正常科研样式；Phase 2b 继续生成方法/架构插图。'
                      : '当前没有真实实验指标：Phase 2a /paper-figure 将跳过数据图，Phase 2b 仍由系统按科研语义自动规划。'}
                  </p>
                )}
              </div>
              {experimentExecutionEnabled && (
                <>
                  <div className="space-y-2 rounded-md border border-border/70 bg-muted/20 p-2.5">
                    <div>
                      <Label className="text-2xs text-muted-foreground">实验资源与部署</Label>
                      <p className="text-[10px] leading-4 text-muted-foreground">
                        仅在实际运行实验时选择计算目标；远程平台必须先通过连接测试。
                      </p>
                    </div>
                    <Select
                      value={config.gpu}
                      onValueChange={value => onUpdate({
                        gpu: value as WorkflowConfig['gpu'],
                        sshServer: value === 'remote' ? config.sshServer : '',
                      })}
                    >
                      <SelectTrigger className="bg-background border-border text-xs text-foreground">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="local">
                          <span className="flex items-center gap-2"><Cpu size={13} />本地 GPU</span>
                        </SelectItem>
                        <SelectItem value="remote" disabled={verifiedSshServers.length === 0}>
                          <span className="flex items-center gap-2">
                            <Server size={13} />
                            远程 SSH GPU
                            <span className="text-muted-foreground">
                              （{sshServers.length === 0 ? '未配置' : verifiedSshServers.length === 0 ? '待测试' : `${verifiedSshServers.length} 台可用`}）
                            </span>
                          </span>
                        </SelectItem>
                        <SelectItem value="vast" disabled={integrationStatus.vastai?.verified !== true}>
                          Vast.ai（{integrationStatus.vastai ? verificationLabel(integrationStatus.vastai, integrationStatus.vastai.configured) : '检查中'}）
                        </SelectItem>
                        <SelectItem value="modal" disabled={integrationStatus.modal?.verified !== true}>
                          Modal（{integrationStatus.modal ? verificationLabel(integrationStatus.modal, integrationStatus.modal.configured) : '检查中'}）
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-2xs text-muted-foreground">GPU 环境描述</Label>
                    <Input
                      value={config.gpuInfo}
                      onChange={e => onUpdate({ gpuInfo: e.target.value })}
                      placeholder="如: RTX 4090 24GB / 4x A100 80GB"
                      className="h-7 text-xs"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-2xs text-muted-foreground">批准后重试上限</Label>
                      <Input
                        type="number"
                        value={config.maxRetries}
                        onChange={e => onUpdate({ maxRetries: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })}
                        min={0}
                        max={10}
                        className="h-7 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-2xs text-muted-foreground">超时（分钟）</Label>
                      <Input
                        type="number"
                        value={config.experimentTimeoutMinutes}
                        onChange={e => onUpdate({ experimentTimeoutMinutes: Math.max(1, Math.min(10080, Number(e.target.value) || 360)) })}
                        min={1}
                        max={10080}
                        className="h-7 text-xs"
                      />
                    </div>
                  </div>
                  <p className="text-[10px] leading-4 text-muted-foreground">
                    系统不会自动改代码或 batch size。每次重试都需要先查看诊断并批准一个未使用的调整提案。
                  </p>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <Label className="text-2xs text-muted-foreground">异常自动止损</Label>
                      <p className="text-[10px] leading-4 text-muted-foreground">NaN/Inf、OOM、loss 异常或日志停滞时先保存证据再停止</p>
                    </div>
                    <Switch
                      checked={config.autoStopOnAnomaly}
                      onCheckedChange={value => onUpdate({ autoStopOnAnomaly: value })}
                    />
                  </div>
                  {config.gpu !== 'local' && (
                    <>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <Label className="text-2xs text-muted-foreground">目标 GPU</Label>
                          <Input
                            value={config.remoteGpuType}
                            onChange={e => onUpdate({ remoteGpuType: e.target.value })}
                            placeholder="A100"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-2xs text-muted-foreground">单次预算（USD）</Label>
                          <Input
                            type="number"
                            value={config.maxRemoteCostUsd}
                            onChange={e => onUpdate({ maxRemoteCostUsd: Math.max(0.1, Number(e.target.value) || 10) })}
                            min={0.1}
                            step={0.5}
                            className="h-7 text-xs"
                          />
                        </div>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <Label className="text-2xs text-muted-foreground">同步项目数据</Label>
                          <p className="text-[10px] leading-4 text-muted-foreground">默认仅同步代码与配置；数据集建议预置在远端</p>
                        </div>
                        <Switch
                          checked={config.syncProjectData}
                          onCheckedChange={value => onUpdate({ syncProjectData: value })}
                        />
                      </div>
                    </>
                  )}
                  {config.gpu === 'vast' && (
                    <div className="space-y-2 border-t border-border/70 pt-2">
                      <div className="grid grid-cols-2 gap-2">
                        <div className="space-y-1">
                          <Label className="text-2xs text-muted-foreground">最高时价（USD/h）</Label>
                          <Input
                            type="number"
                            value={config.vastMaxHourlyUsd}
                            onChange={e => onUpdate({ vastMaxHourlyUsd: Math.max(0.05, Number(e.target.value) || 2) })}
                            min={0.05}
                            step={0.1}
                            className="h-7 text-xs"
                          />
                        </div>
                        <div className="flex items-end justify-between gap-2 pb-1">
                          <Label className="text-2xs text-muted-foreground">完成后销毁实例</Label>
                          <Switch
                            checked={config.autoDestroyVast}
                            onCheckedChange={value => onUpdate({ autoDestroyVast: value })}
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Reviewer */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-2xs text-muted-foreground">审稿器</Label>
                <Select value={config.reviewerDifficulty} onValueChange={v => onUpdate({ reviewerDifficulty: v as any })}>
                  <SelectTrigger className="bg-background border-border text-xs text-foreground">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="hard">Hard</SelectItem>
                    <SelectItem value="nightmare">Nightmare</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>
  </>
}
