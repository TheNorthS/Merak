import type { RevisionDecisionBrief } from './workflowViewModels'


export const CHECKPOINT_GUIDANCE: Record<string, { title: string; detail: string }> = {
  'exp-design': {
    title: '确认研究 Idea 和实验边界',
    detail: '重点检查核心假设、反证条件、数据范围和计划中的强基线是否符合你的整体研究方向。',
  },
  'exp-run': {
    title: '确认是否投入实验资源',
    detail: '重点检查代码审查、数据隔离、运行预算、远程目标和停止条件；继续后可能开始消耗 GPU 与费用。',
  },
  paper: {
    title: '确认论文主张与叙事',
    detail: '重点检查主 claim 是否超出已有证据，以及论文结构是否仍围绕你确认的研究 Idea。',
  },
}

const humanizeUnstructuredRevisionIssue = (issue: string): string => {
  const clean = String(issue || '').replace(/\s+/g, ' ').trim()
  const symbolMatch = clean.match(/^([^:]+): missing declared symbol\(s\) in ([^:]+): (.+)$/i)
  if (symbolMatch) {
    return `检查项 ${symbolMatch[1]} 声明 ${symbolMatch[2]} 应提供 ${symbolMatch[3]}，但静态校验没有识别到这些可执行定义。请核对代码名称、定义位置和方法契约。`
  }
  const keyMatch = clean.match(/^([^:]+): missing config key\(s\) in ([^:]+): (.+)$/i)
  if (keyMatch) {
    return `检查项 ${keyMatch[1]} 需要 ${keyMatch[2]} 中的配置 ${keyMatch[3]}，但当前解析结果没有找到。`
  }
  const lowered = clean.toLowerCase()
  const translations: Array<[string[], string]> = [
    [['research depth contract failed'], '当前产物虽然可能已经生成文件，但核心假设、实现证据或证伪设计仍不完整，暂时不能支撑后续实验。'],
    [['no current metric file', 'no machine-readable scientific metric'], '系统没有找到由成功实验运行产生并可追溯的指标文件；当前不能生成或引用结果型图表。'],
    [['at least two comparable methods'], '现有结果没有在同一数据划分和指标下覆盖至少两个可比较方法，无法形成有效的主比较。'],
    [['missing or empty', 'file not found'], '当前阶段要求的标准研究产物缺失或为空，需要先生成或修复对应文件。'],
    [['not referenced in prose'], '论文中已经插入图表，但正文没有引用并解释它；图表目前只是附加物，尚未参与科研论证。'],
  ]
  const translated = translations.find(([needles]) => needles.some(value => lowered.includes(value)))
  return translated?.[1]
    || (clean ? `独立验收仍发现一项未解决问题：${clean}` : '当前节点尚未通过独立验收。')
}

const splitUnstructuredRevisionIssues = (issues: string[]): string[] => issues.flatMap(issue => {
  const clean = String(issue || '').replace(/\s+/g, ' ').trim()
  if (!clean) return []
  return clean
    .split(/[；;]\s+(?=(?:[A-Z]\d+:|missing|need|no |executed|planned|paper|figure|scientific))/i)
    .map(item => item.trim())
    .filter(Boolean)
})

interface RevisionBriefContext {
  nodeId: string
  nodeName: string
  round: number
  maxRounds: number
  summary: string
  issues: string[]
}

export const normalizeRevisionDecisionBrief = (
  raw: unknown,
  context: RevisionBriefContext,
): RevisionDecisionBrief => {
  const source = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const strings = (value: unknown): string[] => Array.isArray(value)
    ? value.map(item => String(item).trim()).filter(Boolean) : []
  const impacts: Record<string, string> = {
    idea: '研究问题或机制未确认时继续，后续实验可能偏离原始 Idea。',
    novelty: '新颖性证据未闭合时继续实现，核心贡献可能与已有工作重复。',
    'exp-design': '实现、配置和方法契约不一致时，后续基线、消融和统计结果无法可靠归因到选定 Idea。',
    'exp-run': '执行证据不完整时，实验结果可能不可复现，也不能安全用于论文。',
    results: '结果没有绑定运行证据时，当前数字不能支持科研结论。',
    figure: '图表没有绑定真实产物时，读者无法追溯证据来源。',
    narrative: '叙事超出证据范围时，论文主张会被不合理放大。',
    paper: '论文 claim、引用或结果不一致时，稿件形式完整也不代表科研上可提交。',
  }
  const technical = splitUnstructuredRevisionIssues(strings(source.technical_details))
  const contextual = splitUnstructuredRevisionIssues(context.issues)
  const fallback = contextual.length ? contextual
    : technical.length ? technical : context.summary ? [context.summary] : []
  const plain = strings(source.plain_issues)
  return {
    headline: String(source.headline || `${context.nodeName}仍有关键问题未通过验收`),
    whatHappened: String(source.what_happened || `系统已进行 ${context.round} 轮修订和重新验收，达到 ${context.maxRounds} 轮上限后仍未通过。`),
    researchImpact: String(source.research_impact || impacts[context.nodeId] || '如果继续执行，下游结论将缺少可靠、可追溯的科研证据。'),
    plainIssues: plain.length ? plain : fallback.length
      ? fallback.map(humanizeUnstructuredRevisionIssue).slice(0, 8)
      : ['当前节点尚未通过独立验收，详细原因需要结合质量报告进一步确认。'],
    systemActions: strings(source.system_actions).length
      ? strings(source.system_actions)
      : [`已记录 ${context.round} 轮修订与最新验收结果。`, '已停止相同问题上的自动循环，并保留恢复断点。'],
    recommendedActions: strings(source.recommended_actions).length
      ? strings(source.recommended_actions)
      : ['修改对应标准产物后重新验收。', '提交正确文件、符号或科研约束，让智能体定向修订。', '暂时收起并手动检查；质量门不会放行后续节点。'],
    decisionQuestion: String(source.decision_question || '请选择先修改产物重新验收，或提交明确反馈进行一次定向修订。'),
    protectedState: String(source.protected_state || '当前节点仍未通过；系统没有跳过质量门，也没有放行依赖它的后续节点。'),
    technicalDetails: technical.length ? technical : fallback,
  }
}
