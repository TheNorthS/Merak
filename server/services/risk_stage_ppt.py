"""Collect deterministic ppt findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib
import re
from .node_risk_audit import _has_trusted_empirical_evidence, _workflow_evidence_mode
from .risk_artifact_support import _finding, _has_content, _json, _missing, _relative, _source_bundle_sha256, _text
from .risk_constants import PENDING_RE
from .slide_scope_validation import has_bounded_slide_scope, bind_slide_repair_owners
from .risk_validator_support import _bib_entries, _citation_keys, _has_unbounded_supported_claim, _latex_graphic_exists, _latex_graphics, _newest_mtime, _placeholder_excerpt
from .simulation_policy import FORBIDDEN_RENDERED_SIMULATION_LABELS, visible_watermark_commands

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _simulation_portfolio_findings(root: Path, text: str, plan: dict) -> list[dict[str, Any]]:
    """Keep the required contribution portfolio independent of current qualification."""
    from .slide_figures import required_synthetic_figure_ids
    from .scientific_slides import scientific_slide_service

    try:
        expected = set(required_synthetic_figure_ids(root))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        return [_finding(
            'PPT-SIM-004', 'blocker', 'figure_binding',
            f'Simulation slide contribution portfolio is unavailable: {error}',
            '演示必需图集缺少当前冻结贡献或完整、哈希有效的七角色证据包。',
            ['ideas/SELECTED_IDEA.json', 'experiments/results/simulated/SIMULATION_MANIFEST.json'],
            'Repair the declared scientific portfolio or its evidence at the producer; never lower the required set.',
        )]
    qualified = {str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or '')
                 for item in scientific_slide_service.qualified_synthetic_figures(root)}
    selected = {str(item) for item in plan.get('selected_figures') or [] if str(item).strip()}
    referenced = set(scientific_slide_service.referenced_figure_ids(root, text))
    missing = sorted(expected - qualified | expected - selected | expected - referenced)
    if not missing:
        return []
    return [_finding(
        'PPT-SIM-001', 'blocker', 'evidence_state',
        'Simulation deck omits required contribution-bound result figures: ' + ', '.join(missing),
        '演示没有完整引用当前贡献必需且哈希有效的结果图：' + '、'.join(missing),
        ['slides/main.tex', 'slides/SLIDE_PLAN.json', 'figures/FIGURE_MANIFEST.json',
         'experiments/results/simulated/SIMULATION_MANIFEST.json'],
        'Include every required contribution figure while preserving the complete seven-role evidence bundle.',
    )]

def _rule_1(options: Any, root: Any) -> dict[str, Any]:
    tex = root / 'slides' / 'main.tex'
    pdf = root / 'slides' / 'main.pdf'
    if not _has_content(tex):
        raise _EarlyReturn([_missing('PPT-TEX-001', 'slides/main.tex')])
    findings: list[dict[str, Any]] = []
    text = _text(tex)
    evidence_mode = _workflow_evidence_mode(options)
    simulation_mode = evidence_mode == 'synthetic_preview'
    source_hash, source_bundle_paths = _source_bundle_sha256(root / 'slides')
    slide_build, build_error = _json(root / 'slides' / 'SLIDE_BUILD.json')
    compile_record = slide_build.get('compile') or {} if isinstance(slide_build, dict) else {}
    has_source_hash = bool(str(compile_record.get('source_bundle_sha256') or '').strip())
    if '\\documentclass' not in text or 'beamer' not in text.casefold():
        findings.append(_finding('PPT-TEX-002', 'blocker', 'slides', 'slides/main.tex is not a complete Beamer document.', 'slides/main.tex 不是完整的 Beamer 文档。', ['slides/main.tex'], 'Generate a complete, compilable Beamer source.'))
    frame_count = len(re.findall('\\\\begin\\{frame\\}', text))
    if frame_count < 6:
        findings.append(_finding('PPT-DEPTH-001', 'warning', 'slides', f'Slide deck contains only {frame_count} frame(s).', f'演示文稿只有 {frame_count} 页，可能无法完整覆盖问题、方法、证据、局限和结论。', ['slides/main.tex'], 'Cover the research argument rather than padding to a fixed count.'))
    dense_frames: list[str] = []
    for index, frame in enumerate(re.findall('\\\\begin\\{frame\\}(.*?)\\\\end\\{frame\\}', text, re.IGNORECASE | re.DOTALL), start=1):
        without_comments = re.sub('(?m)%.*$', ' ', frame)
        visible = re.sub('\\\\[A-Za-z@]+\\*?(?:\\[[^\\]]*\\])?', ' ', without_comments)
        visible = re.sub('[{}$\\\\]', ' ', visible)
        word_count = len(re.findall('[A-Za-z0-9][A-Za-z0-9_-]*|[\\u4e00-\\u9fff]', visible))
        item_count = len(re.findall('\\\\item\\b', frame))
        if word_count > 120 or item_count > 10:
            dense_frames.append(f'frame {index} ({word_count} words/chars, {item_count} items)')
    if dense_frames:
        findings.append(_finding('PPT-LEGIBILITY-001', 'warning', 'layout', 'Slide frames are too text-dense for presentation use: ' + '; '.join(dense_frames[:6]), '部分演示页文字或条目过密，投影后难以阅读：' + '；'.join(dense_frames[:6]), ['slides/main.tex'], 'Split the scientific argument across frames and retain only evidence-critical text.'))
    if re.search('\\\\(?:tiny|scriptsize)\\b', text):
        findings.append(_finding('PPT-LEGIBILITY-002', 'warning', 'layout', 'Slides use tiny or scriptsize text, which may hide overcrowding.', '演示稿使用 tiny/scriptsize 微小字号，可能是在掩盖内容过载。', ['slides/main.tex'], 'Shorten or split the frame instead of shrinking evidence and labels.'))
    if not _has_content(pdf):
        findings.append(_missing('PPT-PDF-001', 'slides/main.pdf'))
    else:
        try:
            valid_pdf = pdf.read_bytes()[:5] == b'%PDF-'
        except OSError:
            valid_pdf = False
        if not valid_pdf:
            findings.append(_finding('PPT-PDF-002', 'blocker', 'slides', 'slides/main.pdf is not a valid PDF file.', 'slides/main.pdf 不是有效 PDF，演示稿没有真正编译完成。', ['slides/main.pdf'], 'Compile the Beamer source and retain the real PDF.'))
        elif not has_source_hash and pdf.stat().st_mtime + 1.0 < _newest_mtime(source_bundle_paths):
            findings.append(_finding('PPT-STALE-001', 'blocker', 'slides', 'Slide PDF is older than its TeX or referenced graphic bundle.', '演示 PDF 早于当前 TeX 或引用图片，是旧版本。', ['slides/main.pdf', *[_relative(root, path) for path in source_bundle_paths]], 'Recompile the current slide source and referenced figures.'))
    return {key: value for key, value in locals().items() if key in ['build_error', 'compile_record', 'dense_frames', 'evidence_mode', 'findings', 'frame', 'frame_count', 'has_source_hash', 'index', 'item_count', 'pdf', 'simulation_mode', 'slide_build', 'source_bundle_paths', 'source_hash', 'tex', 'text', 'valid_pdf', 'visible', 'without_comments', 'word_count']}

def _rule_2(build_error: Any, compile_record: Any, findings: Any, options: Any, pdf: Any, root: Any, simulation_mode: Any, slide_build: Any, source_hash: Any, tex: Any, text: Any) -> dict[str, Any]:
    if build_error or not isinstance(slide_build, dict):
        findings.append(_missing('PPT-BUILD-001', 'slides/SLIDE_BUILD.json'))
    elif _has_content(pdf):
        current_pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if not compile_record.get('success') or compile_record.get('source_bundle_sha256') != source_hash or compile_record.get('pdf_sha256') != current_pdf_hash:
            findings.append(_finding('PPT-BUILD-002', 'blocker', 'slides', 'SLIDE_BUILD.json is not hash-bound to the current source and PDF.', 'SLIDE_BUILD.json 与当前演示源文件/PDF 哈希不一致，无法确认预览就是最终版本。', ['slides/SLIDE_BUILD.json', 'slides/main.tex', 'slides/main.pdf'], 'Compile the current source and refresh SLIDE_BUILD.json.'))
    from .scientific_slides import scientific_slide_service
    slide_plan, plan_error = _json(root / 'slides' / 'SLIDE_PLAN.json')
    if plan_error or not isinstance(slide_plan, dict):
        generated_deck = 'MERAK_GENERATED_SLIDES' in text
        findings.append(_finding('PPT-PLAN-001', 'blocker' if generated_deck else 'warning', 'freshness', 'Slide source has no paper/research source-bundle record.', 'MERAK 生成的演示稿缺少论文/研究来源哈希，无法确认内容对应当前研究版本。' if generated_deck else '用户维护的演示稿没有论文/研究来源哈希；系统不会自动覆盖，但需要研究者确认内容新鲜度。', ['slides/SLIDE_PLAN.json', 'slides/main.tex'], 'Regenerate the MERAK deck and persist SLIDE_PLAN.json.' if generated_deck else 'Review the deck against the current paper or opt into MERAK source binding.'))
    else:
        current_plan_hash, _ = scientific_slide_service.source_bundle(root)
        current_tex_hash = hashlib.sha256(tex.read_bytes()).hexdigest()
        if slide_plan.get('source_bundle_sha256') != current_plan_hash or slide_plan.get('tex_sha256') != current_tex_hash:
            findings.append(_finding('PPT-SOURCE-001', 'blocker', 'freshness', 'Slide source is not bound to the current paper and research artifacts.', '演示稿没有绑定当前论文、冻结 Idea、方法、结果和图表版本，可能仍展示旧研究状态。', ['slides/SLIDE_PLAN.json', 'slides/main.tex', 'paper/main.tex'], 'Regenerate the MERAK slide source from the current accepted artifact bundle.'))
        if simulation_mode:
            findings.extend(_simulation_portfolio_findings(root, text, slide_plan))
    referenced_figure_ids = set(scientific_slide_service.referenced_figure_ids(root, text))
    selected_figure_ids = {str(item) for item in (slide_plan.get('selected_figures') if isinstance(slide_plan, dict) else []) or [] if str(item).strip()}
    if isinstance(slide_plan, dict) and selected_figure_ids != referenced_figure_ids:
        findings.append(_finding('PPT-FIG-002', 'blocker', 'figure_binding', 'SLIDE_PLAN.json does not match the manifest figures actually referenced by slides/main.tex.', 'SLIDE_PLAN.json 记录的科研图与 slides/main.tex 实际引用的图不一致，修复或换图后仍可能沿用旧绑定。', ['slides/main.tex', 'slides/SLIDE_PLAN.json', 'figures/FIGURE_MANIFEST.json'], 'Refresh the slide binding from the current TeX source and manifest before compiling.'))
    qualified_standard = scientific_slide_service.qualified_standard_figures(root)
    standard_by_id = {str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or ''): item for item in qualified_standard}
    referenced_standard_ids = referenced_figure_ids & set(standard_by_id)
    method_ids = {figure_id for figure_id, item in standard_by_id.items() if str((item.get('metadata') or {}).get('scientific_role') or '').casefold() in {'method', 'architecture', 'mechanism'}}
    result_ids = {figure_id for figure_id, item in standard_by_id.items() if str((item.get('metadata') or {}).get('scientific_role') or '').casefold() in {'result', 'ablation', 'robustness', 'analysis', 'qualitative', 'training_dynamics', 'error_analysis', 'calibration', 'efficiency'}}
    missing_scientific_roles: list[str] = []
    if qualified_standard and (not referenced_standard_ids):
        missing_scientific_roles.append('any qualified scientific figure')
    else:
        if method_ids and (not method_ids & referenced_standard_ids):
            missing_scientific_roles.append('method/mechanism figure')
        if _has_trusted_empirical_evidence(options) and result_ids and (not result_ids & referenced_standard_ids):
            missing_scientific_roles.append('result/ablation/robustness figure')
    if missing_scientific_roles:
        findings.append(_finding('PPT-FIG-003', 'blocker', 'scientific_coverage', 'Slide deck omits available, hash-qualified scientific visuals: ' + ', '.join(missing_scientific_roles), '演示稿没有实际引用已有且哈希有效的科研图：' + '、'.join(missing_scientific_roles), ['slides/main.tex', 'figures/FIGURE_MANIFEST.json'], 'Include the available method visual and, for empirical studies, at least one qualified result or analysis figure.'))
    if simulation_mode and not has_bounded_slide_scope(text):
        findings.append(_finding('PPT-SIM-002', 'blocker', 'evidence_state', 'Simulation deck does not bound its findings to the registered benchmark scope.', '仿真研究演示没有把结论限定在已注册的基准评估范围内。', ['slides/main.tex', 'paper/main.tex'], 'State the registered benchmark scope and keep every quantitative conclusion within it.'))
    return {key: value for key, value in locals().items() if key in ['_', 'current_pdf_hash', 'current_plan_hash', 'current_tex_hash', 'generated_deck', 'method_ids', 'missing_scientific_roles', 'plan_error', 'qualified_standard', 'referenced_figure_ids', 'referenced_standard_ids', 'result_ids', 'scientific_slide_service', 'selected_figure_ids', 'slide_plan', 'standard_by_id']}

def _rule_3(findings: Any, options: Any, root: Any, simulation_mode: Any, tex: Any, text: Any) -> dict[str, Any]:
    if simulation_mode and any((marker.casefold() in text.casefold() for marker in FORBIDDEN_RENDERED_SIMULATION_LABELS)):
        findings.append(_finding('PPT-SIM-003', 'blocker', 'artifact_quality', 'Simulation deck contains a forbidden warning or preview label.', '仿真研究演示仍包含禁止的警告或预览标签。', ['slides/main.tex'], 'Use normal scientific presentation language and retain eligibility only in sidecars.'))
    watermark_commands = visible_watermark_commands(text)
    if watermark_commands:
        findings.append(_finding('PPT-WATERMARK-001', 'blocker', 'artifact_quality', 'Slides contain visible watermark or draft-stamp commands: ' + ', '.join(watermark_commands[:4]), '演示稿包含可见水印或草稿印章命令。', ['slides/main.tex'], 'Remove visible watermark and draft-stamp commands from the slide source.'))
    if not simulation_mode and (not _has_trusted_empirical_evidence(options)) and _has_unbounded_supported_claim(text, current_method_only=True):
        findings.append(_finding('PPT-CLAIM-001', 'blocker', 'overclaim', 'Slides strengthen pending claims into empirical conclusions.', '演示稿把待验证 claim 写成了实证结论，强于论文证据。', ['slides/main.tex', 'paper/main.tex'], "Preserve the paper's claim maturity on every slide."))
    bib = _bib_entries(_text(root / 'paper' / 'references.bib') or _text(root / 'literature' / 'references.bib'))
    unknown = sorted(_citation_keys(text) - {item['key'] for item in bib})
    if unknown:
        findings.append(_finding('PPT-CITE-001', 'blocker', 'citation', f"Slides cite unknown BibTeX keys: {', '.join(unknown)}", f"演示稿引用了不存在的文献键：{', '.join(unknown)}。", ['slides/main.tex', 'paper/references.bib'], 'Use the paper bibliography and repair the citation keys.'))
    missing_graphics: list[str] = []
    for raw_graphic in _latex_graphics(text):
        if not _latex_graphic_exists(tex.parent, tex, raw_graphic, text):
            missing_graphics.append(raw_graphic)
    if missing_graphics:
        findings.append(_finding('PPT-FIG-001', 'blocker', 'slides', f"Slides reference missing graphics: {', '.join(sorted(set(missing_graphics))[:12])}", f"演示稿引用的图片不存在：{', '.join(sorted(set(missing_graphics))[:12])}。", ['slides/main.tex', 'figures/FIGURE_MANIFEST.json'], 'Use current manifest-backed figures and repair the include paths.'))
    if not simulation_mode and (not _has_trusted_empirical_evidence(options)) and (not PENDING_RE.search(text)):
        findings.append(_finding('PPT-MODE-001', 'warning', 'evidence_state', 'Slides do not visibly mark that experimental claims are pending/not run.', '实验未运行，但演示稿没有显式标注待验证状态，口头汇报可能比论文声明更强。', ['slides/main.tex', 'paper/main.tex'], 'Add a concise evidence-status marker to result and conclusion slides.'))
    placeholder = _placeholder_excerpt(text)
    if placeholder:
        findings.append(_finding('PPT-TEMPLATE-001', 'warning', 'artifact_quality', f'Slides contain unresolved template text: {placeholder}', '演示稿仍有模板占位文本，不适合作为科研汇报交付物。', ['slides/main.tex'], 'Resolve the template fragment using paper-backed content or remove the slide.'))
    slide_log = _text(root / 'slides' / 'main.log')
    if re.search('(?:undefined references|citation.+undefined|!\\s+LaTeX\\s+Error)', slide_log, re.IGNORECASE):
        findings.append(_finding('PPT-LOG-001', 'blocker', 'slides', 'Slide build log contains unresolved references, citations, or LaTeX errors.', '演示稿编译日志仍有引用或 LaTeX 错误，PDF 可能不是当前完整版本。', ['slides/main.log'], 'Repair the Beamer source and compile until references stabilize.'))
    return {key: value for key, value in locals().items() if key in ['bib', 'missing_graphics', 'placeholder', 'raw_graphic', 'slide_log', 'unknown', 'watermark_commands']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root']))
        state.update(_rule_2(build_error=state['build_error'], compile_record=state['compile_record'], findings=state['findings'], options=state['options'], pdf=state['pdf'], root=state['root'], simulation_mode=state['simulation_mode'], slide_build=state['slide_build'], source_hash=state['source_hash'], tex=state['tex'], text=state['text']))
        state.update(_rule_3(findings=state['findings'], options=state['options'], root=state['root'], simulation_mode=state['simulation_mode'], tex=state['tex'], text=state['text']))
    except _EarlyReturn as returned:
        return returned.value
    from .slide_authoring_contract import talk_delivery_findings
    from .slide_rendered_contrast import slide_contrast_findings
    from .slide_overflow_validation import slide_overflow_findings
    findings = [*state.get('findings', []), *talk_delivery_findings(root, state.get('text', ''))]
    findings.extend(slide_overflow_findings(root))
    if not any(item.get('severity') == 'blocker' for item in findings):
        findings.extend(slide_contrast_findings(root))
    return bind_slide_repair_owners(findings)
