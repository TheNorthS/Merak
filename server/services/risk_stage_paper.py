"""Collect deterministic paper findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .node_risk_audit import _has_trusted_empirical_evidence, _workflow_evidence_mode
from .risk_artifact_support import _finding, _has_content, _json, _latex_sources, _missing, _relative, _text
from .risk_constants import PENDING_RE
from .risk_validator_support import _bib_entries, _citation_keys, _ids, _inline_bibliography_keys, _latex_graphic_exists, _latex_graphics, _newest_mtime, _placeholder_excerpt, _unbounded_supported_claims
from .simulation_policy import FORBIDDEN_RENDERED_SIMULATION_LABELS, rendered_mode_framing_hits_outside_end_disclosure, simulation_disclosure_report, strip_latex_comments, visible_watermark_commands

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any) -> dict[str, Any]:
    main = root / 'paper' / 'main.tex'
    if not _has_content(main):
        raise _EarlyReturn([_missing('PAPER-ART-001', 'paper/main.tex')])
    sources = _latex_sources(root, main)
    combined = '\n'.join(sources.values())
    findings: list[dict[str, Any]] = []
    claim_locations: list[dict[str, Any]] = []
    simulation_mode = _workflow_evidence_mode(options) == 'synthetic_preview'
    if not simulation_mode and (not _has_trusted_empirical_evidence(options)):
        for source, source_content in sources.items():
            for hit in _unbounded_supported_claims(source_content, current_method_only=True):
                claim_locations.append({'path': _relative(root, source), 'line': source_content.count('\n', 0, int(hit['start'])) + 1, 'match': str(hit['match']), 'context': str(hit['context'])})
    if claim_locations:
        first = claim_locations[0]
        evidence_paths = list(dict.fromkeys([str(item['path']) for item in claim_locations] + ['experiments/results/analysis.md']))
        finding = _finding('PAPER-CLAIM-001', 'blocker', 'overclaim', f"Paper uses empirical superiority language without a visible pending/not-run boundary at {first['path']}:{first['line']}: {first['context']}", f"论文在未运行实验时使用了无边界的实证优越性措辞；首个位置：{first['path']}:{first['line']}。", evidence_paths, f"Rewrite {first['path']}:{first['line']} as a conditional, negated, or explicitly pending statement, then rerun validation.")
        finding['locations'] = claim_locations
        findings.append(finding)
    if simulation_mode:
        normalized_manuscript = ' '.join(strip_latex_comments(combined).split())
        main_text = _text(main)
        disclosure = simulation_disclosure_report(main_text)
        framing_hits = rendered_mode_framing_hits_outside_end_disclosure(combined)
        if disclosure.get('count') != 1 or disclosure.get('end_matter_count') != 1 or disclosure.get('outside_end_matter_count') != 0:
            findings.append(_finding('PAPER-SIM-001', 'blocker', 'evidence_state', 'Simulation manuscript must contain exactly one disclosure after the Conclusion and before the bibliography.', '仿真论文必须在结论之后、参考文献之前且仅保留一段统一说明。', ['paper/main.tex'], 'Reassemble main.tex so the canonical disclosure appears exactly once in final end matter.'))
        if framing_hits:
            findings.append(_finding('PAPER-SIM-003', 'blocker', 'evidence_state', 'Manuscript exposes simulation/evidence-mode framing outside the final disclosure: ' + ', '.join(framing_hits[:6]), '论文在末尾统一说明之外暴露了仿真或证据模式属性。', ['paper/main.tex'], 'Remove repeated framing from sections, figures, tables, and captions; retain only the canonical final disclosure.'))
        if any((marker.casefold() in normalized_manuscript.casefold() for marker in FORBIDDEN_RENDERED_SIMULATION_LABELS)):
            findings.append(_finding('PAPER-SIM-002', 'blocker', 'artifact_quality', 'Rendered simulation manuscript contains a forbidden warning or preview label.', '仿真论文仍包含禁止的警告或预览标签。', ['paper/main.tex'], 'Remove visible warnings and keep eligibility metadata in sidecars.'))
    watermark_commands = visible_watermark_commands(combined)
    if watermark_commands:
        findings.append(_finding('PAPER-WATERMARK-001', 'blocker', 'artifact_quality', 'Manuscript contains visible watermark or draft-stamp commands: ' + ', '.join(watermark_commands[:4]), '论文包含可见水印或草稿印章命令。', ['paper/main.tex'], 'Remove watermark and draft-stamp commands from every manuscript mode.'))
    bib = _bib_entries(_text(root / 'paper' / 'references.bib') or _text(root / 'literature' / 'references.bib'))
    known_citations = {item['key'] for item in bib} | _inline_bibliography_keys(combined)
    unknown = sorted(_citation_keys(combined) - known_citations)
    if unknown:
        findings.append(_finding('PAPER-CITE-001', 'blocker', 'citation', f"Paper cites unknown keys: {', '.join(unknown)}", f"论文引用了 BibTeX 中不存在的键：{', '.join(unknown)}。", ['paper/main.tex', 'paper/references.bib'], 'Repair citation keys before compilation.'))
    selected, _ = _json(root / 'ideas' / 'SELECTED_IDEA.json')
    layout_report, _ = _json(root / '.merak/quality/paper-layout.json')
    if isinstance(layout_report, dict):
        findings.extend(dict(item) for item in layout_report.get('repair_findings') or [] if isinstance(item, dict))
    return {key: value for key, value in locals().items() if key in ['_', 'bib', 'claim_locations', 'combined', 'disclosure', 'evidence_paths', 'finding', 'findings', 'first', 'framing_hits', 'hit', 'known_citations', 'main', 'main_text', 'normalized_manuscript', 'selected', 'simulation_mode', 'source', 'source_content', 'sources', 'unknown', 'watermark_commands']}

def _rule_2(combined: Any, findings: Any, main: Any, options: Any, root: Any, selected: Any, sources: Any) -> dict[str, Any]:
    if isinstance(selected, dict):
        claim_ids = _ids(selected.get('claims'))
        evidence_map, _ = _json(root / '.merak' / 'research_audit' / 'PAPER_EVIDENCE_MAP.json')
        evidence_map = evidence_map if isinstance(evidence_map, dict) else {}
        map_claim_ids = {str(item.get('id') or '').strip() for item in evidence_map.get('claims', []) if isinstance(item, dict) and str(item.get('id') or '').strip()}
        plan_claim_ids = {str(item.get('idea_claim_id') or '').strip() for item in evidence_map.get('claim_evidence_plan', []) if isinstance(item, dict) and str(item.get('idea_claim_id') or '').strip()}
        mapping_claim_ids = {str(item.get('claim_id') or '').strip() for item in evidence_map.get('claim_mappings', []) if isinstance(item, dict) and str(item.get('claim_id') or '').strip()}
        missing_claims = [item for item in claim_ids if item not in map_claim_ids or item not in plan_claim_ids or item not in mapping_claim_ids]
        manuscript = evidence_map.get('manuscript') if isinstance(evidence_map.get('manuscript'), dict) else {}
        map_hash = str(manuscript.get('source_bundle_sha256') or '')
        try:
            from .latex_bundle import latex_source_bundle
            current_hash, _ = latex_source_bundle(root / 'paper')
        except Exception:
            current_hash = ''
        stale_map = bool(map_hash and current_hash and (map_hash != current_hash))
        if not evidence_map or missing_claims or stale_map:
            detail = f"Evidence map is missing or incomplete for claims: {', '.join(missing_claims)}" if missing_claims else 'Paper evidence map is stale relative to the current LaTeX source bundle.' if stale_map else 'Paper evidence map is missing.'
            findings.append(_finding('PAPER-CLAIM-002', 'warning', 'claim_mapping', detail, '论文的机器可读证据映射缺失、不完整或过期；正文不需要打印内部 C1/C2 编号，但每项主张必须在审计 sidecar 中绑定证据、反证和成熟度。', ['ideas/SELECTED_IDEA.json', '.merak/research_audit/PAPER_EVIDENCE_MAP.json', 'paper/main.tex'], 'Refresh PAPER_EVIDENCE_MAP.json after manuscript edits and ensure every frozen claim has decisive evidence, counterevidence, maturity, and manuscript-section targets.'))
    required_sections = {'abstract': '\\\\begin\\{abstract\\}', 'introduction': '\\\\section\\{[^}]*intro', 'method': '\\\\section\\{[^}]*(?:method|approach|model)', 'evidence': '\\\\section\\{[^}]*(?:experiment|evaluation|result|protocol)', 'limitations': '\\\\section\\{[^}]*(?:discussion|limitation|threat)', 'conclusion': '\\\\section\\{[^}]*conclu'}
    missing_sections = [name for name, pattern in required_sections.items() if not re.search(pattern, combined, re.IGNORECASE)]
    if missing_sections:
        findings.append(_finding('PAPER-STRUCT-001', 'warning', 'paper_structure', f"Paper does not expose expected argument sections: {', '.join(missing_sections)}", f"论文缺少可识别的论证章节：{', '.join(missing_sections)}；这不是页数问题，而是科研论证链可能不完整。", ['paper/main.tex'], 'Add only evidence-grounded sections; do not pad the paper to satisfy length.'))
    placeholder = _placeholder_excerpt(combined)
    if placeholder:
        findings.append(_finding('PAPER-TEMPLATE-001', 'warning', 'artifact_quality', f'Paper contains unresolved template text: {placeholder}', '论文仍有占位文本，当前版本不能作为高质量科研交付物。', ['paper/main.tex'], 'Resolve or explicitly remove the template fragment without inventing missing results.'))
    missing_graphics: list[str] = []
    for source_path, source_text in sources.items():
        for raw_graphic in _latex_graphics(source_text):
            if not _latex_graphic_exists(main.parent, source_path, raw_graphic, combined):
                missing_graphics.append(raw_graphic)
    if missing_graphics:
        findings.append(_finding('PAPER-FIG-001', 'blocker', 'figure', f"Paper references missing graphic files: {', '.join(sorted(set(missing_graphics))[:12])}", f"论文引用的图片文件不存在：{', '.join(sorted(set(missing_graphics))[:12])}。", ['paper/main.tex', 'figures/FIGURE_MANIFEST.json'], 'Repair the include path or regenerate the exact manifest-backed figure.'))
    if not _has_trusted_empirical_evidence(options) and (not PENDING_RE.search(combined)):
        findings.append(_finding('PAPER-MODE-001', 'warning', 'evidence_state', 'Paper has no visible pending/not-run boundary despite disabled experiments.', '实验未运行，但论文没有显式标注 Pending/Not run，读者可能误判证据成熟度。', ['paper/main.tex', 'experiments/results/analysis.md'], 'Expose the evidence state in the abstract, results, and conclusion.'))
    upstream_relatives = ('ideas/SELECTED_IDEA.json', 'experiments/METHOD_CONTRACT.json', 'experiments/results/analysis.md', 'figures/SCIENTIFIC_ASSET_PLAN.json', 'figures/FIGURE_MANIFEST.json', 'NARRATIVE_REPORT.md')
    upstream_paths = [root / relative for relative in upstream_relatives]
    recorded_input_hashes: dict[str, str] = {}
    freshness_binding = ''
    freeze, _ = _json(root / 'paper' / 'SCIENTIFIC_FREEZE.json')
    return {key: value for key, value in locals().items() if key in ['_', 'claim_ids', 'current_hash', 'detail', 'evidence_map', 'freeze', 'freshness_binding', 'latex_source_bundle', 'manuscript', 'map_claim_ids', 'map_hash', 'mapping_claim_ids', 'missing_claims', 'missing_graphics', 'missing_sections', 'placeholder', 'plan_claim_ids', 'raw_graphic', 'recorded_input_hashes', 'required_sections', 'source_path', 'source_text', 'stale_map', 'upstream_paths', 'upstream_relatives']}

def _rule_3(findings: Any, freeze: Any, root: Any, sources: Any, upstream_paths: Any, upstream_relatives: Any) -> dict[str, Any]:
    if isinstance(freeze, dict) and freeze.get('schema_version') == 1 and isinstance(freeze.get('inputs'), dict):
        recorded_input_hashes = {str(key): str(value) for key, value in dict(freeze.get('inputs') or {}).items()}
        freshness_binding = 'paper/SCIENTIFIC_FREEZE.json'
    else:
        draft_state, _ = _json(root / 'paper' / 'DRAFT_STATE.json')
        if isinstance(draft_state, dict) and isinstance(draft_state.get('authoring_inputs'), dict):
            recorded_input_hashes = {str(key): str(value) for key, value in dict(draft_state.get('authoring_inputs') or {}).items()}
            freshness_binding = 'paper/DRAFT_STATE.json'
    try:
        from .paper_drafting import SEMANTIC_DERIVED_HASH_MODE, paper_drafting_service, stable_source_hash
        if freeze.get('input_hash_mode') == SEMANTIC_DERIVED_HASH_MODE:
            scientific_inputs = paper_drafting_service.scientific_freeze_inputs(root)
            current_input_hashes = {relative: scientific_inputs.get(relative, '<missing>') for relative in upstream_relatives}
        else:
            current_input_hashes = {relative: stable_source_hash(root / relative) or '<missing>' for relative in upstream_relatives}
    except Exception:
        current_input_hashes = {}
        recorded_input_hashes = {}
        freshness_binding = ''
    changed_bound_inputs = sorted((relative for relative in upstream_relatives if relative in recorded_input_hashes and current_input_hashes.get(relative) != recorded_input_hashes.get(relative)))
    unbound_paths = [root / relative for relative in upstream_relatives if relative not in recorded_input_hashes]
    timestamp_stale = bool(_newest_mtime(list(sources)) + 5.0 < _newest_mtime(unbound_paths if recorded_input_hashes else upstream_paths))
    if changed_bound_inputs or timestamp_stale:
        finding = _finding('PAPER-STALE-001', 'blocker', 'freshness', 'Authoritative paper-input hashes changed after the manuscript scientific freeze.' if changed_bound_inputs else 'One or more unbound upstream artifacts are newer than the paper source bundle.', '论文科学冻结后，Idea、方法、结果、图表或叙事的内容哈希发生了变化。' if changed_bound_inputs else '尚未绑定哈希的上游产物晚于论文，论文可能仍描述旧研究状态。', ['paper/main.tex', *([freshness_binding] if freshness_binding else []), *[_relative(root, item) for item in upstream_paths if item.is_file()]], 'Review the upstream diff and regenerate or deliberately reconcile the affected paper sections.')
        finding['freshness_basis'] = 'content_hashes' if changed_bound_inputs else 'mtime_fallback'
        finding['changed_inputs'] = changed_bound_inputs
        finding['owner_node'] = 'paper'
        finding['producer_kind'] = 'deterministic'
        finding['runtime_operation'] = 'refresh_paper_runtime_inputs'
        finding['target_files'] = ['paper/DRAFT_STATE.json', 'paper/SCIENTIFIC_FREEZE.json']
        findings.append(finding)
    return {key: value for key, value in locals().items() if key in ['SEMANTIC_DERIVED_HASH_MODE', '_', 'changed_bound_inputs', 'current_input_hashes', 'draft_state', 'finding', 'freshness_binding', 'paper_drafting_service', 'recorded_input_hashes', 'scientific_inputs', 'stable_source_hash', 'timestamp_stale', 'unbound_paths']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root']))
        state.update(_rule_2(combined=state['combined'], findings=state['findings'], main=state['main'], options=state['options'], root=state['root'], selected=state['selected'], sources=state['sources']))
        state.update(_rule_3(findings=state['findings'], freeze=state['freeze'], root=state['root'], sources=state['sources'], upstream_paths=state['upstream_paths'], upstream_relatives=state['upstream_relatives']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
