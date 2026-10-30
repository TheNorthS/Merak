"""Validate audit coverage, counterevidence ownership, and source identity."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .node_risk_audit import KNOWN_AUDIT_VERDICTS, _audit_failure_owner, _workflow_evidence_mode
from .risk_artifact_support import _finding, _json, _missing, _relative, _sha256
from .risk_validator_support import _artifact_files, _dict_list, _newest_mtime, _string_list
from dataclasses import dataclass

@dataclass(frozen=True)
class AuditBinding:
    audit_build: Any
    build_error: str | None
    current_hash: str
    current_results_hash: str
    recorded_hash: str
    recorded_results_hash: str
    audit_build_hashes_current: bool

def _audit_binding(root: Path, path: Path) -> AuditBinding:
    audit_build_path = root / 'audit-results' / 'AUDIT_BUILD.json'
    audit_build, build_error = _json(audit_build_path)
    current_hash = ''
    current_results_hash = ''
    recorded_hash = ''
    recorded_results_hash = ''
    audit_build_hashes_current = False
    if isinstance(audit_build, dict):
        from ..workflows.review_audit import audit_source_bundle
        current_hash, _ = audit_source_bundle(root)
        current_results_hash = _sha256(path)
        recorded_hash = str(audit_build.get('source_bundle_sha256') or '')
        recorded_results_hash = str(audit_build.get('results_sha256') or '')
        audit_build_hashes_current = bool(recorded_hash and recorded_hash == current_hash and recorded_results_hash and (recorded_results_hash == current_results_hash))
    return AuditBinding(audit_build=audit_build, build_error=build_error, current_hash=current_hash, current_results_hash=current_results_hash, recorded_hash=recorded_hash, recorded_results_hash=recorded_results_hash, audit_build_hashes_current=audit_build_hashes_current)

def _evidence_mode_findings(entries: list[dict[str, Any]], options: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    expected_mode = _workflow_evidence_mode(options)
    recorded_modes = {str(item.get('evidence_mode') or '').strip().casefold() for item in entries if str(item.get('evidence_mode') or '').strip()}
    if recorded_modes and recorded_modes != {expected_mode}:
        findings.append(_finding('AUDIT-MODE-001', 'blocker', 'evidence_state', f'Audit evidence modes {sorted(recorded_modes)} do not match workflow mode {expected_mode}.', f'五层审计使用了 {sorted(recorded_modes)} 证据模式，但当前工作流是 {expected_mode}，审计结论不可直接复用。', ['audit-results/AUDIT_RESULTS.json'], 'Rerun all audit layers using the current experiment-execution mode.'))
    elif entries and (not recorded_modes):
        findings.append(_finding('AUDIT-MODE-002', 'warning', 'provenance', 'Audit results do not record the evidence mode used for adjudication.', '五层审计没有记录 planned/executed 口径，无法确认缺失实验是否被按正确标准处理。', ['audit-results/AUDIT_RESULTS.json'], 'Persist evidence_mode on every audit layer during the next audit run.'))
    return findings

def _coverage_findings(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    fallback_layers = [int(item.get('layer') or 0) for item in entries if str(item.get('method') or '').strip() == 'deterministic_fallback']
    if fallback_layers:
        findings.append(_finding('AUDIT-DEGRADED-001', 'warning', 'audit_independence', f'Audit layers used deterministic fallback after model interruption: {fallback_layers}.', f'五层审计中的 {fallback_layers} 层因模型中断改用本地确定性检查；流程可继续，但这不是完整独立语义审计。', ['audit-results/AUDIT_RESULTS.json'], 'Rerun the affected semantic audit layers before claiming submission readiness.'))
    layers = [int(item.get('layer') or 0) for item in entries]
    if sorted(layers) != [1, 2, 3, 4, 5]:
        findings.append(_finding('AUDIT-LAYER-001', 'blocker', 'audit_coverage', f'Five-layer audit coverage is incomplete or duplicated: {layers}', f'五层审计覆盖不完整或重复，当前层号为 {layers}。', ['audit-results/AUDIT_RESULTS.json'], 'Record exactly one machine-readable verdict for layers 1 through 5.'))
    return findings

def _verdict_findings(index: int, item: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    verdict = str(item.get('verdict') or '').upper()
    if verdict not in KNOWN_AUDIT_VERDICTS:
        findings.append(_finding(f'AUDIT-VERDICT-{index:03d}', 'blocker', 'audit_integrity', f"Audit layer has an invalid verdict: {verdict or '[empty]'}", f"审计层使用了无效 verdict：{verdict or '[empty]'}。", ['audit-results/AUDIT_RESULTS.json'], 'Use a defined verdict and preserve parser failures as ERROR.'))
    if verdict == 'ERROR':
        findings.append(_finding(f'AUDIT-ERROR-{index:03d}', 'blocker', 'audit_infrastructure', f"Audit layer {item.get('layer') or index} ended in ERROR.", f"五层审计第 {item.get('layer') or index} 层执行错误；工具、编码或解析失败不能被当作 PASS。", ['audit-results/AUDIT_RESULTS.json'], 'Repair the audit infrastructure and rerun the complete five-layer chain.'))
    elif verdict == 'WARN':
        findings.append(_finding(f'AUDIT-WARN-{index:03d}', 'warning', 'audit_counterevidence', f"Audit layer {item.get('layer') or index} retained a warning: {item.get('summary') or 'no summary'}", f"五层审计第 {item.get('layer') or index} 层保留警告：{item.get('summary') or '未提供摘要'}。", ['audit-results/AUDIT_RESULTS.json'], 'Keep the warning visible in the final limitations or resolve it at its responsible stage.'))
    return findings

def _inspected_evidence_findings(index: int, item: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    evidence = _string_list(item.get('evidence'))
    details = str(item.get('details') or '').strip()
    if not evidence and (not details):
        findings.append(_finding(f'AUDIT-EVID-{index:03d}', 'blocker', 'audit_integrity', f"Audit layer {item.get('layer') or index} has no inspected evidence or adjudication details.", f"审计第 {item.get('layer') or index} 层没有证据路径或裁定详情，不能只给 PASS。", ['audit-results/AUDIT_RESULTS.json'], 'Record inspected files, hashes, citations, or the kill-argument adjudication.'))
    if not str(item.get('summary') or '').strip():
        findings.append(_finding(f'AUDIT-SUMMARY-{index:03d}', 'warning', 'audit_integrity', f"Audit layer {item.get('layer') or index} has no human-readable summary.", f"五层审计第 {item.get('layer') or index} 层没有用户可读摘要，无法理解 verdict 的科研含义。", ['audit-results/AUDIT_RESULTS.json'], 'Add a concise finding, research impact, and next action.'))
    return findings

def _counterevidence_findings(index: int, item: dict[str, Any], semantic_verdicts_current: bool) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    verdict = str(item.get('verdict') or '').upper()
    evidence = _string_list(item.get('evidence'))
    if verdict in {'FAIL', 'BLOCKED'} and semantic_verdicts_current:
        layer = int(item.get('layer') or index)
        owner = _audit_failure_owner(item, layer, evidence)
        finding = _finding(f'AUDIT-FAIL-{index:03d}', 'blocker', 'audit_counterevidence', f"Audit layer {layer} returned {verdict}: {item.get('summary') or 'no summary'}", f"五层审计第 {layer} 层返回 {verdict}：{item.get('summary') or '未提供摘要'}。", ['audit-results/AUDIT_RESULTS.json', *evidence[:6]], f'Return the finding to {owner}, repair the underlying artifact, then rerun the full audit.')
        finding['upstream_node'] = owner
        findings.append(finding)
    return findings

def _inspected_inputs(root: Path) -> list[Path]:
    inspected_inputs = [root / relative for relative in ('paper/main.tex', 'paper/references.bib', 'experiments/EXPERIMENT_PLAN.md', 'experiments/METHOD_CONTRACT.json', 'experiments/RUN_SPEC.json', 'literature/references.bib', 'ideas/SELECTED_IDEA.json', 'experiments/results/analysis.md', 'figures/SCIENTIFIC_ASSET_PLAN.json', 'figures/FIGURE_MANIFEST.json', 'NARRATIVE_REPORT.md', 'review-stage/REVIEW_STATE.json')]
    inspected_suffixes = {'.py', '.yaml', '.yml', '.json', '.jsonl', '.csv', '.tsv', '.npz', '.md', '.txt', '.log'}
    for artifact_root in (root / 'experiments' / 'src', root / 'experiments' / 'configs', root / 'experiments' / 'results', root / 'experiments' / 'logs', root / '.merak' / 'experiments'):
        inspected_inputs.extend(_artifact_files(artifact_root, inspected_suffixes))
    inspected_inputs = list(dict.fromkeys(inspected_inputs))
    return inspected_inputs

def _freshness_findings(root: Path, path: Path, binding: AuditBinding, managed_results: bool) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    audit_build = binding.audit_build
    build_error = binding.build_error
    current_hash = binding.current_hash
    current_results_hash = binding.current_results_hash
    recorded_hash = binding.recorded_hash
    recorded_results_hash = binding.recorded_results_hash
    audit_build_hashes_current = binding.audit_build_hashes_current
    inspected_inputs = _inspected_inputs(root)
    if not audit_build_hashes_current and path.stat().st_mtime + 1.0 < _newest_mtime(inspected_inputs):
        findings.append(_finding('AUDIT-STALE-001', 'blocker', 'freshness', 'Audit results predate one or more authoritative artifacts they are meant to inspect.', '五层审计早于当前论文、方法、结果、引用或执行记录，不能认证最新研究状态。', ['audit-results/AUDIT_RESULTS.json', *[_relative(root, item) for item in inspected_inputs if item.is_file()]], 'Rerun all five audit layers against the current artifact hashes.'))
    if managed_results and (build_error or not isinstance(audit_build, dict)):
        findings.append(_finding('AUDIT-HASH-001', 'blocker', 'freshness', 'Managed five-layer audit has no source-bundle build record.', '五层审计缺少来源 bundle 哈希记录，无法证明审计的是当前研究版本。', ['audit-results/AUDIT_RESULTS.json', 'audit-results/AUDIT_BUILD.json'], 'Rerun the complete audit chain and persist AUDIT_BUILD.json.'))
    elif isinstance(audit_build, dict):
        if not recorded_hash or recorded_hash != current_hash:
            findings.append(_finding('AUDIT-HASH-002', 'blocker', 'freshness', 'Audit source bundle hash does not match the current research record.', '审计来源哈希与当前论文、审稿、实验或图表记录不一致。', ['audit-results/AUDIT_BUILD.json'], 'Rerun all audit layers against the current source bundle.'))
        if not recorded_results_hash or recorded_results_hash != current_results_hash:
            findings.append(_finding('AUDIT-HASH-003', 'blocker', 'freshness', 'AUDIT_BUILD results hash does not match AUDIT_RESULTS.json.', 'AUDIT_BUILD 记录的结果哈希与 AUDIT_RESULTS.json 不一致。', ['audit-results/AUDIT_RESULTS.json', 'audit-results/AUDIT_BUILD.json'], 'Restore the audited result file or regenerate the build record by rerunning the chain.'))
    return findings

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    path = root / 'audit-results' / 'AUDIT_RESULTS.json'
    payload, error = _json(path)
    if error:
        return [_missing('AUDIT-ART-001', 'audit-results/AUDIT_RESULTS.json')]
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get('results') or payload.get('audits') or []
    else:
        entries = []
    entries = _dict_list(entries)
    findings: list[dict[str, Any]] = []
    managed_results = any((str(item.get('managed_by') or '') == 'merak_audit_chain' for item in entries))
    binding = _audit_binding(root, path)
    semantic_verdicts_current = not managed_results or binding.audit_build_hashes_current
    findings.extend(_evidence_mode_findings(entries, options))
    findings.extend(_coverage_findings(entries))
    for index, item in enumerate(entries, start=1):
        findings.extend(_verdict_findings(index, item))
        findings.extend(_inspected_evidence_findings(index, item))
        counterevidence = _counterevidence_findings(index, item, semantic_verdicts_current)
        from ..workflows.draft_review_evidence import draft_response_matches
        if (semantic_verdicts_current and options.get('delivery_goal') == 'reviewable_draft'
                and item.get('delivery_goal') == 'reviewable_draft' and item.get('draft_blockers')
                and draft_response_matches(root, item)):
            from ..workflows.draft_audit_routing import draft_blocker_findings
            counterevidence = draft_blocker_findings(root, item['draft_blockers'], layer=int(item.get('layer') or index))
        if (options.get("delivery_goal") == "reviewable_draft" and item.get("delivery_goal") == "reviewable_draft"
                and item.get("draft_blockers") == [] and item.get("verdict") == "FAIL"
                and draft_response_matches(root, item)):
            for finding in counterevidence:
                finding["severity"] = "warning"
                finding["remediation"] = "Retain this scientific limitation in draft delivery; resolve before submission."
        findings.extend(counterevidence)
    findings.extend(_freshness_findings(root, path, binding, managed_results))
    return findings
