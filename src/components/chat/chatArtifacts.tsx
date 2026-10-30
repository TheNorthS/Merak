import { FileText, BookOpen, Code2, Presentation, BarChart3 } from 'lucide-react'
import { useWorkspaceStore, type OpenFile } from '../../stores/workspace'
import { API_BASE } from '../../config'
import { type AttachedFile, type ChatMode, type ChatSuggestion, type SuggestionContextKind, type AttachmentGroup } from './chatTypes'
import { shortLabel } from './chatModes'

export function makeBackendContextKey(projectPath?: string | null, mode: ChatMode = 'ask', activePath?: string | null) {
  return [projectPath || '', mode, normalizePathKey(activePath)].join('|')
}

export const RESEARCH_ARTIFACT_DIRS = ['paper', 'slides', 'experiments', 'figures', 'literature', 'ideas'] as const

export const RESEARCH_ARTIFACT_LABELS: Record<string, string> = {
  paper: '论文',
  slides: 'Slides',
  experiments: '实验',
  figures: '图表',
  literature: '文献',
  ideas: '想法',
}

export function getRelativeArtifactPath(filePath?: string | null, projectPath?: string | null) {
  if (!filePath) return ''
  const normalizedPath = filePath.replace(/\\/g, '/')
  const normalizedProject = projectPath?.replace(/\\/g, '/').replace(/\/$/, '')
  if (!normalizedProject) return normalizedPath.replace(/^\.\//, '')
  const pathLower = normalizedPath.toLowerCase()
  const projectLower = normalizedProject.toLowerCase()
  return pathLower.startsWith(`${projectLower}/`)
    ? normalizedPath.slice(normalizedProject.length + 1)
    : normalizedPath.replace(/^\.\//, '')
}

export function getResearchArtifactDir(filePath?: string | null, projectPath?: string | null) {
  const relativePath = getRelativeArtifactPath(filePath, projectPath)
  return RESEARCH_ARTIFACT_DIRS.find(dir => relativePath === dir || relativePath.startsWith(`${dir}/`)) ?? null
}

export function getArtifactLabel(dir?: string | null) {
  return dir ? RESEARCH_ARTIFACT_LABELS[dir] ?? dir : '研究产物'
}

export function normalizePathKey(filePath?: string | null) {
  return (filePath || '').replace(/\\/g, '/').toLowerCase()
}

export function isResearchArtifactPath(filePath?: string | null, projectPath?: string | null) {
  return getResearchArtifactDir(filePath, projectPath) !== null
}

export function formatArtifactPath(filePath?: string | null, projectPath?: string | null) {
  const relativePath = getRelativeArtifactPath(filePath, projectPath)
  return relativePath || filePath || ''
}

export function getSuggestionContext(filePath?: string | null, projectPath?: string | null): { kind: SuggestionContextKind; label: string; target: string } {
  if (!filePath) return { kind: 'project', label: '研究项目', target: '当前研究项目' }
  const artifactDir = getResearchArtifactDir(filePath, projectPath)
  const name = filePath.split(/[\\/]/).pop() || ''
  const pathLabel = formatArtifactPath(filePath, projectPath)
  if (name.endsWith('.tex') && artifactDir === 'slides') return { kind: 'slides', label: 'Slides', target: `当前 Slides（${pathLabel}）` }
  if (name.endsWith('.tex')) return { kind: 'paper', label: '论文', target: `当前论文（${pathLabel}）` }
  if ((name.endsWith('.py') || name.endsWith('.ipynb')) && artifactDir === 'experiments') return { kind: 'code', label: '实验代码', target: `当前实验代码（${pathLabel}）` }
  if (artifactDir === 'figures') return { kind: 'figure', label: '图表', target: `当前图表（${pathLabel}）` }
  return { kind: 'project', label: getArtifactLabel(artifactDir), target: `当前${getArtifactLabel(artifactDir)}（${pathLabel}）` }
}

export function getModeSuggestions(mode: ChatMode, filePath?: string | null, projectPath?: string | null): ChatSuggestion[] {
  const ctx = getSuggestionContext(filePath, projectPath)
  if (mode === 'ask') {
    if (ctx.kind === 'code') return [
      { label: '解释代码', prompt: `请解释${ctx.target}的输入、输出、训练流程和关键逻辑`, mode },
      { label: '解释配置', prompt: `请说明${ctx.target}依赖哪些配置、数据路径和命令行参数`, mode },
      { label: '梳理调用链', prompt: `请按执行顺序梳理${ctx.target}的函数调用链`, mode },
    ]
    return [
      { label: '解释当前', prompt: `请解释${ctx.target}的目标、结构、关键逻辑和下一步建议`, mode },
      { label: '总结要点', prompt: `请总结${ctx.target}目前最重要的结论和缺口`, mode },
      { label: '梳理任务', prompt: `请把${ctx.target}拆成可执行的后续任务清单`, mode },
    ]
  }
  if (mode === 'edit') return [
    { label: ctx.kind === 'code' ? '添加注释' : '润色当前', prompt: ctx.kind === 'code' ? `请为${ctx.target}添加清晰注释，说明关键逻辑` : `请润色${ctx.target}，提升清晰度并保持原意不变`, mode },
    { label: '最小修复', prompt: `请用最小必要改动修复或改进${ctx.target}，并生成待审批变更`, mode },
    { label: '统一风格', prompt: `请统一${ctx.target}的术语、命名和表达风格`, mode },
  ]
  if (mode === 'review') return [
    { label: '审查风险', prompt: `请严格审查${ctx.target}的科研风险、逻辑漏洞和证据缺口`, mode },
    { label: '复现检查', prompt: `请从可复现性、数据泄漏、指标计算和 claim 一致性角度检查${ctx.target}`, mode },
    { label: '提交清单', prompt: `请列出${ctx.target}提交前必须修正或确认的问题`, mode },
  ]
  if (mode === 'write') return [
    { label: '起草段落', prompt: `请基于${ctx.target}起草一段可放入论文或报告的说明`, mode },
    { label: '写实验说明', prompt: `请把${ctx.target}整理成实验设置、实现细节和结果描述`, mode },
    { label: '写讲稿', prompt: `请基于${ctx.target}生成简洁的汇报讲稿或 speaker notes`, mode },
  ]
  return [
    { label: '图表方案', prompt: `请为${ctx.target}设计一张适合论文的核心图表，并说明视觉编码`, mode },
    { label: '结果图', prompt: `请规划一张支撑${ctx.target}主要 claim 的结果对比图`, mode },
    { label: '图注草稿', prompt: `请为${ctx.target}相关图表写一版清晰 caption`, mode },
  ]
}

export function getComposerSuggestions(mode: ChatMode, filePath?: string | null, projectPath?: string | null): ChatSuggestion[] {
  return getModeSuggestions(mode, filePath, projectPath)
}

export function getAttachableGroups(
  openFiles: OpenFile[],
  attachedFiles: AttachedFile[],
  activeFile: OpenFile | null,
  projectPath?: string | null,
): AttachmentGroup[] {
  const attachedKeys = new Set(attachedFiles.map(file => normalizePathKey(file.path)))
  const activeKey = normalizePathKey(activeFile?.path)
  const seen = new Set<string>()
  const files = openFiles
    .filter(file => isResearchArtifactPath(file.path, projectPath))
    .map(file => ({ file, dir: getResearchArtifactDir(file.path, projectPath) || 'ideas' }))
    .filter(({ file }) => {
      const key = normalizePathKey(file.path)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .map(({ file, dir }) => ({
      path: file.path,
      name: file.name,
      dir,
      isCurrent: normalizePathKey(file.path) === activeKey,
      isAttached: attachedKeys.has(normalizePathKey(file.path)),
      isDirty: file.isDirty,
    }))
    .sort((a, b) => {
      if (a.isCurrent !== b.isCurrent) return a.isCurrent ? -1 : 1
      const aDir = RESEARCH_ARTIFACT_DIRS.indexOf(a.dir as typeof RESEARCH_ARTIFACT_DIRS[number])
      const bDir = RESEARCH_ARTIFACT_DIRS.indexOf(b.dir as typeof RESEARCH_ARTIFACT_DIRS[number])
      if (aDir !== bDir) return aDir - bDir
      return formatArtifactPath(a.path, projectPath).localeCompare(formatArtifactPath(b.path, projectPath))
    })

  return RESEARCH_ARTIFACT_DIRS
    .map(dir => ({ dir, label: getArtifactLabel(dir), files: files.filter(file => file.dir === dir) }))
    .filter(group => group.files.length > 0)
}

export function inferPromptMode(text: string, fallback: ChatMode): ChatMode {
  const value = text.trim().toLowerCase()
  if (!value) return fallback
  if (/(画图|图表|可视化|流程图|架构图|figure|plot|chart|diagram)/i.test(value)) return 'figure'
  if (/(审稿|审查|review|评估|检查引用|一致性|风险|漏洞|reproducibility|soundness)/i.test(value)) return 'review'
  if (/(起草|撰写|续写|补充|生成.*(论文|摘要|相关工作|slides|幻灯片|报告)|write|draft)/i.test(value)) return 'write'
  if (/(调高|调低|提高|降低|增大|减小|batch[_ -]?size|learning[_ -]?rate|\blr\b|epoch|num[_ -]?workers|预训练|pretrain|pre-training|配置|config|yaml|yml)/i.test(value)) return 'edit'
  if (/(修改|改写|改进|修复|重构|替换|删除|插入|添加注释|优化.*(代码|实现|函数)|edit|fix|refactor)/i.test(value)) return 'edit'
  return fallback
}

export function modelStatusLabel(provider?: string, model?: string) {
  if (!provider) return ''
  return model ? `${shortLabel(provider)} · ${model}` : shortLabel(provider)
}

export function formatAgentStatus(data: unknown) {
  if (!data || typeof data !== 'object') return typeof data === 'string' ? data : 'Working'
  const status = data as { status?: string; provider?: string; model?: string; from?: string; to?: string; elapsed?: number; attempt?: number }
  if (status.status === 'switching_provider' && status.to) return `Switching · ${modelStatusLabel(status.to, status.model)}`
  if (status.status === 'retrying_provider' && status.provider) return `Retrying · ${modelStatusLabel(status.provider, status.model)} · #${status.attempt || 2}`
  if (status.status === 'waiting_model' && status.provider) return `Waiting · ${modelStatusLabel(status.provider, status.model)} · ${status.elapsed || 0}s`
  if (status.status === 'stream_closed_after_silence' && status.provider) return `Finishing · ${modelStatusLabel(status.provider, status.model)}`
  if (status.status === 'thinking' && status.provider) return `Thinking · ${modelStatusLabel(status.provider, status.model)}`
  if (status.status === 'tool_calling') return 'Using tools'
  return status.status || 'Working'
}

export function formatChatError(data: unknown) {
  const raw = typeof data === 'string' ? data : JSON.stringify(data)
  const lower = raw.toLowerCase()
  if (lower.includes('no available accounts')) {
    return '当前选中的模型路由返回 503：账号池暂无可用账号。Auto 模式会尝试切到其它已配置模型；如果你手动指定了模型，请切回 Auto 或换一个模型后重试。'
  }
  if (lower.includes('503') || lower.includes('service temporarily unavailable') || lower.includes('service unavailable')) {
    return '当前模型路由返回 503：上游服务临时不可用。你的 OpenAI 兼容池可能仍然可用，Chat 会在 Auto 模式下尝试其它 route。'
  }
  if (lower.includes('timeout') || lower.includes('timed out') || lower.includes('请求超时')) {
    return '模型请求超时。会话已保留，可以重试、切换模型，或把问题拆短后再发送。'
  }
  return raw
}

export async function readTextFileForRefresh(path: string): Promise<string> {
  if (window.merakIDE?.fs?.readFile) return window.merakIDE.fs.readFile(path)
  const res = await fetch(API_BASE + '/api/files/read?path=' + encodeURIComponent(path))
  if (!res.ok) throw new Error('Read failed: ' + res.status)
  const data = await res.json() as { content?: string }
  return data.content ?? ''
}

export async function refreshOpenFileFromDisk(path?: string) {
  if (!path) return
  const content = await readTextFileForRefresh(path)
  useWorkspaceStore.getState().replaceFileContent(path, content)
}

export function ArtifactIcon({ type }: { type: string }) {
  if (type === 'paper') return <BookOpen size={9} />
  if (type === 'slides') return <Presentation size={9} />
  if (type === 'experiments') return <Code2 size={9} />
  if (type === 'figures') return <BarChart3 size={9} />
  return <FileText size={9} />
}
