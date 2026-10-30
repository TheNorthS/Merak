"""Collect deterministic idea findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .risk_artifact_support import _finding, _missing, _text
from .risk_validator_support import _bib_entries, _candidate_sections, _citation_keys, _direction_has_semantic_overlap, _placeholder_excerpt

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any) -> dict[str, Any]:
    path = root / 'ideas' / 'ideas.md'
    text = _text(path)
    if not text:
        raise _EarlyReturn([_missing('IDEA-ART-001', 'ideas/ideas.md')])
    findings: list[dict[str, Any]] = []
    aligned, direction = _direction_has_semantic_overlap(root, options, text)
    if not aligned:
        findings.append(_finding('IDEA-DIRECTION-001', 'warning', 'research_scope', f'Candidate ideas have no distinctive term overlap with the declared direction: {direction}', f'候选 Idea 与最初研究方向“{direction}”没有可识别的领域锚点重合，可能已经偏离用户目标。', ['ideas/ideas.md', '.merak/RESEARCH_WORKFLOW_CONTRACT.json'], 'Explain the intended pivot explicitly or revise candidates to preserve the declared research objective.'))
    field_checks = {'hypothesis': '(?:hypothesis|假设|可证伪)', 'mechanism': '(?:mechanism|机制|作用路径)', 'nearest_work': '(?:nearest[-\\s]+work|most[-\\s]+related|closest\\s+prior|最近邻|最相关工作)', 'failure': '(?:falsif|failure|pivot|证伪|失败条件|转向条件)', 'feasibility': '(?:feasib|resource|compute|dataset|可行性|算力|数据需求)'}
    missing_fields = [name for name, pattern in field_checks.items() if not re.search(pattern, text, re.IGNORECASE)]
    if missing_fields:
        findings.append(_finding('IDEA-STRUCT-001', 'warning', 'scientific_logic', f"Candidate ideas do not expose all decision fields: {', '.join(missing_fields)}", f"候选 Idea 缺少这些可决策字段：{', '.join(missing_fields)}；容易退化为功能清单。", ['ideas/ideas.md'], 'For every serious candidate, add hypothesis, mechanism, nearest work, failure/pivot, and feasibility.'))
    candidate_sections = _candidate_sections(text)
    candidate_headings = [heading for heading, _ in candidate_sections]
    if not candidate_headings:
        findings.append(_finding('IDEA-STRUCT-002', 'warning', 'selection', 'No explicit candidate boundaries were detected in ideas.md.', 'ideas.md 没有清晰区分候选 Idea，后续新颖性节点可能无法稳定选择同一个方案。', ['ideas/ideas.md'], 'Give each candidate a stable heading or ID.'))
    elif len(candidate_headings) == 1:
        findings.append(_finding('IDEA-SELECT-001', 'warning', 'selection', 'Only one explicit candidate idea was detected.', '当前只有一个清晰候选 Idea；缺少可比较的替代方案会削弱新颖性和可行性选择依据。', ['ideas/ideas.md'], 'Keep at least one serious alternative or explain why the search space was deliberately narrowed.'))
    for index, (heading, body) in enumerate(candidate_sections[:12], start=1):
        missing_for_candidate = [name for name, pattern in field_checks.items() if not re.search(pattern, body, re.IGNORECASE)]
        if missing_for_candidate:
            findings.append(_finding(f'IDEA-BLOCK-{index:03d}', 'warning', 'scientific_logic', f"Candidate '{heading}' does not expose: {', '.join(missing_for_candidate)}.", f"候选 Idea“{heading}”缺少 {', '.join(missing_for_candidate)}，无法完整比较其科学可检验性。", ['ideas/ideas.md'], 'Complete the candidate-level fields instead of relying on information from another idea.'))
    placeholder = _placeholder_excerpt(text)
    if placeholder:
        findings.append(_finding('IDEA-TEMPLATE-001', 'warning', 'artifact_quality', f'Idea list still contains template text: {placeholder}', 'Idea 列表仍包含模板占位文本，候选方案可能尚未真正形成。', ['ideas/ideas.md'], 'Replace template prompts with a concrete hypothesis, mechanism, and falsification test.'))
    bib = _bib_entries(_text(root / 'literature' / 'references.bib'))
    unknown = sorted(_citation_keys(text) - {item['key'] for item in bib})
    if unknown:
        findings.append(_finding('IDEA-CITE-001', 'blocker', 'citation', f"Idea rationale cites unknown keys: {', '.join(unknown)}", f"Idea 论证引用了不存在的文献键：{', '.join(unknown)}。", ['ideas/ideas.md', 'literature/references.bib'], 'Correct or verify the cited prior work.'))
    return {key: value for key, value in locals().items() if key in ['aligned', 'bib', 'body', 'candidate_headings', 'candidate_sections', 'direction', 'field_checks', 'findings', 'heading', 'index', 'missing_fields', 'missing_for_candidate', 'path', 'placeholder', 'text', 'unknown']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
