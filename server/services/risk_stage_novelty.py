"""Collect deterministic novelty findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .risk_artifact_support import _finding, _json, _missing, _text
from .risk_validator_support import _bib_entries, _citation_keys, _direction_has_semantic_overlap, _placeholder_excerpt

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any, service: Any) -> dict[str, Any]:
    from .method_contract import method_contract_service
    findings: list[dict[str, Any]] = service._search_evidence_findings(root, 'novelty', options)
    report_path = root / 'ideas' / 'novelty_report.md'
    if not _text(report_path):
        findings.append(_missing('NOV-ART-001', 'ideas/novelty_report.md'))
    valid, issues, _ = method_contract_service.validate_selected_idea(root)
    if not valid:
        for index, issue in enumerate(issues[:16], start=1):
            findings.append(_finding(f'NOV-CONTRACT-{index:03d}', 'blocker', 'contract', issue, f'选定 Idea 契约不完整：{issue}', ['ideas/SELECTED_IDEA.json', 'ideas/novelty_report.md'], 'Repair the selected-idea contract without changing the evidence-backed selection.'))
    report = _text(report_path)
    bib_entries = _bib_entries(_text(root / 'literature' / 'references.bib'))
    unknown = sorted(_citation_keys(report) - {item['key'] for item in bib_entries})
    if unknown:
        findings.append(_finding('NOV-CITE-001', 'blocker', 'citation', f"Novelty report cites unknown keys: {', '.join(unknown)}", f"新颖性报告引用了不存在的文献键：{', '.join(unknown)}。", ['ideas/novelty_report.md', 'literature/references.bib'], 'Verify the nearest-work references and correct the keys.'))
    if not re.search('(?:unknown|uncertain|inconclusive|不确定|未知|证据不足)', report, re.IGNORECASE):
        findings.append(_finding('NOV-UNC-001', 'warning', 'uncertainty', 'Novelty review contains no explicit UNKNOWN or inconclusive boundary.', '新颖性报告没有标出 UNKNOWN/证据不足边界，容易把检索未发现误写成绝对新颖。', ['ideas/novelty_report.md'], 'Mark unverified claim overlap as UNKNOWN and state the retrieval limits.'))
    for check_id, pattern, plain, remediation in (('NOV-COMP-001', '(?:nearest|most\\s+related|最近邻|最相关)', '新颖性报告没有明确列出最近邻工作，无法判断贡献增量。', 'Name the closest prior methods and compare claims, mechanisms, data, and evidence.'), ('NOV-COMP-002', '(?:overlap|difference|delta|重叠|差异|创新增量)', '新颖性报告没有进行 claim-level 重叠/差异分析，可能把功能变化误判为科学创新。', 'State what the nearest work already does and the exact remaining delta.'), ('NOV-COMP-003', '(?:recommend|reject|decision|推荐|淘汰|结论|选择)', '新颖性报告没有留下可追溯的选择决策，后续实验可能在候选 Idea 之间漂移。', 'Record the selected candidate, rejected alternatives, and the evidence for the decision.')):
        if not re.search(pattern, report, re.IGNORECASE):
            findings.append(_finding(check_id, 'warning', 'novelty_logic', pattern, plain, ['ideas/novelty_report.md', 'literature/references.bib'], remediation))
    selected_payload, selected_error = _json(root / 'ideas' / 'SELECTED_IDEA.json')
    if isinstance(selected_payload, dict):
        title = str(selected_payload.get('title') or '').strip()
        if title and title.casefold() not in report.casefold():
            findings.append(_finding('NOV-TRACE-001', 'blocker', 'traceability', 'Selected idea title is absent from the novelty report.', '冻结的选定 Idea 没有出现在新颖性报告中，无法确认它确实来自本轮比较。', ['ideas/SELECTED_IDEA.json', 'ideas/novelty_report.md'], 'Regenerate the report or repair the selected-idea provenance without changing the accepted title silently.'))
        selected_text = '\n'.join([title, str(selected_payload.get('problem_statement') or ''), str(selected_payload.get('hypothesis') or ''), *[f"{item.get('name') or ''} {item.get('description') or ''}" for item in selected_payload.get('mechanisms') or [] if isinstance(item, dict)]])
        aligned, direction = _direction_has_semantic_overlap(root, options, selected_text)
        if not aligned:
            findings.append(_finding('NOV-DIRECTION-001', 'warning', 'research_scope', f'Frozen selected idea has no distinctive term overlap with the declared direction: {direction}', f'冻结 Idea 与最初研究方向“{direction}”没有可识别的领域锚点重合，可能发生了未说明的研究转向。', ['ideas/SELECTED_IDEA.json', '.merak/RESEARCH_WORKFLOW_CONTRACT.json'], 'Record an explicit user-approved pivot or restore a selected idea grounded in the declared direction.'))
    if _placeholder_excerpt(report):
        findings.append(_finding('NOV-TEMPLATE-001', 'warning', 'artifact_quality', 'Novelty report still contains unresolved template text.', '新颖性报告仍包含模板占位文本，结论可能不是基于实际检索。', ['ideas/novelty_report.md'], 'Replace template prompts with retrieved prior-art comparisons and uncertainty boundaries.'))
    if options.get('enable_patent_search'):
        patent, error = _json(root / 'ideas' / 'patent_prior_art.json')
        if error:
            findings.append(_missing('NOV-PAT-001', 'ideas/patent_prior_art.json'))
        elif isinstance(patent, dict) and (not patent.get('limitations')):
            findings.append(_finding('NOV-PAT-002', 'warning', 'prior_art', 'Patent screen does not record coverage limitations.', '专利检索产物没有记录司法辖区、专利族或查询覆盖限制。', ['ideas/patent_prior_art.json'], 'Record why the screen is not a legal patentability opinion.'))
    return {key: value for key, value in locals().items() if key in ['_', 'aligned', 'bib_entries', 'check_id', 'direction', 'error', 'findings', 'index', 'issue', 'issues', 'method_contract_service', 'patent', 'pattern', 'plain', 'remediation', 'report', 'report_path', 'selected_error', 'selected_payload', 'selected_text', 'title', 'unknown', 'valid']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root'], service=state['service']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
