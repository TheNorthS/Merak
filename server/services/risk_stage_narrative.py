"""Collect deterministic narrative findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib
import re
from .node_risk_audit import _has_trusted_empirical_evidence, _workflow_evidence_mode
from .risk_artifact_support import _finding, _json, _missing, _text
from .risk_constants import LIMITATION_RE, PENDING_RE, SIMULATION_SCOPE_RE
from .risk_validator_support import _dict_list, _has_unbounded_supported_claim, _ids, _placeholder_excerpt

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(options: Any, root: Any) -> dict[str, Any]:
    path = root / 'NARRATIVE_REPORT.md'
    text = _text(path)
    if not text:
        raise _EarlyReturn([_missing('NAR-ART-001', 'NARRATIVE_REPORT.md')])
    findings: list[dict[str, Any]] = []
    selected, _ = _json(root / 'ideas' / 'SELECTED_IDEA.json')
    title = str(selected.get('title') or '') if isinstance(selected, dict) else ''
    title_tokens = [item.casefold() for item in re.findall('[A-Za-z0-9]{5,}', title)]
    if title_tokens and (not any((token in text.casefold() for token in title_tokens))):
        findings.append(_finding('NAR-DRIFT-001', 'blocker', 'idea_drift', 'Narrative is not traceable to the frozen selected-idea title.', '叙事报告没有出现冻结 Idea 的关键术语，可能已经偏离用户确认的研究主线。', ['ideas/SELECTED_IDEA.json', 'NARRATIVE_REPORT.md'], 'Rebuild the narrative from the frozen title, claims, and mechanisms.'))
    simulation_mode = _workflow_evidence_mode(options) == 'synthetic_preview'
    if not simulation_mode and (not _has_trusted_empirical_evidence(options)) and _has_unbounded_supported_claim(text, current_method_only=True):
        findings.append(_finding('NAR-CLAIM-001', 'blocker', 'overclaim', 'Narrative claims empirical support although experiments were disabled.', '叙事报告在未运行实验时使用了实证支持措辞，超出了当前证据范围。', ['NARRATIVE_REPORT.md'], 'Label findings as planned or pending and retain the falsification plan.'))
    if isinstance(selected, dict):
        claim_ids = _ids(selected.get('claims'))
        missing_claim_ids = [item for item in claim_ids if item.casefold() not in text.casefold()]
        if missing_claim_ids:
            findings.append(_finding('NAR-CLAIM-002', 'warning', 'claim_mapping', f"Narrative omits frozen claim IDs: {', '.join(missing_claim_ids)}", f"叙事没有逐项处理冻结 claim：{', '.join(missing_claim_ids)}，可能遗漏负结果或待验证边界。", ['ideas/SELECTED_IDEA.json', 'NARRATIVE_REPORT.md'], 'State the maturity and evidence source for every frozen claim.'))
        mechanisms = _dict_list(selected.get('mechanisms'))
        narrative_folded = text.casefold()
        missing_mechanisms = []
        for item in mechanisms:
            mechanism_id = str(item.get('id') or '').strip()
            mechanism_name = str(item.get('name') or '').strip()
            if any((candidate and candidate.casefold() in narrative_folded for candidate in (mechanism_id, mechanism_name))):
                continue
            missing_mechanisms.append(mechanism_name or mechanism_id)
        if missing_mechanisms:
            findings.append(_finding('NAR-MECH-001', 'warning', 'mechanism', f"Narrative omits declared mechanisms: {', '.join(missing_mechanisms)}", '叙事没有覆盖全部声明机制，方法贡献可能被改写成更容易讲述的替代方案。', ['ideas/SELECTED_IDEA.json', 'experiments/METHOD_CONTRACT.json', 'NARRATIVE_REPORT.md'], 'Explain how each required mechanism links to a decisive comparison.'))
    if simulation_mode and (not SIMULATION_SCOPE_RE.search(text)):
        findings.append(_finding('NAR-SIM-001', 'blocker', 'evidence_state', 'Simulation narrative does not bound its findings to a defined evaluation scope.', '仿真研究叙事没有把结论限制在明确的评估范围内。', ['NARRATIVE_REPORT.md'], 'Synthesize the complete quantitative findings within the declared simulator, controlled study, registered conditions, or evaluation domain.'))
    if not simulation_mode and (not _has_trusted_empirical_evidence(options)) and (not PENDING_RE.search(text)):
        findings.append(_finding('NAR-MODE-001', 'warning', 'evidence_state', 'Narrative does not visibly mark the no-run/pending evidence state.', '叙事没有显式标注实验未运行或 claim 待验证，后续论文写作容易越界。', ['NARRATIVE_REPORT.md'], 'Expose the planned evidence state in the findings and conclusion sections.'))
    if not LIMITATION_RE.search(text):
        findings.append(_finding('NAR-LIMIT-001', 'warning', 'interpretation', 'Narrative has no limitations or threats-to-validity section.', '叙事没有局限和有效性威胁，论证链只保留了支持方向。', ['NARRATIVE_REPORT.md'], 'Retain negative evidence, unresolved alternatives, and explicit limitations.'))
    placeholder = _placeholder_excerpt(text)
    if placeholder:
        findings.append(_finding('NAR-TEMPLATE-001', 'warning', 'artifact_quality', f'Narrative still contains template text: {placeholder}', '叙事报告仍含占位文本，不能作为论文论证输入。', ['NARRATIVE_REPORT.md'], 'Replace the template fragment with contract- and evidence-backed prose.'))
    build, build_error = _json(root / '.merak' / 'NARRATIVE_BUILD.json')
    return {key: value for key, value in locals().items() if key in ['_', 'build', 'build_error', 'claim_ids', 'findings', 'item', 'mechanism_id', 'mechanism_name', 'mechanisms', 'missing_claim_ids', 'missing_mechanisms', 'narrative_folded', 'path', 'placeholder', 'selected', 'simulation_mode', 'text', 'title', 'title_tokens']}

def _rule_2(build: Any, build_error: Any, findings: Any, path: Any, root: Any, options: Any = None) -> dict[str, Any]:
    if build_error:
        findings.append(_finding('NAR-PROV-001', 'warning', 'provenance', 'Narrative has no deterministic source-bundle record.', '叙事报告没有记录生成时绑定的来源文件哈希；后续源文件变化需要重新确认叙事是否仍然有效。', ['NARRATIVE_REPORT.md', '.merak/NARRATIVE_BUILD.json'], 'Generate or refresh the narrative provenance record after upstream changes.'))
    elif isinstance(build, dict):
        recorded_sources = build.get('sources')
        source_paths = ([root / item for item in recorded_sources]
                        if isinstance(recorded_sources, list) and all(isinstance(item, str) and item.strip()
                            for item in recorded_sources) else [])
        if not source_paths or not str(build.get('source_bundle_sha256') or ''):
            findings.append(_finding('NAR-PROV-002', 'blocker', 'provenance', 'Narrative build record has no complete source bundle.', '叙事构建记录没有完整来源清单或来源哈希，无法确认文本绑定了哪个研究状态。', ['.merak/NARRATIVE_BUILD.json'], 'Rebuild the narrative with a complete source bundle and hash.'))
        else:
            try:
                from .scientific_narrative import scientific_narrative_service
                if any(not source.resolve().is_relative_to(root.resolve()) for source in source_paths):
                    raise ValueError('Narrative recorded source leaves its project')
                current_paths = scientific_narrative_service._source_paths(root)
                inventory_changed = recorded_sources != [source.relative_to(root).as_posix() for source in current_paths]
                current_source_hash = scientific_narrative_service._source_hash(root, current_paths)
            except (OSError, ValueError, TypeError):
                current_source_hash = ''
                inventory_changed = True
            from .narrative_acceptance_binding import accepted_narrative_inputs_match
            accepted_inputs = (not inventory_changed and bool(current_source_hash)
                and accepted_narrative_inputs_match(root, build, current_paths, options or {}))
            if inventory_changed or not current_source_hash or (current_source_hash != str(build.get('source_bundle_sha256')) and not accepted_inputs):
                findings.append(_finding('NAR-PROV-003', 'blocker', 'provenance', 'Narrative source bundle hash does not match current upstream artifacts.', '叙事报告绑定的 Idea/方法/结果来源已经变化，当前叙事已过期。', ['.merak/NARRATIVE_BUILD.json', 'NARRATIVE_REPORT.md'], 'Regenerate the narrative from the current frozen contracts and evidence state.', target_files=['NARRATIVE_REPORT.md']))
            output_hash = str(build.get('output_sha256') or '')
            if output_hash:
                try:
                    current_output_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    current_output_hash = ''
                if current_output_hash and current_output_hash != output_hash:
                    findings.append(_finding('NAR-PROV-004', 'blocker', 'provenance', 'NARRATIVE_BUILD.json output hash does not match NARRATIVE_REPORT.md.', '叙事构建记录与当前 NARRATIVE_REPORT.md 不一致，不能确认验收文本来源。', ['.merak/NARRATIVE_BUILD.json', 'NARRATIVE_REPORT.md'], 'Refresh the narrative build record or regenerate the narrative.'))
    return {key: value for key, value in locals().items() if key in ['current_output_hash', 'current_source_hash', 'output_hash', 'scientific_narrative_service', 'source_paths']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(options=state['options'], root=state['root']))
        state.update(_rule_2(build=state['build'], build_error=state['build_error'], findings=state['findings'], path=state['path'], root=state['root'], options=options))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
