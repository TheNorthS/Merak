"""Collect deterministic figure findings for the risk coordinator.

Finding generation does not grant artifact acceptance. Repair responsibility
remains with the producer identified by each finding, not a downstream consumer."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from .node_risk_audit import _has_trusted_empirical_evidence
from .risk_artifact_support import _finding, _json, _missing
from .risk_validator_support import _dict_list

class _EarlyReturn(BaseException):

    def __init__(self, value: Any):
        self.value = value

def _rule_1(root: Any) -> dict[str, Any]:
    from .figure_artifacts import figure_artifact_registry
    findings: list[dict[str, Any]] = []
    valid, issues, payload = figure_artifact_registry.validate(root / 'figures')
    if not valid:
        for index, issue in enumerate(issues[:20], start=1):
            findings.append(_finding(f'FIG-ART-{index:03d}', 'blocker', 'figure', issue, f'图表产物不可用：{issue}', ['figures/FIGURE_MANIFEST.json'], 'Repair the source, preview, metadata, or persisted hash.'))
    quality_issues = figure_artifact_registry.scientific_quality_issues(root / 'figures')
    alignment_issues = figure_artifact_registry.scientific_alignment_issues(root / 'figures')
    for index, issue in enumerate([*quality_issues, *alignment_issues][:30], start=1):
        issue_asset_id = str(issue).partition(':')[0].strip()
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{2,80}', issue_asset_id):
            issue_asset_id = ''
        asset_target_files: list[str] = ['figures/FIGURE_SPECS.json', 'figures/FIGURE_MANIFEST.json']
        if issue_asset_id:
            for entry in payload.get('figures', []):
                if not isinstance(entry, dict):
                    continue
                metadata = entry.get('metadata') or {}
                entry_ids = {str(entry.get('id') or ''), str(metadata.get('id') or ''), str(metadata.get('semantic_key') or '')}
                if issue_asset_id not in entry_ids:
                    continue
                source_path = str(entry.get('source_path') or '').strip()
                if source_path.startswith('figures/') and source_path not in asset_target_files:
                    asset_target_files.insert(0, source_path)
                break
        findings.append(_finding(f'FIG-QUALITY-{index:03d}', 'blocker', 'scientific_alignment', issue, f'图表实际内容未满足科研契约：{issue}', ['figures/FIGURE_SPECS.json', 'figures/FIGURE_MANIFEST.json', 'ideas/SELECTED_IDEA.json'], 'Regenerate or repair the same semantic figure ID from the frozen claims and mechanisms.', target_files=asset_target_files, asset_ids=[issue_asset_id] if issue_asset_id else []))
    keys = [str((item.get('metadata') or {}).get('semantic_key') or '') for item in payload.get('figures', [])]
    duplicates = sorted({key for key in keys if key and keys.count(key) > 1})
    if duplicates:
        findings.append(_finding('FIG-DUP-001', 'warning', 'duplication', f"Multiple manifest entries share semantic IDs: {', '.join(duplicates)}", f"以下图表语义 ID 重复：{', '.join(duplicates)}；论文可能引用近似重复图。", ['figures/FIGURE_MANIFEST.json'], 'Keep one current source/output pair per scientific question.'))
    entries = [item for item in payload.get('figures', []) if isinstance(item, dict)]
    exposed_placeholders = [str(item.get('id') or 'unknown') for item in entries if str((item.get('metadata') or {}).get('evidence_status') or '').casefold() == 'placeholder' and (bool(item.get('paper_ready')) or (item.get('metadata') or {}).get('paper_selected') is not False)]
    if exposed_placeholders:
        findings.append(_finding('FIG-PLACEHOLDER-001', 'blocker', 'evidence_state', 'Placeholder/demo figures remain eligible for paper selection: ' + ', '.join(exposed_placeholders[:8]), '带演示值的占位图仍被标记为可用于论文，后续组件可能把 NOT EVIDENCE 图误当作科研证据。', ['figures/FIGURE_MANIFEST.json'], 'Set paper_ready=false and metadata.paper_selected=false for every placeholder/demo figure.'))
    for hash_field, label in (('source_sha256', 'editable source'), ('output_sha256', 'rendered output')):
        hashes = [str(item.get(hash_field) or '') for item in entries if item.get(hash_field)]
        duplicates_by_hash = {value for value in hashes if hashes.count(value) > 1}
        if duplicates_by_hash:
            findings.append(_finding(f'FIG-HASH-{hash_field.upper()}', 'warning', 'duplication', f'Multiple manifest entries share the same {label} hash.', f'多个图表条目共享同一{label}哈希，可能只是重复命名或重复渲染。', ['figures/FIGURE_MANIFEST.json'], 'Keep one semantic asset per scientific question and remove redundant entries.'))
    meaningless = [str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or '') for item in entries if re.fullmatch('(?:fig(?:ure)?|image|generated|plot|diagram|asset)[_-]?(?:\\d+|[0-9a-f]{6,})', str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or ''), re.IGNORECASE)]
    if meaningless:
        findings.append(_finding('FIG-NAME-001', 'warning', 'traceability', f"Figures use non-semantic identifiers: {', '.join(meaningless[:8])}", '部分图片名称只是序号或哈希，用户和论文无法从名称判断其科研用途。', ['figures/FIGURE_MANIFEST.json'], 'Rename semantic IDs after the scientific question, such as method_architecture or robustness_sensitivity.'))
    asset_plan, asset_error = _json(root / 'figures' / 'SCIENTIFIC_ASSET_PLAN.json')
    if not asset_error and isinstance(asset_plan, dict):
        from .figure_preflight import asset_plan_preflight_findings
        findings.extend(asset_plan_preflight_findings(asset_plan))
    return {key: value for key, value in locals().items() if key in ['alignment_issues', 'asset_error', 'asset_plan', 'asset_target_files', 'duplicates', 'duplicates_by_hash', 'entries', 'entry', 'entry_ids', 'exposed_placeholders', 'figure_artifact_registry', 'findings', 'hash_field', 'hashes', 'index', 'issue', 'issue_asset_id', 'issues', 'keys', 'label', 'meaningless', 'metadata', 'payload', 'quality_issues', 'source_path', 'valid']}

def _rule_2(asset_error: Any, asset_plan: Any, entries: Any, findings: Any, options: Any) -> dict[str, Any]:
    if asset_error or not isinstance(asset_plan, dict):
        findings.append(_missing('FIG-PLAN-001', 'figures/SCIENTIFIC_ASSET_PLAN.json'))
    else:
        planned_ids = {str(item.get('id') or '').strip() for item in _dict_list(asset_plan.get('assets')) if item.get('id') and str(item.get('kind') or 'figure') == 'figure'}
        manifest_ids = {str((item.get('metadata') or {}).get('semantic_key') or item.get('id') or '').strip() for item in entries}
        missing_assets = sorted(planned_ids - manifest_ids)
        if missing_assets:
            findings.append(_finding('FIG-PLAN-002', 'blocker', 'figure', f"Planned scientific assets are absent from the manifest: {', '.join(missing_assets)}", f"图表计划中的科研资产没有持久化到 manifest：{', '.join(missing_assets)}。", ['figures/SCIENTIFIC_ASSET_PLAN.json', 'figures/FIGURE_MANIFEST.json'], 'Render each planned asset once or explicitly remove it from the plan with a reason.'))
            findings[-1]['asset_ids'] = missing_assets
    if not _has_trusted_empirical_evidence(options):
        executed_entries = [str(item.get('id') or '') for item in entries if str((item.get('metadata') or {}).get('evidence_status') or '').casefold() == 'executed']
        if executed_entries:
            findings.append(_finding('FIG-EVID-001', 'blocker', 'evidence_state', f"Figure entries are marked executed in a no-run workflow: {', '.join(executed_entries[:8])}", '未运行实验的工作流中有图片被标记为 executed，可能把模板图升级为科研证据。', ['figures/FIGURE_MANIFEST.json'], 'Reclassify the asset as planned/design-only or bind it to a proven prior run.'))
    return {key: value for key, value in locals().items() if key in ['executed_entries', 'manifest_ids', 'missing_assets', 'planned_ids']}

def audit(service: Any, root: Path, options: dict[str, Any]) -> list[dict[str, Any]]:
    state = {'root': root, 'service': service, 'options': options}
    try:
        state.update(_rule_1(root=state['root']))
        state.update(_rule_2(asset_error=state['asset_error'], asset_plan=state['asset_plan'], entries=state['entries'], findings=state['findings'], options=state['options']))
    except _EarlyReturn as returned:
        return returned.value
    return state.get('findings', [])
